#!/usr/bin/env python3
import os, json, time, argparse, random
import logging
logger = logging.getLogger("train_tokenizer")
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from backend.core.profile import Profile

PAD = "<pad>"; BOS = "<bos>"; EOS = "<eos>"

def load_dataset(path):
    pairs = []
    with open(path, "r", encoding="utf-8") as f:
        hdr = f.readline().strip().split("\t")
        idx = {h: i for i, h in enumerate(hdr)}
        for ln in f:
            if not ln.strip(): continue
            cols = ln.rstrip("\n").split("\t")
            src = cols[idx["src"]]
            tgt = cols[idx["tgt"]]
            pairs.append((src, tgt))
    return pairs

def build_vocabs(pairs, token_delim="-"):
    src_chars = {PAD, BOS, EOS}
    tgt_toks = {PAD, BOS, EOS}
    for src, tgt in pairs:
        src_chars.update(list(src))
        tgt_toks.update(list(tgt))
    src2i = {c: i for i, c in enumerate(sorted(src_chars))}
    i2src = {i: c for c, i in src2i.items()}
    tgt2i = {t: i for i, t in enumerate(sorted(tgt_toks))}
    i2tgt = {i: t for t, i in tgt2i.items()}
    return (src2i, i2src, tgt2i, i2tgt)

class TokDataset(Dataset):
    def __init__(self, pairs, src2i, tgt2i, token_delim="-", max_src=None, max_tgt=None):
        self.data = pairs
        self.src2i = src2i; self.tgt2i = tgt2i
        self.token_delim = token_delim
        self.max_src = max_src; self.max_tgt = max_tgt
    def __len__(self): return len(self.data)
    def __getitem__(self, idx):
        src, tgt = self.data[idx]
        src_ids = [self.src2i[BOS]] + [self.src2i.get(ch, self.src2i[PAD]) for ch in src] + [self.src2i[EOS]]
        tgt_ids = [self.tgt2i[BOS]] + [self.tgt2i.get(tok, self.tgt2i[PAD]) for tok in tgt.split(self.token_delim)] + [self.tgt2i[EOS]]
        if self.max_src: src_ids = src_ids[:self.max_src]
        if self.max_tgt: tgt_ids = tgt_ids[:self.max_tgt]
        return torch.tensor(src_ids, dtype=torch.long), torch.tensor(tgt_ids, dtype=torch.long)

def collate(batch):
    src_seqs, tgt_seqs = zip(*batch)
    src_lens = [len(x) for x in src_seqs]; tgt_lens = [len(x) for x in tgt_seqs]
    max_src = max(src_lens); max_tgt = max(tgt_lens)
    pad_src = torch.full((len(batch), max_src), fill_value=0, dtype=torch.long)
    pad_tgt = torch.full((len(batch), max_tgt), fill_value=0, dtype=torch.long)
    for i, (s, t) in enumerate(zip(src_seqs, tgt_seqs)):
        pad_src[i, :len(s)] = s
        pad_tgt[i, :len(t)] = t
    return pad_src, torch.tensor(src_lens), pad_tgt, torch.tensor(tgt_lens)

class Encoder(nn.Module):
    def __init__(self, vocab_size, emb_dim, hid, layers=1, dropout=0.1):
        super().__init__()
        self.emb = nn.Embedding(vocab_size, emb_dim, padding_idx=0)
        self.rnn = nn.LSTM(emb_dim, hid, num_layers=layers, batch_first=True, bidirectional=False, dropout=dropout if layers>1 else 0.0)
    def forward(self, x, lengths):
        emb = self.emb(x)
        packed = nn.utils.rnn.pack_padded_sequence(emb, lengths.cpu(), batch_first=True, enforce_sorted=False)
        out, (h, c) = self.rnn(packed)
        return h, c

class Decoder(nn.Module):
    def __init__(self, vocab_size, emb_dim, hid, layers=1, dropout=0.1):
        super().__init__()
        self.emb = nn.Embedding(vocab_size, emb_dim, padding_idx=0)
        self.rnn = nn.LSTM(emb_dim, hid, num_layers=layers, batch_first=True, dropout=dropout if layers>1 else 0.0)
        self.proj = nn.Linear(hid, vocab_size)
    def forward(self, y_in, h, c):
        emb = self.emb(y_in)
        out, (h, c) = self.rnn(emb, (h, c))
        logits = self.proj(out)
        return logits, h, c

