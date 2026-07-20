r"""
X3-DATA — kernel CPU de Kaggle: corpus de 3 DOMINIOS para X3 (04_MOM_GROKKING §6):
  cuentos  = ffuuugor/tinystories_spanish (text_es)
  wiki     = wikimedia/wikipedia 20231101.es con los filtros pre-registrados de K0
  codigo   = codeparrot/codeparrot-clean (Python; fallback code_search_net)
No toca los datos congelados de K3 (kernel aparte). Tokenizer BPE 16k PROPIO entrenado sobre
la mezcla equitativa de los 3 dominios. Separador <|doc|> id 0.

Salidas: tokenizer_3dom.json · train_dom_{stories,wiki,code}.bin · train_gen_mix3.bin
(tercios por documentos barajados) · val_{stories,wiki,code}.txt + val_*_3dom.bin ·
xh_x3data_meta.json (fertilidad por dominio en el held-out real).
USO local: venv312\Scripts\python.exe cognia_x/construccion/xhundred/xh_x3data_kernel.py --smoke
"""
import argparse
import hashlib
import json
import random
import re
import time

import numpy as np

META_PATH = "xh_x3data_meta.json"
DOM_TARGET = 120_000_000         # texto por dominio (experto 12 min ve ~11M tokens ≈ 45MB)
VAL_BYTES = 1_500_000
TOKENIZER_SAMPLE_PER_DOM = 33_000_000
VOCAB = 16384                    # veredicto E de K2
EOS = "<|doc|>"
SECTION_CUT = re.compile(r"^(Referencias|Enlaces externos|Véase también|Bibliografía)\s*$", re.M)


def filter_wiki_article(text, seen_hashes):
    m = SECTION_CUT.search(text)
    if m:
        text = text[:m.start()]
    lines = []
    for ln in text.split("\n"):
        s = ln.strip()
        if not s:
            lines.append("")
            continue
        alpha = sum(1 for c in s if c.isalpha() or c == " ") / len(s)
        if alpha < 0.55:
            continue
        if len(s) > 80:
            h = hashlib.md5(s.encode("utf-8", "ignore")).digest()[:8]
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
        lines.append(ln)
    out = "\n".join(lines).strip()
    return out if len(out) > 400 else None


def get_wiki(smoke, target):
    if smoke:
        rng = random.Random(1)
        base = ["la historia de espana tiene siglos de reyes y batallas que cambiaron europa. ",
                "la ciencia estudia los fenomenos naturales mediante hipotesis y experimentos. "]
        arts, tot = [], 0
        while tot < target:
            a = "".join(rng.choices(base, k=rng.randint(6, 20)))
            arts.append(a)
            tot += len(a)
        return arts
    from datasets import load_dataset
    ds = load_dataset("wikimedia/wikipedia", "20231101.es", split="train", streaming=True)
    arts, tot, seen = [], 0, set()
    for a in ds:
        t = a.get("text", "")
        if len(t) <= 500:
            continue
        ft = filter_wiki_article(t, seen)
        if ft:
            arts.append(ft)
            tot += len(ft)
        if tot >= target:
            break
    print(f"[wiki] {tot / 1e6:.0f}MB, {len(arts)} arts", flush=True)
    return arts


def get_stories(smoke, target):
    if smoke:
        rng = random.Random(2)
        base = ["habia una vez un nino que jugaba en el parque con su perro feliz. ",
                "la pequena sofia encontro una flor azul y se la llevo a su mama. "]
        arts, tot = [], 0
        while tot < target:
            a = "".join(rng.choices(base, k=rng.randint(4, 12)))
            arts.append(a)
            tot += len(a)
        return arts
    from datasets import load_dataset
    ds = load_dataset("ffuuugor/tinystories_spanish", split="train", streaming=True)
    arts, tot = [], 0
    for i, a in enumerate(ds):
        t = (a.get("text_es") or "").strip()
        if i < 5:
            assert t, f"muestra {i} vacia"
        if len(t) > 100:
            arts.append(t)
            tot += len(t)
        if tot >= target:
            break
    print(f"[stories] {tot / 1e6:.0f}MB, {len(arts)} cuentos", flush=True)
    return arts


