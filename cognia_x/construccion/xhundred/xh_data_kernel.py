r"""
XH-DATA v2 — kernel CPU de Kaggle: corpus según 00_DISENO.md §4.5 (pre-registrado).
La preparación de datos es ONE-TIME (no cuenta en los 30 min de entreno).

Fuentes:
  - `ffuuugor/tinystories_spanish` (campo text_es) — motor de coherencia. Assert 5 muestras;
    fallback pre-programado a wiki-solo si falla (00_DISENO §8-R5).
  - `wikimedia/wikipedia 20231101.es` con filtros: corte en Referencias/Enlaces externos/
    Véase también/Bibliografía; líneas con ratio alfabético <0.55 fuera; dedup exacto por hash
    de línea (>80 chars) — mata plantillas de municipios (causa raíz de la deriva del precedente).

Mezcla 50/50 por DOCUMENTOS barajados (no bloques). Separador: token `<|doc|>` id 0 (byte 0x00 en
el brazo byte). Tokenizers BPE byte-level PROPIOS 32k y 16k entrenados sobre 100MB de la MEZCLA.

Salidas:
  tokenizer_32k.json / tokenizer_16k.json
  train_mix_32k.bin / train_mix_16k.bin / train_wiki_32k.bin (brazo G) / train_bytes.bin (brazo D)
  val_wiki.txt / val_stories.txt / val_{wiki,stories}_{32k,16k}.bin
  xh_data_meta.json (fertilidad MEDIDA en los held-out reales — 00_DISENO §8-R11)

USO local:  venv312\Scripts\python.exe cognia_x/construccion/xhundred/xh_data_kernel.py --smoke
USO Kaggle: push via run_kaggle_xh.py data (kernel CPU, sin quota GPU)
"""
import argparse
import hashlib
import json
import random
import re
import time

import numpy as np

META_PATH = "xh_data_meta.json"
WIKI_TARGET = 265_000_000        # filtrado; brazo G usa 256MB wiki-solo
STORIES_TARGET = 132_000_000
MIX_EACH = 128_000_000           # 128MB de cada fuente -> mezcla 256MB (00_DISENO §4.5)
VAL_BYTES = 2_000_000            # por fuente
BYTES_BIN_CAP = 200_000_000
TOKENIZER_SAMPLE_BYTES = 100_000_000
VOCABS = (32768, 16384)
EOS = "<|doc|>"
SECTION_CUT = re.compile(r"^(Referencias|Enlaces externos|Véase también|Bibliografía)\s*$", re.M)


def filter_wiki_article(text, seen_hashes):
    """Filtros pre-registrados §4.5. Devuelve texto limpio o None."""
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


def get_wiki(smoke, target_bytes):
    if smoke:
        base = ["la historia de espana tiene siglos de reyes y batallas que cambiaron europa entera. ",
                "el rio baja de la cordillera y riega los campos de trigo antes de llegar al mar. ",
                "la ciencia estudia los fenomenos naturales mediante hipotesis y experimentos reales. "]
        rng = random.Random(1)
        arts, total = [], 0
        while total < target_bytes:
            a = "".join(rng.choices(base, k=rng.randint(6, 20)))
            arts.append(a)
            total += len(a)
        return arts
    from datasets import load_dataset
    ds = load_dataset("wikimedia/wikipedia", "20231101.es", split="train", streaming=True)
    arts, total, seen, t0 = [], 0, set(), time.time()
    dropped = 0
    for a in ds:
        t = a.get("text", "")
        if len(t) <= 500:
            continue
        ft = filter_wiki_article(t, seen)
        if ft is None:
            dropped += 1
            continue
        arts.append(ft)
        total += len(ft)
        if len(arts) % 20000 == 0:
            print(f"[wiki] {total / 1e6:.0f}MB / {len(arts)} arts ({dropped} filtrados, "
                  f"{time.time() - t0:.0f}s)", flush=True)
        if total >= target_bytes:
            break
    print(f"[wiki] {total / 1e6:.0f}MB, {len(arts)} articulos ({dropped} filtrados)", flush=True)
    return arts


