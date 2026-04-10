#!/usr/bin/env python3
import os, sys, argparse, ast, json
from typing import List, Dict, Any, Optional

def should_skip_dir(name: str) -> bool:
    return name.startswith(".") or name in {"__pycache__", "venv", ".venv", "env", "build", "dist"}

def iter_py_files(paths: List[str]) -> List[str]:
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, fnames in os.walk(p):
                dirs[:] = [d for d in dirs if not should_skip_dir(d)]
                for fn in fnames:
                    if fn.endswith(".py"):
                        files.append(os.path.join(root, fn))
        elif p.endswith(".py") and os.path.exists(p):
            files.append(p)
    return files

def node_end_lineno(node: ast.AST) -> Optional[int]:
    end = getattr(node, "end_lineno", None)
    if isinstance(end, int):
        return end
    # Fallback: find max end_lineno among children (Python <3.8 or missing end)
    max_end = None
    for ch in ast.walk(node):
        e = getattr(ch, "end_lineno", None)
        if isinstance(e, int):
            if max_end is None or e > max_end:
                max_end = e
    return max_end

class FuncVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.stack: List[str] = []
        self.records: List[Dict[str, Any]] = []

    def visit_ClassDef(self, node: ast.ClassDef):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def _record_function(self, node: ast.AST, name: str, async_flag: bool):
        start = getattr(node, "lineno", None)
        end = node_end_lineno(node)
        if not isinstance(start, int) or not isinstance(end, int) or end < start:
            return
        length = end - start + 1
        qualname = ".".join(self.stack + [name]) if self.stack else name
        kind = "method" if any(isinstance(p, ast.ClassDef) for p in getattr(node, "parents", [])) else ("async_function" if async_flag else "function")
        self.records.append({
            "file": self.file_path,
            "qualname": qualname,
            "name": name,
            "lineno": start,
            "end_lineno": end,
            "length": length,
            "kind": kind,
        })

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._record_function(node, node.name, async_flag=False)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._record_function(node, node.name, async_flag=True)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

def annotate_parents(tree: ast.AST):
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            # attach a simple parents list (shallow; good enough to detect class nesting)
            plist = getattr(child, "parents", [])
            plist = list(plist) + [parent]
            setattr(child, "parents", plist)

def analyze_file(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError:
        return []
    annotate_parents(tree)
    v = FuncVisitor(path)
    v.visit(tree)
    return v.records

def main():
    ap = argparse.ArgumentParser(description="Report function/method lengths for refactoring.")
    ap.add_argument("paths", nargs="*", default=["."], help="Files or directories to scan (default: current dir)")
    ap.add_argument("--min", type=int, default=0, dest="min_len", help="Only show functions with length >= MIN")
    ap.add_argument("--top", type=int, default=0, help="Show only the TOP longest functions")
    ap.add_argument("--by-file", action="store_true", help="Group output by file")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    ap.add_argument("--sort", choices=["length","name","file"], default="length", help="Sort key (default: length)")
    ap.add_argument("--reverse", action="store_true", help="Reverse sort order (default: longest first when sort=length)")
    args = ap.parse_args()

    files = iter_py_files(args.paths)
    all_recs: List[Dict[str, Any]] = []
    for fp in files:
        all_recs.extend(analyze_file(fp))

    # Filter by min length
    if args.min_len > 0:
        all_recs = [r for r in all_recs if r["length"] >= args.min_len]

    # Sort
    if args.sort == "length":
        all_recs.sort(key=lambda r: r["length"], reverse=(not args.reverse))
    elif args.sort == "name":
        all_recs.sort(key=lambda r: (r["qualname"], r["file"]), reverse=args.reverse)
    else:  # file
        all_recs.sort(key=lambda r: (r["file"], r["lineno"]), reverse=args.reverse)

    # Top-K
    if args.top and args.top > 0:
        all_recs = all_recs[:args.top]

    if args.json:
        print(json.dumps(all_recs, ensure_ascii=False, indent=2))
        return

    # Text output
    if args.by_file:
        from itertools import groupby
        for file_path, group in groupby(all_recs, key=lambda r: r["file"]):
            print(f"\n* ={file_path}=")
            for r in group:
                print(f"|{r['length']:5d} | {r['lineno']:5d}-{r['end_lineno']:5d} |  ~{r['qualname']}~ |")
    else:
        for r in all_recs:
            print(f"| {r['length']:5d} | {r['file']}:{r['lineno']:d}-{r['end_lineno']:d}|  ~{r['qualname']}~ |")

if __name__ == "__main__":
    main()