class Seq2Seq(nn.Module):
    def __init__(self, enc, dec):
        super().__init__()
        self.enc = enc; self.dec = dec
    def forward(self, src, src_lens, tgt, teacher_forcing=0.5):
        B = src.size(0)
        h, c = self.enc(src, src_lens)
        max_len = tgt.size(1) - 1
        y = tgt[:, 0].unsqueeze(1)
        logits_all = []
        for t in range(max_len):
            logits, h, c = self.dec(y, h, c)
            logits_all.append(logits)
            use_teacher = random.random() < teacher_forcing
            next_y = tgt[:, t+1] if use_teacher else logits.squeeze(1).argmax(-1)
            y = next_y.unsqueeze(1)
        return torch.cat(logits_all, dim=1)

def train_loop(model, loader, tgt_pad_idx, epochs=5, lr=1e-3, device="cpu"):
    model.to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    crit = nn.CrossEntropyLoss(ignore_index=tgt_pad_idx)
    for ep in range(1, epochs+1):
        t0 = time.perf_counter()
        model.train()
        total = 0.0; steps = 0
        for src, src_lens, tgt, tgt_lens in loader:
            src, src_lens, tgt = src.to(device), src_lens.to(device), tgt.to(device)
            logits = model(src, src_lens, tgt, teacher_forcing=0.5)
            gold = tgt[:, 1:]
            loss = crit(logits.reshape(-1, logits.size(-1)), gold.reshape(-1))
            opt.zero_grad(); loss.backward(); opt.step()
            total += loss.item(); steps += 1
        avg = total / max(1, steps)
        dur_ms = int((time.perf_counter() - t0) * 1000)
        print(f"epoch {ep} loss {avg:.4f}")
        logger.info("epoch=%d loss=%.4f dur_ms=%d steps=%d", ep, avg, dur_ms, steps)

def save_model(out_dir, model, cfg, vocabs):
    logger.info("saving model to %s", out_dir)
    os.makedirs(out_dir, exist_ok=True)
    torch.save(model.state_dict(), os.path.join(out_dir, "model.pt"))
    with open(os.path.join(out_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "vocab.json"), "w", encoding="utf-8") as f:
        json.dump(vocabs, f, ensure_ascii=False, indent=2)

def encode_src(word, src2i):
    ids = [src2i.get(BOS, 1)] + [src2i.get(ch, src2i.get(PAD, 0)) for ch in word] + [src2i.get(EOS, 2)]
    return torch.tensor(ids, dtype=torch.long)

def decode_ids(ids, i2tgt, delim="-"):
    toks = [i2tgt.get(i, "") for i in ids]
    toks = [t for t in toks if t not in (PAD, BOS, EOS, "")]
    return delim.join(toks)

@torch.no_grad()
def greedy_decode(model, src_batch, src_lens, bos_idx, eos_idx, max_len):
    h, c = model.enc(src_batch, src_lens)
    y = torch.full((src_batch.size(0), 1), bos_idx, dtype=torch.long, device=src_batch.device)
    toks = []
    for _ in range(max_len):
        logits, h, c = model.dec(y, h, c)
        next_tok = logits.squeeze(1).argmax(-1)
        toks.append(next_tok)
        y = next_tok.unsqueeze(1)
    out = torch.stack(toks, dim=1)
    res = []
    for i in range(out.size(0)):
        row = out[i].tolist()
        if eos_idx in row:
            row = row[:row.index(eos_idx)]
        res.append(row)
    return res

def run_infer(words, model, cfg, src2i, tgt2i, i2tgt, device="cpu", max_len=None, batch_size=256):
    logger.info("infer: words=%d batch_size=%d device=%s", len(words), batch_size, device)
    model.eval()
    delim = cfg.get("token_delim", "-")
    bos_idx = tgt2i[BOS]; eos_idx = tgt2i[EOS]
    out = []
    for i in range(0, len(words), batch_size):
        batch_words = words[i:i+batch_size]
        tensors = [encode_src(w, src2i) for w in batch_words]
        lens = torch.tensor([len(t) for t in tensors], dtype=torch.long)
        maxL = int(max(lens).item())
        pad_id = 0
        B = len(batch_words)
        src = torch.full((B, maxL), fill_value=pad_id, dtype=torch.long)
        for bi, t in enumerate(tensors):
            src[bi, :len(t)] = t
        src = src.to(device); lens = lens.to(device)
        dec_max = max_len if max_len is not None else max(4, int(maxL * 2))
        pred_ids = greedy_decode(model, src, lens, bos_idx=bos_idx, eos_idx=eos_idx, max_len=dec_max)
        for w, ids in zip(batch_words, pred_ids):
            out.append((w, decode_ids(ids, i2tgt, delim=delim)))
    return out