def get_stories(smoke, target_bytes):
    """Devuelve lista de cuentos o None (fallback wiki-solo pre-programado)."""
    if smoke:
        base = ["habia una vez un nino que jugaba en el parque con su perro pequeno y feliz. ",
                "la pequena sofia encontro una flor azul y se la llevo a su mama con una sonrisa. ",
                "el gato subio al arbol y desde arriba miraba las nubes blancas del cielo. "]
        rng = random.Random(2)
        arts, total = [], 0
        while total < target_bytes:
            a = "".join(rng.choices(base, k=rng.randint(4, 12)))
            arts.append(a)
            total += len(a)
        return arts
    try:
        from datasets import load_dataset
        ds = load_dataset("ffuuugor/tinystories_spanish", split="train", streaming=True)
        arts, total, t0 = [], 0, time.time()
        for i, a in enumerate(ds):
            t = (a.get("text_es") or "").strip()
            if i < 5:
                assert t and any(w in t.lower() for w in (" el ", " la ", " un ", " una ", " y ")), \
                    f"muestra {i} vacia o no-espanol: {t[:80]!r}"
            if len(t) > 100:
                arts.append(t)
                total += len(t)
            if len(arts) % 50000 == 0 and arts:
                print(f"[stories] {total / 1e6:.0f}MB / {len(arts)} cuentos ({time.time() - t0:.0f}s)",
                      flush=True)
            if total >= target_bytes:
                break
        print(f"[stories] {total / 1e6:.0f}MB, {len(arts)} cuentos", flush=True)
        return arts
    except Exception as e:  # noqa: BLE001
        print(f"[stories] FALLO ({e!r}) -> fallback wiki-solo (00_DISENO §8-R5)", flush=True)
        return None


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