def get_code(smoke, target):
    """Python real. codeparrot-clean (sin gating); fallback code_search_net."""
    if smoke:
        rng = random.Random(3)
        base = ["def suma(a, b):\n    return a + b\n\n",
                "class Punto:\n    def __init__(self, x, y):\n        self.x = x\n        self.y = y\n\n",
                "for i in range(10):\n    print(i * 2)\n\n"]
        arts, tot = [], 0
        while tot < target:
            a = "".join(rng.choices(base, k=rng.randint(3, 10)))
            arts.append(a)
            tot += len(a)
        return arts
    from datasets import load_dataset
    try:
        ds = load_dataset("codeparrot/codeparrot-clean", split="train", streaming=True)
        field = "content"
    except Exception as e:  # noqa: BLE001
        print(f"[code] codeparrot fallo ({e!r}) -> code_search_net", flush=True)
        ds = load_dataset("code_search_net", "python", split="train", streaming=True,
                          trust_remote_code=True)
        field = "whole_func_string"
    arts, tot = [], 0
    for a in ds:
        t = (a.get(field) or "").strip()
        if 200 < len(t) < 20000:
            arts.append(t)
            tot += len(t)
        if tot >= target:
            break
    print(f"[code] {tot / 1e6:.0f}MB, {len(arts)} archivos", flush=True)
    return arts


def train_bpe(sample_texts, vocab_size):
    from tokenizers import Tokenizer, models, pre_tokenizers, decoders, trainers
    tok = Tokenizer(models.BPE())
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    tr = trainers.BpeTrainer(vocab_size=vocab_size, min_frequency=2, special_tokens=[EOS],
                             initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
                             show_progress=False)
    tok.train_from_iterator(sample_texts, trainer=tr)
    return tok


def encode(tok, arts, eos_id, tag):
    parts = []
    for i in range(0, len(arts), 2000):
        for e in tok.encode_batch(arts[i:i + 2000]):
            parts.append(np.asarray(e.ids + [eos_id], dtype=np.uint16))
    ids = np.concatenate(parts) if parts else np.zeros(0, dtype=np.uint16)
    print(f"[encode-{tag}] {len(ids):,} tokens", flush=True)
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    target = 2_000_000 if args.smoke else DOM_TARGET
    val_b = 60_000 if args.smoke else VAL_BYTES
    vocab = 512 if args.smoke else VOCAB
    sample_per = 500_000 if args.smoke else TOKENIZER_SAMPLE_PER_DOM

    doms = {"stories": get_stories(args.smoke, target),
            "wiki": get_wiki(args.smoke, target),
            "code": get_code(args.smoke, target)}
    rng = random.Random(0)
    meta = {"experiment": "xh_x3data", "smoke": args.smoke, "domains": {}, "vocab": vocab}
    vals, trains = {}, {}
    for d, arts in doms.items():
        rng.shuffle(arts)
        val, tot = [], 0
        while arts and tot < val_b:
            a = arts.pop()
            val.append(a)
            tot += len(a)
        vals[d] = "\n\n".join(val)
        trains[d] = arts
        open(f"val_{d}.txt", "w", encoding="utf-8").write(vals[d])
        meta["domains"][d] = {"train_docs": len(arts),
                              "train_bytes": int(sum(len(a) for a in arts)),
                              "val_bytes": len(vals[d].encode("utf-8"))}
        print(f"[split-{d}] {meta['domains'][d]}", flush=True)

    sample = []
    for d in doms:
        s, tot = [], 0
        for a in trains[d]:
            s.append(a)
            tot += len(a)
            if tot >= sample_per:
                break
        sample += s
    tok = train_bpe(sample, vocab)
    eos_id = tok.token_to_id(EOS)
    assert eos_id == 0
    probe = trains["code"][0][:1500]
    assert tok.decode(tok.encode(probe).ids) == probe, "round-trip FALLO"
    tok.save("tokenizer_3dom.json")

    gen_docs = []
    for d in doms:                                # tercios por DOCUMENTOS, barajados
        acc, cap = [], meta["domains"][d]["train_bytes"] // 2
        tot = 0
        for a in trains[d]:
            acc.append(a)
            tot += len(a)
            if tot >= cap:
                break
        gen_docs += acc
    rng.shuffle(gen_docs)

    for d in doms:
        encode(tok, trains[d], eos_id, f"dom-{d}").tofile(f"train_dom_{d}.bin")
        va = encode(tok, [vals[d]], eos_id, f"val-{d}")
        va.tofile(f"val_{d}_3dom.bin")
        meta["domains"][d]["val_tokens"] = int(len(va))
        meta["domains"][d]["fertility"] = round(
            meta["domains"][d]["val_bytes"] / max(1, len(va)), 4)
    encode(tok, gen_docs, eos_id, "gen-mix3").tofile("train_gen_mix3.bin")
    meta["gen_docs"] = len(gen_docs)
    meta["minutes_total"] = round((time.time() - t0) / 60, 1)
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"[x3data] LISTO en {meta['minutes_total']} min | fertilidades: "
          f"{ {d: meta['domains'][d]['fertility'] for d in doms} }", flush=True)


if __name__ == "__main__":
    main()