def evaluate(dataset_path, model, cfg, src2i, tgt2i, i2tgt, device="cpu", max_len=None):
    logger.info("evaluate: dataset=%s", dataset_path)
    pairs = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        hdr = f.readline().strip().split("\t")
        idx = {h:i for i,h in enumerate(hdr)}
        for ln in f:
            if not ln.strip(): continue
            c = ln.rstrip("\n").split("\t")
            pairs.append((c[idx["src"]], c[idx["tgt"]]))
    if not pairs:
        print("Eval dataset is empty")
        return 0.0
    words = [w for w,_ in pairs]
    preds = dict(run_infer(words, model, cfg, src2i, tgt2i, i2tgt, device=device, max_len=max_len))
    hit = sum(1 for w,g in pairs if preds.get(w, "") == g)
    acc = hit / max(1, len(pairs))
    print(f"Eval: {hit}/{len(pairs)} = {acc:.4f} exact-match accuracy")
    logger.info("evaluate: exact_match=%d/%d acc=%.4f", hit, len(pairs), acc)
    return acc

def load_model(model_dir, device="cpu"):
    with open(os.path.join(model_dir, "config.json"), "r", encoding="utf-8") as f:
        cfg = json.load(f)
    with open(os.path.join(model_dir, "vocab.json"), "r", encoding="utf-8") as f:
        voc = json.load(f)
    src2i = voc["src2i"]; tgt2i = voc["tgt2i"]
    i2tgt = {int(k): v for k, v in voc["i2tgt"].items()}
    enc = Encoder(vocab_size=len(src2i), emb_dim=cfg["emb"], hid=cfg["hidden"], layers=cfg["layers"])
    dec = Decoder(vocab_size=len(tgt2i), emb_dim=cfg["emb"], hid=cfg["hidden"], layers=cfg["layers"])
    model = Seq2Seq(enc, dec).to(device)
    sd = torch.load(os.path.join(model_dir, "model.pt"), map_location=device)
    model.load_state_dict(sd)
    model.eval()
    return model, cfg, src2i, tgt2i, i2tgt

def choose_dataset(prof, ds_path):
    logger.debug("choose_dataset: requested=%s", ds_path)
    if ds_path:
        logger.info("choose_dataset: using %s", ds_path)
        return ds_path
    try:
        cands = [p for p in os.listdir(prof.datasets_dir) if p.startswith("tokenizer-") and p.endswith(".tsv")]
        if not cands:
            raise SystemExit("No dataset found. Run: python -m tools.export_dataset --profile ...")
        chosen = os.path.join(prof.datasets_dir, sorted(cands)[-1])
        logger.info("choose_dataset: using %s", chosen)
        return chosen
    except FileNotFoundError:
        logger.error("choose_dataset: datasets dir not found under %s", prof.datasets_dir)
        raise SystemExit("No dataset dir found. Run exporter first.")

def prepare_vocabs_and_loader(pairs, args):
    logger.info("prepare_vocabs: token_delim=%s", args.token_delim)
    src2i, i2src, tgt2i, i2tgt = build_vocabs(pairs, token_delim=args.token_delim)
    if PAD in src2i and src2i[PAD] != 0:
        def remap(v):
            it = sorted(v.items(), key=lambda kv: kv[1])
            keys = [k for k, _ in it]
            new = {k: i for i, k in enumerate(keys)}
            return new, {i: k for k, i in new.items()}
        src2i, i2src = remap(src2i)
    if PAD in tgt2i and tgt2i[PAD] != 0:
        def remap(v):
            it = sorted(v.items(), key=lambda kv: kv[1])
            keys = [k for k, _ in it]
            new = {k: i for i, k in enumerate(keys)}
            return new, {i: k for k, i in new.items()}
        tgt2i, i2tgt = remap(tgt2i)
    ds = TokDataset(pairs, src2i, tgt2i, token_delim=args.token_delim)
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=True, collate_fn=collate)
    logger.info("vocabs: src=%d tgt=%d batch_size=%d", len(src2i), len(tgt2i), args.batch_size)
    return (src2i, i2src, tgt2i, i2tgt), loader

def train_and_save(prof, args, vocabs, loader):
    logger.info("train: emb=%d hidden=%d layers=%d lr=%g epochs=%d batch=%d device=%s",
                args.emb, args.hidden, args.layers, args.lr, args.epochs, args.batch_size, args.device)
    src2i, i2src, tgt2i, i2tgt = vocabs
    enc = Encoder(vocab_size=len(src2i), emb_dim=args.emb, hid=args.hidden, layers=args.layers)
    dec = Decoder(vocab_size=len(tgt2i), emb_dim=args.emb, hid=args.hidden, layers=args.layers)
    model = Seq2Seq(enc, dec)
    train_loop(model, loader, tgt_pad_idx=tgt2i[PAD], epochs=args.epochs, lr=args.lr, device=args.device)
    ts = time.strftime("%Y%m%dT%H%M%S", time.localtime())
    out_dir = os.path.join(prof.models_dir, ts)
    cfg = {
        "emb": args.emb, "hidden": args.hidden, "layers": args.layers, "lr": args.lr,
        "token_delim": args.token_delim, "src_vocab": len(src2i), "tgt_vocab": len(tgt2i),
        "dataset": os.path.abspath(args.dataset) if args.dataset else ""
    }
    voc = {"src2i": src2i, "i2src": i2src, "tgt2i": tgt2i, "i2tgt": i2tgt, "special": {"PAD": PAD, "BOS": BOS, "EOS": EOS}}
    save_model(out_dir, model, cfg, voc)
    print(f"Saved model to {out_dir}")
    logger.info("saved_dir=%s", out_dir)
    return out_dir, model, cfg, (src2i, i2src, tgt2i, i2tgt)

