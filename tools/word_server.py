#!/usr/bin/env python3
import os, sys, time, shlex, argparse, fcntl, re as stdre
import socket, socketserver
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

REQUIRED_BATCH_HDR = ("id", "word", "freq", "glen", "splits", "status", "notes")
LEDGER_HDR = ("timestamp", "batch", "id", "word", "status", "splits", "notes")

from urllib.parse import unquote

def percent_decode(s):
    return unquote(s)

def parse_params(line):
    toks = line.strip().split()
    cmd = toks[0]
    params = {}
    for t in toks[1:]:
        if "=" in t:
            k, v = t.split("=", 1)
            params[k] = percent_decode(v)
    return cmd, params

from tools.word_indexer import WordIndex

class State:
    def __init__(self, wordlist_path, ledger_path):
        self.wordlist_path = wordlist_path
        self.ledger_path = ledger_path
        self.word_index = WordIndex(wordlist_path)
        self.words = self.word_index.words  # For backwards compatibility if needed.
        self.words_by_len = self.words    # Already sorted.
        self.latest_status = {}  # word -> status
        self.accepted = set()
        self._load_ledger()

    def _load_wordlist(self):
        words = []
        with open(self.wordlist_path, "r", encoding="utf-8") as f:
            header = f.readline().strip().split("\t")
            idx = {h:i for i,h in enumerate(header)}
            for line in f:
                if not line.strip(): continue
                cols = line.rstrip("\n").split("\t")
                w = cols[idx["word"]]
                fr = int(cols[idx["freq"]])
                gl = int(cols[idx["glen"]])
                words.append((w,fr,gl))
        self.words = words
        self.words_by_len = sorted(words, key=lambda x: (-x[2], -x[1], x[0]))

    def _load_ledger(self):
        latest = {}
        if os.path.exists(self.ledger_path):
            with open(self.ledger_path, "r", encoding="utf-8") as f:
                hdr = f.readline().strip().split("\t")
                if set(hdr) >= set(LEDGER_HDR):
                    idx = {h:i for i,h in enumerate(hdr)}
                    for line in f:
                        if not line.strip(): continue
                        cols = line.rstrip("\n").split("\t")
                        w = cols[idx["word"]]
                        st = cols[idx["status"]]
                        latest[w] = st
        self.latest_status = latest
        self.accepted = {w for (w, st) in latest.items() if st == "accepted"}

    def reload(self, what):
        if what in ("wordlist","both"):
            self._load_wordlist()
        if what in ("ledger","both"):
            self._load_ledger()

