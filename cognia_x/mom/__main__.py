r"""CLI del MoM de CogniaX.

USO (venv312):
  python -m cognia_x.mom build-manifest [--src DIR] [--prefix x3|fleet] [--out PATH]
  python -m cognia_x.mom route "texto..."             # posterior + destino (sin cargar modelos)
  python -m cognia_x.mom gen "prompt..." [--n 150] [--force gen|stories|wiki|code]
  python -m cognia_x.mom eval                          # acc del selector + bpb wiring check
  python -m cognia_x.mom chat                          # loop interactivo con ruteo visible
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
XH = HERE.parents[0] / "construccion" / "xhundred"
DEFAULT_MANIFEST = HERE / "manifest.json"
DOMS = ("stories", "wiki", "code")


def _build(args):
    from .selector import Selector, eval_selector, tri_profile  # noqa: F401
    from .fleet import build_manifest, REPO_ROOT
    src = Path(args.src) if args.src else XH / "results_x3"
    # perfiles del selector desde la 1ª mitad de los val.txt; eval en la 2ª (held-out)
    halves_train, halves_eval = {}, {}
    for d in DOMS:
        t = (XH / "results_x3" / f"val_{d}.txt").read_text(encoding="utf-8")
        halves_train[d] = t[:len(t) // 2]
        halves_eval[d] = t[len(t) // 2:]
    sel = Selector.from_texts(halves_train, threshold=args.threshold)
    rep = eval_selector(sel, halves_eval)
    names = {"gen": f"{args.prefix}_gen.pt",
             **{d: f"{args.prefix}_exp_{d}.pt" for d in DOMS}}
    tok_rel = str((XH / "results_x3" / "tokenizer_3dom.json")
                  .relative_to(REPO_ROOT)).replace("\\", "/")
    out = Path(args.out) if args.out else DEFAULT_MANIFEST
    build_manifest(src, out, names, tok_rel, selector=sel)
    print(f"[build] manifest -> {out}")
    print(f"[build] selector held-out: {rep}")
    if rep["acc"] < 0.95:
        print("[build] AVISO: acc < 0.95 (gate X4) — revisar threshold/perfiles")


def _fleet(args):
    from .fleet import Fleet
    return Fleet(args.manifest)


def _route(args):
    from .selector import load_selector  # noqa: F401
    fl = _fleet(args)
    dest, post = fl.route(args.text)
    print(json.dumps({"destino": dest,
                      "posterior": {k: round(v, 3) for k, v in post.items()}},
                     ensure_ascii=False))


def _gen(args):
    fl = _fleet(args)
    t0 = time.time()
    txt, dest, post = fl.generate(args.text, n_new=args.n, force=args.force)
    dt = time.time() - t0
    print(f"[ruteo] destino={dest} posterior="
          f"{ {k: round(v, 3) for k, v in post.items()} } ({dt:.1f}s)")
    print("-" * 70)
    print(txt)


def _eval(args):
    import numpy as np
    import torch
    from .selector import eval_selector
    fl = _fleet(args)
    halves = {}
    for d in DOMS:
        t = (XH / "results_x3" / f"val_{d}.txt").read_text(encoding="utf-8")
        halves[d] = t[len(t) // 2:]
    print(f"[selector] {eval_selector(fl.selector, halves)}")
    # wiring check: bpb del experto en su dominio (ventana de val) ≈ números del kernel
    import math
    meta = json.loads((XH / "results_x3" / "xh_x3data_meta.json").read_text(encoding="utf-8"))
    for d in DOMS:
        va = np.fromfile(XH / "results_x3" / f"val_{d}_3dom.bin", dtype=np.uint16)
        ids = torch.from_numpy(va[:2049].astype(np.int64))
        tpb = meta["domains"][d]["val_tokens"] / meta["domains"][d]["val_bytes"]
        for name in ("gen", d):
            nll = fl.model(name).mean_nll(ids)
            print(f"[bpb-wiring] {name:8s} sobre {d:8s}: "
                  f"{nll * tpb / math.log(2):.4f} (4 ventanas)")


def _chat(args):
    fl = _fleet(args)
    print("MoM chat — escribí (vacío para salir). El ruteo se muestra por turno.")
    while True:
        try:
            q = input("vos> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            break
        txt, dest, post = fl.generate(q, n_new=args.n)
        print(f"[{dest} | { {k: round(v, 2) for k, v in post.items()} }]")
        print(txt)


def main():
    ap = argparse.ArgumentParser(prog="python -m cognia_x.mom")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-manifest")
    b.add_argument("--src", default=None)
    b.add_argument("--prefix", default="x3", choices=("x3", "fleet"))
    b.add_argument("--out", default=None)
    b.add_argument("--threshold", type=float, default=0.45)
    for name in ("route", "gen"):
        p = sub.add_parser(name)
        p.add_argument("text")
        p.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
        if name == "gen":
            p.add_argument("--n", type=int, default=150)
            p.add_argument("--force", default=None)
    e = sub.add_parser("eval")
    e.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    c = sub.add_parser("chat")
    c.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    c.add_argument("--n", type=int, default=120)
    args = ap.parse_args()
    {"build-manifest": _build, "route": _route, "gen": _gen,
     "eval": _eval, "chat": _chat}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
