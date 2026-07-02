r"""
XH-DATA — kernel CPU de Kaggle: prepara el corpus tokenizado para XHUNDRED (100M en <=30 min T4).
La preparación de datos es ONE-TIME (como descargar un dataset): no cuenta en los 30 min de
entreno. Pre-registrado en 00_DISENO.md.

Hace: descarga es-wiki (streaming HF, patrón probado en xfinal_kernel.py), entrena BPE byte-level
PROPIOS (32k y 16k) sobre una muestra, encodea el corpus completo a uint16 y emite:
  tokenizer_32k.json / train_32k.bin / val_32k.bin
  tokenizer_16k.json / train_16k.bin / val_16k.bin
  train_bytes.bin (uint8, cap 200MB — para el brazo byte-vs-BPE) / val.txt
  xh_data_meta.json (fertilidad, conteos, timings — normalización bpb entre brazos)

USO local:  venv312\Scripts\python.exe cognia_x/construccion/xhundred/xh_data_kernel.py --smoke
USO Kaggle: push via run_kaggle_xh.py data (kernel CPU, sin quota GPU)
"""
import argparse
import json
import random
import time

import numpy as np

META_PATH = "xh_data_meta.json"
TARGET_BYTES = 600_000_000       # texto crudo objetivo (~140M tokens BPE-32k > presupuesto de 30 min)
VAL_BYTES = 2_000_000            # held-out para bpb/ppl
BYTES_BIN_CAP = 200_000_000      # el brazo byte-level ve <=75M tokens en su wall — 200MB sobra
TOKENIZER_SAMPLE_BYTES = 200_000_000
VOCABS = (32768, 16384)
EOS = "<|endoftext|>"


def get_articles(smoke, target_bytes):
    """Lista de artículos (str). es-wiki streaming con filtro mínimo; fallback wikitext-103."""
    if smoke:
        base = [
            "la casa es azul y el cielo se llena de nubes blancas cuando llueve en la montana. ",
            "los gatos duermen al sol mientras los ninos juegan en el parque de la ciudad vieja. ",
            "la historia de espana tiene siglos de reyes, guerras, arte y ciencia que cambiaron europa. ",
            "el rio baja de la cordillera y riega los campos de trigo antes de llegar al mar abierto. ",
            "la ciencia estudia los fenomenos naturales mediante hipotesis, experimentos y evidencia. ",
        ]
        rng = random.Random(0)
        arts, total = [], 0
        while total < target_bytes:
            art = "".join(rng.choices(base, k=rng.randint(8, 30)))
            arts.append(art)
            total += len(art)
        return arts
    from datasets import load_dataset
    try:
        ds = load_dataset("wikimedia/wikipedia", "20231101.es", split="train", streaming=True)
        arts, total, t0 = [], 0, time.time()
        for a in ds:
            t = a.get("text", "")
            if len(t) > 500:
                arts.append(t)
                total += len(t)
            if len(arts) % 20000 == 0 and arts:
                print(f"[data] {total/1e6:.0f}MB / {len(arts)} articulos ({time.time()-t0:.0f}s)", flush=True)
            if total >= target_bytes:
                break
        print(f"[data] es-wiki: {total/1e6:.0f}MB, {len(arts)} articulos", flush=True)
        return arts
    except Exception as e:  # noqa: BLE001
        print(f"[data] es-wiki fallo ({e!r}) -> wikitext-103", flush=True)
        ds = load_dataset("wikitext", "wikitext-103-raw-v1", split="train")
        arts, total = [], 0
        for t in ds["text"]:
            if len(t.strip()) > 200:
                arts.append(t)
                total += len(t)
            if total >= target_bytes:
                break
        return arts


def train_bpe(sample_texts, vocab_size):
    from tokenizers import Tokenizer, models, pre_tokenizers, decoders, trainers
    tok = Tokenizer(models.BPE())
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(
        vocab_size=vocab_size, min_frequency=2, special_tokens=[EOS],
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet(), show_progress=False)
    tok.train_from_iterator(sample_texts, trainer=trainer)
    return tok