def maybe_run_eval_and_infer(args, model, cfg, src2i, i2tgt, tgt2i):
    logger.info("post_train: eval_dataset=%s infer_words=%d infer_file=%s infer_out=%s",
                args.eval_dataset, len(args.infer_words or []), bool(args.infer_file), args.infer_out or "")
    if args.eval_dataset:
        evaluate(args.eval_dataset, model, cfg, src2i, tgt2i, i2tgt, device=args.device, max_len=args.max_decode_len)
    words = []
    if args.infer_words:
        words.extend(args.infer_words)
    if args.infer_file:
        with open(args.infer_file, "r", encoding="utf-8") as f:
            for ln in f:
                w = ln.strip()
                if w:
                    words.append(w)
    if words:
        preds = run_infer(words, model, cfg, src2i, tgt2i, i2tgt, device=args.device, max_len=args.max_decode_len)
        if args.infer_out:
            os.makedirs(os.path.dirname(args.infer_out), exist_ok=True)
            with open(args.infer_out, "w", encoding="utf-8") as o:
                print("word\tpred", file=o)
                for w, p in preds:
                    print(f"{w}\t{p}", file=o)
            print(f"Wrote predictions for {len(preds)} word(s) to {args.infer_out}")
        else:
            for w, p in preds:
                print(f"{w}\t{p}")

def build_arg_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="default")
    ap.add_argument("--base-dir", default=None)
    ap.add_argument("--dataset", default=None, help="Path to tokenizer-*.tsv. If omitted, use the latest in profile datasets dir.")
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--emb", type=int, default=128)
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--layers", type=int, default=1)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--token_delim", default="-")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--model-dir", default=None, help="Use an existing saved model dir for eval/infer; if set with --no_train, skips training")
    ap.add_argument("--no-train", action="store_true", help="Skip training and only run eval/infer with --model_dir")
    ap.add_argument("--eval-dataset", default=None, help="Evaluate exact-match accuracy on a TSV (header: src<TAB>tgt)")
    ap.add_argument("--infer-words", nargs="*", default=None, help="Words to tokenize (space-separated)")
    ap.add_argument("--infer-file", default=None, help="Path to a file with one word per line")
    ap.add_argument("--infer-out", default=None, help="Optional TSV output path for inference (word<TAB>pred)")
    ap.add_argument("--max-decode_len", type=int, default=None, help="Optional max output tokens for greedy decode")
    return ap

def main():
    ap = build_arg_parser()
    args = ap.parse_args()
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

    prof = Profile(name=args.profile, base_dir=args.base_dir)

    if args.no_train:
        if not args.model_dir:
            raise SystemExit("--no_train requires --model_dir to load a saved model")
        model, cfg, src2i, tgt2i, i2tgt = load_model(args.model_dir, device=args.device)
        logger.info("load model only: dir=%s", args.model_dir)
        maybe_run_eval_and_infer(args, model, cfg, src2i, i2tgt, tgt2i)
        return

    ds_path = choose_dataset(prof, args.dataset)
    logger.info("using dataset: %s", ds_path)
    print(f"Using dataset: {ds_path}")
    pairs = load_dataset(ds_path)
    if not pairs:
        raise SystemExit("Dataset is empty")
    logger.info("loaded pairs: %d", len(pairs))
    vocabs, loader = prepare_vocabs_and_loader(pairs, args)
    out_dir, model, cfg, (src2i, i2src, tgt2i, i2tgt) = train_and_save(prof, args, vocabs, loader)
    logger.info("model saved: %s (emb=%d hidden=%d layers=%d epochs=%d batch=%d)",
                out_dir, args.emb, args.hidden, args.layers, args.epochs, args.batch_size)
    cfg["dataset"] = os.path.abspath(ds_path)
    maybe_run_eval_and_infer(args, model, cfg, src2i, i2tgt, tgt2i)

if __name__ == "__main__":
    main()