class Handler(socketserver.StreamRequestHandler):
    # State is injected via server
    def handle(self):
        line = self.rfile.readline().decode("utf-8")
        if not line:
            return
        logging.info("Received raw command: %s", line.strip())
        cmd, params = parse_params(line)
        if cmd == "QUERY":
            self._handle_query(params)
        elif cmd == "COMMIT":
            self._handle_commit(params)
        elif cmd == "RELOAD":
            self._handle_reload(params)
        elif cmd == "STATS":
            self._handle_stats()
        else:
            self._write_err("bad_command", f"Unknown: {cmd}")

    def _write_ok(self, kv=None):
        kvs = " ".join(f"{k}={v}" for k,v in (kv or {}).items())
        self.wfile.write((f"OK {kvs}\n").encode("utf-8"))

    def _write_err(self, code, msg):
        self.wfile.write((f"ERR code={code} msg={msg}\n").encode("utf-8"))

    def _handle_query(self, p):
        prefix = p.get("prefix","")
        suffix = p.get("suffix","")
        try: min_len = int(p.get("min_len","1"))
        except: min_len = 1
        try: limit = int(p.get("limit","200"))
        except: limit = 200
        try: offset = int(p.get("offset","0"))
        except: offset = 0
        exclude = p.get("exclude_accepted","0") in ("1","true","yes","on")
        rx_pat = p.get("regex","")
        rx = None
        if rx_pat:
            try:
                rx = stdre.compile(rx_pat)
            except Exception as e:
                self._write_err("bad_regex", str(e)); return

        def exclude_fn(word):
            return exclude and (word in self.server.state.accepted)
        
        out_rows = self.server.state.word_index.query_words(
            prefix=prefix,
            suffix=suffix,
            min_len=min_len,
            limit=limit,
            offset=offset,
            exclude_fn=exclude_fn,
            regex=rx_pat
        )

        logging.info("QUERY params: %s; returning %d words", p, len(out_rows))
        self._write_ok({"rows":len(out_rows)})
        self.wfile.write(("\t".join(REQUIRED_BATCH_HDR) + "\n").encode("utf-8"))
        for w,fr,gl in out_rows:
            self.wfile.write(f"{w}\t{fr}\t{gl}\t\ttodo\t\n".encode("utf-8"))

    def _handle_commit(self, p):
        batch = p.get("batch","unnamed")
        try:
            rows = int(p.get("rows","0"))
        except:
            self._write_err("bad_rows","rows must be int"); return
        if rows <= 0:
            self._write_err("bad_rows","rows must be > 0"); return

        lines = []
        for _ in range(rows):
            ln = self.rfile.readline().decode("utf-8")
            if not ln:
                self._write_err("bad_body","unexpected EOF"); return
            lines.append(ln.rstrip("\n"))

        hdr = lines[0].split("\t")
        if tuple(hdr[:len(REQUIRED_BATCH_HDR)]) != REQUIRED_BATCH_HDR:
            self._write_err("bad_header", f"expected {REQUIRED_BATCH_HDR}, got {hdr}")
            return

        col = {h:i for i,h in enumerate(hdr)}
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        os.makedirs(os.path.dirname(self.server.ledger_path), exist_ok=True)
        write_header = not os.path.exists(self.server.ledger_path) or os.path.getsize(self.server.ledger_path) == 0
        committed = 0
        accepted_added = 0
        with open(self.server.ledger_path, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                if write_header:
                    f.write("\t".join(LEDGER_HDR) + "\n")
                for ln in lines[1:]:
                    if not ln.strip(): continue
                    c = ln.split("\t")
                    # Use the 'id' from the TSV; if missing, default to the word.
                    rec_id = c[col["id"]].strip() if col.get("id") is not None and len(c) > col["id"] else ""
                    w    = c[col["word"]].strip()
                    status = (c[col["status"]].strip() or "todo")
                    splits = c[col["splits"]].strip()
                    notes  = c[col["notes"]].strip() if len(c) > col["notes"] else ""
                    # Write both id and word to ledger.
                    f.write(f"{ts}\t{batch}\t{rec_id or w}\t{w}\t{status}\t{splits}\t{notes}\n")
                    committed += 1
                    # update latest status in memory
                    self.server.state.latest_status[w] = status
                    if status == "accepted":
                        if w not in self.server.state.accepted:
                            accepted_added += 1
                        self.server.state.accepted.add(w)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        logging.info("COMMIT batch=%s: committed %d rows; accepted_added=%d", batch, committed, accepted_added)
        self._write_ok({"committed":committed, "accepted_added":accepted_added})

    def _handle_reload(self, p):
        what = p.get("what","both")
        if what not in ("ledger","wordlist","both"):
            self._write_err("bad_param","what must be ledger|wordlist|both"); return
        self.server.state.reload(what)
        logging.info("RELOAD: %s", what)
        self._write_ok({"reloaded":what})

    def _handle_stats(self):
        wl = self.server.state.wordlist_path
        lg = self.server.ledger_path
        wl_m = os.path.getmtime(wl) if os.path.exists(wl) else 0
        lg_m = os.path.getmtime(lg) if os.path.exists(lg) else 0
        kv = {
            "words": len(self.server.state.words),
            "accepted": len(self.server.state.accepted),
            "ledger_lines": sum(1 for _ in open(lg, "r", encoding="utf-8"))-1 if os.path.exists(lg) and os.path.getsize(lg)>0 else 0,
            "wordlist_mtime": int(wl_m),
            "ledger_mtime": int(lg_m),
        }
        logging.info("STATS: %s", kv)
        self._write_ok(kv)

class UnixServer(socketserver.UnixStreamServer):
    def __init__(self, sock_path, state):
        if os.path.exists(sock_path):
            os.unlink(sock_path)
        os.makedirs(os.path.dirname(sock_path), exist_ok=True)
        super().__init__(sock_path, Handler)
        self.state = state
        self.ledger_path = state.ledger_path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", default="run/tamil_words.sock")
    ap.add_argument("--profile", default="default",
                    help="Profile name to choose different corpora")
    ap.add_argument("--base_dir", default=None,
                    help="Optional base directory for the profile")
    args = ap.parse_args()
    if not os.path.exists(args.wordlist):
        sys.stderr.write(f"wordlist not found: {args.wordlist}\n"); sys.exit(2)
    os.makedirs(os.path.dirname(args.ledger), exist_ok=True)
    from tools.profile import Profile
    profile = Profile(name=args.profile, base_dir=args.base_dir)
    wordlist_path = profile.wordlist_path
    ledger_path = profile.ledger_path
    socket_path = profile.socket_path
    state = State(wordlist_path, ledger_path)
    srv = UnixServer(socket_path, state)
    print(f"Server ready on {args.socket}; words={len(state.words)} accepted={len(state.accepted)}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        if os.path.exists(args.socket):
            os.unlink(args.socket)

if __name__ == "__main__":
    main()