def encode_corpus(tok, articles, eos_id, chunk=2000):
    """Encodea articulos + EOS entre docs -> np.uint16. encode_batch usa los cores de rust."""
    parts = []
    for i in range(0, len(articles), chunk):
        encs = tok.encode_batch(articles[i:i + chunk])
        for e in encs:
            parts.append(np.asarray(e.ids + [eos_id], dtype=np.uint16))
        if (i // chunk) % 20 == 0:
            print(f"[encode] {i}/{len(articles)}", flush=True)
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.uint16)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    target = 3_000_000 if args.smoke else TARGET_BYTES
    vocabs = (512, 384) if args.smoke else VOCABS
    sample_cap = 1_000_000 if args.smoke else TOKENIZER_SAMPLE_BYTES
    val_bytes = 100_000 if args.smoke else VAL_BYTES

    arts = get_articles(args.smoke, target)
    rng = random.Random(0)
    rng.shuffle(arts)
    # split por articulos (val nunca visto en train ni en el entreno del tokenizer)
    val_arts, val_total = [], 0
    while arts and val_total < val_bytes:
        a = arts.pop()
        val_arts.append(a)
        val_total += len(a)
    train_text_bytes = sum(len(a) for a in arts)
    val_text = "\n\n".join(val_arts)
    with open("val.txt", "w", encoding="utf-8") as f:
        f.write(val_text)
    print(f"[split] train={train_text_bytes/1e6:.0f}MB ({len(arts)} arts) val={val_total/1e6:.2f}MB", flush=True)

    # brazo byte-level: mismos datos, uint8 crudo (cap)
    buf, total = [], 0
    for a in arts:
        b = a.encode("utf-8", "ignore") + b"\n\n"
        buf.append(b)
        total += len(b)
        if total >= (500_000 if args.smoke else BYTES_BIN_CAP):
            break
    np.frombuffer(b"".join(buf), dtype=np.uint8).tofile("train_bytes.bin")
    print(f"[bytes] train_bytes.bin={total/1e6:.0f}MB", flush=True)

    # muestra para entrenar tokenizers (una sola, compartida)
    sample, s_total = [], 0
    for a in arts:
        sample.append(a)
        s_total += len(a)
        if s_total >= sample_cap:
            break

    meta = {"experiment": "xh_data", "smoke": args.smoke, "articles_train": len(arts),
            "articles_val": len(val_arts), "train_text_bytes": int(train_text_bytes),
            "val_text_bytes": int(len(val_text.encode('utf-8'))), "vocabs": {}}
    for v in vocabs:
        tag = f"{v // 1024}k" if v >= 1024 else str(v)
        t1 = time.time()
        tok = train_bpe(sample, v)
        eos_id = tok.token_to_id(EOS)
        t_train = time.time() - t1
        # round-trip lossless (ByteLevel BPE debe reconstruir exacto)
        probe = arts[0][:2000]
        assert tok.decode(tok.encode(probe).ids) == probe, f"round-trip FALLO vocab={v}"
        t1 = time.time()
        ids_tr = encode_corpus(tok, arts, eos_id)
        ids_va = encode_corpus(tok, val_arts, eos_id)
        t_enc = time.time() - t1
        ids_tr.tofile(f"train_{tag}.bin")
        ids_va.tofile(f"val_{tag}.bin")
        tok.save(f"tokenizer_{tag}.json")
        fert = train_text_bytes / max(1, len(ids_tr))
        meta["vocabs"][tag] = {
            "vocab_size": tok.get_vocab_size(), "eos_id": int(eos_id),
            "train_tokens": int(len(ids_tr)), "val_tokens": int(len(ids_va)),
            "fertility_bytes_per_token": round(fert, 4),
            "train_bpe_s": round(t_train, 1), "encode_s": round(t_enc, 1)}
        print(f"[bpe-{tag}] vocab={tok.get_vocab_size()} train_tokens={len(ids_tr):,} "
              f"fertilidad={fert:.3f} bytes/token (train {t_train:.0f}s, encode {t_enc:.0f}s)", flush=True)
        with open(META_PATH, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

    meta["minutes_total"] = round((time.time() - t0) / 60, 1)
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"[xh-data] LISTO en {meta['minutes_total']} min", flush=True)


if __name__ == "__main__":
    main()