def encode_corpus(tok, articles, eos_id, tag, chunk=2000):
    parts = []
    t0 = time.time()
    for i in range(0, len(articles), chunk):
        encs = tok.encode_batch(articles[i:i + chunk])
        for e in encs:
            parts.append(np.asarray(e.ids + [eos_id], dtype=np.uint16))
        if (i // chunk) % 25 == 0 and i:
            print(f"[encode-{tag}] {i}/{len(articles)} ({time.time() - t0:.0f}s)", flush=True)
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.uint16)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    if args.smoke:
        wiki_target, stories_target, mix_each = 2_000_000, 1_500_000, 1_000_000
        vocabs, sample_cap, val_bytes, bytes_cap = (512, 384), 800_000, 60_000, 500_000
    else:
        wiki_target, stories_target, mix_each = WIKI_TARGET, STORIES_TARGET, MIX_EACH
        vocabs, sample_cap, val_bytes, bytes_cap = VOCABS, TOKENIZER_SAMPLE_BYTES, VAL_BYTES, BYTES_BIN_CAP

    wiki = get_wiki(args.smoke, wiki_target)
    stories = get_stories(args.smoke, stories_target)
    fallback_wiki_solo = stories is None
    rng = random.Random(0)
    rng.shuffle(wiki)
    if not fallback_wiki_solo:
        rng.shuffle(stories)

    def take_val(arts):
        val, tot = [], 0
        while arts and tot < val_bytes:
            a = arts.pop()
            val.append(a)
            tot += len(a)
        return val

    val_wiki = take_val(wiki)
    val_stories = take_val(stories) if not fallback_wiki_solo else take_val(wiki)
    val_wiki_txt = "\n\n".join(val_wiki)
    val_stories_txt = "\n\n".join(val_stories)
    open("val_wiki.txt", "w", encoding="utf-8").write(val_wiki_txt)
    open("val_stories.txt", "w", encoding="utf-8").write(val_stories_txt)

    def cap_docs(arts, cap):
        out, tot = [], 0
        for a in arts:
            out.append(a)
            tot += len(a)
            if tot >= cap:
                break
        return out, tot

    mix_wiki, mw = cap_docs(wiki, mix_each)
    mix_stories, ms = (cap_docs(stories, mix_each) if not fallback_wiki_solo
                       else cap_docs(wiki[len(mix_wiki):], mix_each))
    mix = mix_wiki + mix_stories
    rng.shuffle(mix)                          # barajar DOCUMENTOS antes de concatenar (§4.5)
    wiki_solo, ws = cap_docs(wiki, 2 * mix_each)
    print(f"[split] mix={len(mix)} docs ({(mw + ms) / 1e6:.0f}MB: wiki {mw / 1e6:.0f} + "
          f"stories {ms / 1e6:.0f}) wiki_solo={ws / 1e6:.0f}MB "
          f"val_wiki={len(val_wiki_txt) / 1e6:.2f}MB val_stories={len(val_stories_txt) / 1e6:.2f}MB "
          f"fallback={fallback_wiki_solo}", flush=True)

    # brazo D (byte-level): mezcla cruda uint8, separador 0x00
    buf, total = [], 0
    for a in mix:
        b = a.encode("utf-8", "ignore") + b"\x00"
        buf.append(b)
        total += len(b)
        if total >= bytes_cap:
            break
    np.frombuffer(b"".join(buf), dtype=np.uint8).tofile("train_bytes.bin")
    print(f"[bytes] train_bytes.bin={total / 1e6:.0f}MB", flush=True)

    sample, _ = cap_docs(mix, sample_cap)
    meta = {"experiment": "xh_data_v2", "smoke": args.smoke,
            "fallback_wiki_solo": fallback_wiki_solo,
            "mix_docs": len(mix), "mix_bytes": int(mw + ms),
            "wiki_solo_bytes": int(ws), "bytes_bin": int(total),
            "val_wiki_bytes": len(val_wiki_txt.encode("utf-8")),
            "val_stories_bytes": len(val_stories_txt.encode("utf-8")),
            "vocabs": {}}

    for v in vocabs:
        tag = f"{v // 1024}k" if v >= 1024 else str(v)
        t1 = time.time()
        tok = train_bpe(sample, v)
        eos_id = tok.token_to_id(EOS)
        t_train = time.time() - t1
        probe = mix[0][:2000]
        assert tok.decode(tok.encode(probe).ids) == probe, f"round-trip FALLO vocab={v}"
        assert eos_id == 0, f"EOS id={eos_id}, esperado 0"
        ids_mix = encode_corpus(tok, mix, eos_id, f"mix-{tag}")
        ids_vw = encode_corpus(tok, val_wiki, eos_id, f"valw-{tag}")
        ids_vs = encode_corpus(tok, val_stories, eos_id, f"vals-{tag}")
        ids_mix.tofile(f"train_mix_{tag}.bin")
        ids_vw.tofile(f"val_wiki_{tag}.bin")
        ids_vs.tofile(f"val_stories_{tag}.bin")
        # wiki-solo en TODOS los vocabs (K3 usa 35/65 con 16k tras el veredicto E de K2)
        ids_g = encode_corpus(tok, wiki_solo, eos_id, f"wikisolo-{tag}")
        ids_g.tofile(f"train_wiki_{tag}.bin")
        meta["vocabs"].setdefault(tag, {})
        meta[f"train_wiki_tokens_{tag}"] = int(len(ids_g))
        tok.save(f"tokenizer_{tag}.json")
        # fertilidad MEDIDA en el held-out real (§8-R11): la fórmula bpb del kernel GPU usa ESTO
        fert_vw = meta["val_wiki_bytes"] / max(1, len(ids_vw))
        fert_vs = meta["val_stories_bytes"] / max(1, len(ids_vs))
        meta["vocabs"][tag] = {
            "vocab_size": tok.get_vocab_size(), "eos_id": int(eos_id),
            "train_mix_tokens": int(len(ids_mix)),
            "val_wiki_tokens": int(len(ids_vw)), "val_stories_tokens": int(len(ids_vs)),
            "fertility_val_wiki": round(fert_vw, 4), "fertility_val_stories": round(fert_vs, 4),
            "train_bpe_s": round(t_train, 1)}
        print(f"[bpe-{tag}] vocab={tok.get_vocab_size()} mix_tokens={len(ids_mix):,} "
              f"fert_wiki={fert_vw:.3f} fert_stories={fert_vs:.3f} B/tok", flush=True)
        with open(META_PATH, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

    meta["minutes_total"] = round((time.time() - t0) / 60, 1)
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"[xh-data] LISTO en {meta['minutes_total']} min", flush=True)


if __name__ == "__main__":
    main()
