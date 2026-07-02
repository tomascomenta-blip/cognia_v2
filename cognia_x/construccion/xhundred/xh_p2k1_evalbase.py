r"""
XH-P2K1 — Fase 2: evaluación del BASE Qwen2.5-3B-Instruct (NF4) en T4, según 02_FASE2_PLAN.md.
Tres suites (una por eje), mismo harness que usará el adapter en P2-K2 (o el delta es inválido):

  MGSM-es (razonamiento):    250 items, generativo 0-shot instruido, greedy <=384 tok,
                             extracción DOBLE (estricta '####' / laxa último número).
                             3-shot CoT condicional (control formato-vs-razonamiento).
  XStoryCloze-es (coherencia): 1,511 items, 2-way por NLL media/token de la opción.
  Belebele spa_Latn (comprensión): 900 items, 4-way por NLL media/token.

Gates: GP2-1 (harness sano: Belebele>=40%, XSC>=55%, MGSM laxa>=15% — si falla NO entrenar encima)
y GP2-2 (tok/s medido en los primeros items -> recortes pre-decididos: cae 3-shot, Belebele 450,
XSC 755; NUNCA MGSM 0-shot). Salida: eval_p2_base.json (guardado incremental).
USO local:  venv312\Scripts\python.exe cognia_x/construccion/xhundred/xh_p2k1_evalbase.py --smoke
            (smoke = unit-tests de extracción/normalización/prompts, sin modelo)
"""
import argparse
import json
import re
import subprocess
import sys
import time

RESULTS_PATH = "eval_p2_base.json"
BUDGET_MIN = 75.0
MGSM_PROMPT = ("Resuelve el siguiente problema paso a paso y termina tu respuesta "
               "con la línea '#### <número>'.\n\n{q}")
FEWSHOT_IDX = (0, 1, 2)          # exemplars del train de MGSM, fijados ANTES de correr


# ───────────────────────── extracción / normalización (unit-testeable sin modelo) ──────────────────


def norm_number(s):
    """'1.234' / '1,234' / '12,5' -> entero si se puede (GSM8K es entero); None si no hay número."""
    if s is None:
        return None
    s = s.strip().rstrip(".")
    s = re.sub(r"[.,](?=\d{3}(\D|$))", "", s)      # separadores de miles
    s = s.replace(",", ".")
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    if not m:
        return None
    v = float(m.group())
    return int(v) if v == int(v) else v


def extract_strict(text):
    """Número tras el ÚLTIMO '####'."""
    hits = re.findall(r"####\s*([^\n]*)", text)
    return norm_number(hits[-1]) if hits else None


def extract_lax(text):
    """Último número de la última línea no vacía con dígitos."""
    for line in reversed([ln for ln in text.split("\n") if ln.strip()]):
        nums = re.findall(r"[-+]?\d[\d.,]*", line)
        if nums:
            return norm_number(nums[-1])
    return None


def _ensure_bitsandbytes():
    """Kaggle trae bnb viejo; transformers exige >=0.46.1 (fix 8b67ac3 del repo)."""
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "bitsandbytes"],
                           capture_output=True, text=True, timeout=600)
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        print(f"[bnb] pip -> rc={r.returncode} ({tail[-1] if tail else 'sin output'})", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[bnb] pip fallo: {e}", flush=True)
    try:
        import importlib.metadata
        import bitsandbytes  # noqa: F401
        ver = importlib.metadata.version("bitsandbytes")
        ok = tuple(int(x) for x in ver.split(".")[:3]) >= (0, 46, 1)
        print(f"[bnb] {ver} -> {'OK' if ok else 'insuficiente'}", flush=True)
        return ok
    except Exception as e:  # noqa: BLE001
        print(f"[bnb] import fallo: {e}", flush=True)
        return False


def find_model_dir():
    import glob
    import os
    cands = [os.path.dirname(p) for p in glob.glob("/kaggle/input/**/config.json", recursive=True)]
    pool = [c for c in cands if "3b-instruct" in c.lower()] or cands
    if not pool:
        raise FileNotFoundError("sin modelo bajo /kaggle/input — adjuntar qwen2.5/3b-instruct")
    pool.sort(key=len)
    print(f"[model] {pool[0]}", flush=True)
    return pool[0]


def save(out):
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)


# ───────────────────────── scoring ─────────────────────────


def build_nll_scorer(model, tokenizer, device):
    import torch
    import torch.nn.functional as F

    @torch.no_grad()
    def score_options(prompt, options, batch=8):
        """NLL media por token de cada opción como continuación del turno assistant."""
        pre = tokenizer.apply_chat_template([{"role": "user", "content": prompt}],
                                            tokenize=False, add_generation_prompt=True)
        pre_ids = tokenizer(pre, add_special_tokens=False)["input_ids"]
        nlls = []
        for i in range(0, len(options), batch):
            chunk = options[i:i + batch]
            seqs = [pre_ids + tokenizer(o, add_special_tokens=False)["input_ids"] for o in chunk]
            maxlen = max(len(s) for s in seqs)
            pad = tokenizer.pad_token_id or tokenizer.eos_token_id
            inp = torch.full((len(seqs), maxlen), pad, dtype=torch.long)
            att = torch.zeros((len(seqs), maxlen), dtype=torch.long)
            for j, s in enumerate(seqs):
                inp[j, :len(s)] = torch.tensor(s)
                att[j, :len(s)] = 1
            inp, att = inp.to(device), att.to(device)
            logits = model(input_ids=inp, attention_mask=att).logits.float()
            logp = F.log_softmax(logits, dim=-1)
            for j, s in enumerate(seqs):
                n_opt = len(s) - len(pre_ids)
                pos = torch.arange(len(pre_ids) - 1, len(s) - 1, device=device)
                tgt = inp[j, len(pre_ids):len(s)]
                lp = logp[j, pos, :].gather(1, tgt[:, None])
                nlls.append(-float(lp.mean()) if n_opt > 0 else float("inf"))
        return nlls

    return score_options


def run_mc_suite(name, items, score_options, out, t0, budget_min, log_every=100):
    """items: lista de (prompt, [opciones], idx_correcta). Guarda parcial cada log_every."""
    correct = n = 0
    t_suite = time.time()
    for k, (prompt, opts, ans) in enumerate(items):
        nlls = score_options(prompt, opts)
        correct += int(min(range(len(nlls)), key=lambda i: nlls[i]) == ans)
        n += 1
        if (k + 1) % log_every == 0:
            el = time.time() - t_suite
            proy = el / (k + 1) * len(items)
            print(f"[{name}] {k + 1}/{len(items)} acc={correct / n:.3f} "
                  f"({el:.0f}s, proy {proy / 60:.1f} min)", flush=True)
            out["suites"][name] = {"acc": round(correct / n, 4), "n": n, "partial": True}
            save(out)
            if (time.time() - t0) / 60 > budget_min:
                print(f"[{name}] BUDGET — corto con n={n}", flush=True)
                break
    se = (correct / n * (1 - correct / n) / n) ** 0.5 if n else 0.0
    out["suites"][name] = {"acc": round(correct / n, 4), "n": n, "se": round(se, 4),
                           "minutes": round((time.time() - t_suite) / 60, 1), "partial": False}
    print(f"[{name}] FINAL acc={correct / n:.4f} (n={n}, SE={se:.3f})", flush=True)
    save(out)


def run_mgsm(tag, items, fewshot, model, tokenizer, device, out, t0, budget_min,
             batch=16, max_new=384):
    import torch
    strict_ok = lax_ok = trunc = n = 0
    t_suite = time.time()
    tokenizer.padding_side = "left"
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        prompts = []
        for q, _a in chunk:
            msgs = []
            for fq, fa in fewshot:
                msgs += [{"role": "user", "content": MGSM_PROMPT.format(q=fq)},
                         {"role": "assistant", "content": fa}]
            msgs.append({"role": "user", "content": MGSM_PROMPT.format(q=q)})
            prompts.append(tokenizer.apply_chat_template(msgs, tokenize=False,
                                                         add_generation_prompt=True))
        enc = tokenizer(prompts, return_tensors="pt", padding=True,
                        add_special_tokens=False).to(device)
        with torch.no_grad():
            gen = model.generate(**enc, max_new_tokens=max_new, do_sample=False,
                                 pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id)
        for j, (_q, ans) in enumerate(chunk):
            txt = tokenizer.decode(gen[j, enc["input_ids"].shape[1]:], skip_special_tokens=True)
            trunc += int(len(tokenizer(txt, add_special_tokens=False)["input_ids"]) >= max_new - 2)
            strict_ok += int(extract_strict(txt) == ans)
            lax_ok += int(extract_lax(txt) == ans)
            n += 1
        el = time.time() - t_suite
        print(f"[{tag}] {n}/{len(items)} estricta={strict_ok / n:.3f} laxa={lax_ok / n:.3f} "
              f"trunc={trunc} ({el:.0f}s, proy {el / n * len(items) / 60:.1f} min)", flush=True)
        out["suites"][tag] = {"acc_strict": round(strict_ok / n, 4),
                              "acc_lax": round(lax_ok / n, 4), "n": n,
                              "truncated": trunc, "partial": True}
        save(out)
        if (time.time() - t0) / 60 > budget_min:
            print(f"[{tag}] BUDGET — corto con n={n}", flush=True)
            break
    se = (lax_ok / n * (1 - lax_ok / n) / n) ** 0.5 if n else 0.0
    out["suites"][tag] = {"acc_strict": round(strict_ok / n, 4), "acc_lax": round(lax_ok / n, 4),
                          "n": n, "se": round(se, 4), "truncated": trunc,
                          "minutes": round((time.time() - t_suite) / 60, 1), "partial": False}
    print(f"[{tag}] FINAL estricta={strict_ok / n:.4f} laxa={lax_ok / n:.4f} "
          f"trunc={trunc}/{n}", flush=True)
    save(out)


def _smoke():
    assert norm_number("1.234") == 1234
    assert norm_number("1,234") == 1234
    assert norm_number("12,5") == 12.5
    assert norm_number("  72 ") == 72
    assert norm_number("$3.000.000") == 3000000
    assert norm_number("no hay") is None
    assert extract_strict("bla\n#### 42") == 42
    assert extract_strict("x #### 8\ny #### 1.500") == 1500
    assert extract_strict("sin marca") is None
    assert extract_lax("La respuesta es 72.") == 72
    assert extract_lax("total: 3 y 5\nfinal 1.200 euros") == 1200
    assert extract_lax("nada") is None
    assert MGSM_PROMPT.format(q="X") .endswith("X")
    print("[smoke] extracción/normalización: 13/13 OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        _smoke()
        return
    t0 = time.time()
    out = {"experiment": "xh_p2k1_evalbase", "suites": {}, "gates": {}}

    use_bnb = _ensure_bitsandbytes()
    import torch
    from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig)
    from datasets import load_dataset
    device = "cuda"
    model_dir = find_model_dir()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                               bnb_4bit_compute_dtype=torch.float16,
                               bnb_4bit_use_double_quant=True) if use_bnb else None
    model = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=quant,
        torch_dtype=torch.float16, device_map={"": 0}, trust_remote_code=True)
    model.eval()
    out["model"] = {"dir": model_dir, "nf4": bool(use_bnb), "torch": torch.__version__}
    # smoke de generación (10 tok)
    enc = tokenizer(tokenizer.apply_chat_template([{"role": "user", "content": "Hola"}],
                                                  tokenize=False, add_generation_prompt=True),
                    return_tensors="pt").to(device)
    gen = model.generate(**enc, max_new_tokens=10, do_sample=False,
                         pad_token_id=tokenizer.pad_token_id)
    print(f"[smoke-gen] {tokenizer.decode(gen[0, enc['input_ids'].shape[1]:], skip_special_tokens=True)!r}",
          flush=True)
    out["wall_setup_min"] = round((time.time() - t0) / 60, 1)
    save(out)

    # ── datasets ──
    bele = load_dataset("facebook/belebele", "spa_Latn", split="test")
    xsc = load_dataset("juletxara/xstory_cloze", "es", split="eval")
    mgsm_test = load_dataset("juletxara/mgsm", "es", split="test")
    mgsm_train = load_dataset("juletxara/mgsm", "es", split="train")
    print(f"[data] belebele={len(bele)} xsc={len(xsc)} mgsm={len(mgsm_test)}", flush=True)

    bele_items = [(f"Pasaje: {r['flores_passage']}\n\nPregunta: {r['question']}\nRespuesta:",
                   [" " + r[f"mc_answer{k}"] for k in (1, 2, 3, 4)],
                   int(r["correct_answer_num"]) - 1) for r in bele]
    xsc_items = [((r["input_sentence_1"] + " " + r["input_sentence_2"] + " "
                   + r["input_sentence_3"] + " " + r["input_sentence_4"]
                   + "\n\n¿Cómo termina la historia?"),
                  [" " + r["sentence_quiz1"], " " + r["sentence_quiz2"]],
                  int(r["answer_right_ending"]) - 1) for r in xsc]
    mgsm_items = [(r["question"], norm_number(str(r["answer_number"]))) for r in mgsm_test]
    fewshot = [(mgsm_train[i]["question"],
                (mgsm_train[i]["answer"] or "") + f"\n#### {mgsm_train[i]['answer_number']}")
               for i in FEWSHOT_IDX]

    score_options = build_nll_scorer(model, tokenizer, device)

    # gate GP2-2: tok/s con 50 items de Belebele -> proyección + recortes pre-decididos
    t_probe = time.time()
    probe_correct = 0
    for prompt, opts, ans in bele_items[:50]:
        nlls = score_options(prompt, opts)
        probe_correct += int(min(range(len(nlls)), key=lambda i: nlls[i]) == ans)
    probe_min = (time.time() - t_probe) / 60
    proy_bele = probe_min / 50 * len(bele_items)
    proy_total = proy_bele + proy_bele / len(bele_items) * len(xsc_items) / 2 + 16
    cut_3shot = proy_total > 55
    cut_bele = proy_total > 90
    out["gates"]["GP2_2"] = {"probe_acc_50": probe_correct / 50,
                             "probe_min_50": round(probe_min, 2),
                             "proy_belebele_min": round(proy_bele, 1),
                             "cut_3shot": cut_3shot, "cut_belebele_450": cut_bele}
    print(f"[GP2-2] probe 50 Belebele: acc={probe_correct / 50:.2f} {probe_min:.1f} min "
          f"-> proy Belebele {proy_bele:.0f} min (3shot={'FUERA' if cut_3shot else 'ok'})", flush=True)
    save(out)

    run_mc_suite("belebele", bele_items[:450] if cut_bele else bele_items,
                 score_options, out, t0, BUDGET_MIN * 0.55)
    run_mc_suite("xstorycloze", xsc_items, score_options, out, t0, BUDGET_MIN * 0.7)
    run_mgsm("mgsm_0shot", mgsm_items, [], model, tokenizer, device, out, t0, BUDGET_MIN)
    if not cut_3shot and (time.time() - t0) / 60 < BUDGET_MIN * 0.8:
        run_mgsm("mgsm_3shot", mgsm_items, fewshot, model, tokenizer, device, out, t0, BUDGET_MIN)
    else:
        print("[mgsm_3shot] omitido (GP2-2 / budget)", flush=True)

    # gate GP2-1: harness sano
    s = out["suites"]
    gp21 = (s.get("belebele", {}).get("acc", 0) >= 0.40
            and s.get("xstorycloze", {}).get("acc", 0) >= 0.55
            and s.get("mgsm_0shot", {}).get("acc_lax", 0) >= 0.15)
    out["gates"]["GP2_1_harness_sano"] = bool(gp21)
    out["minutes_total"] = round((time.time() - t0) / 60, 1)
    save(out)
    print(f"[p2k1] GP2-1 {'PASS' if gp21 else 'FAIL — NO entrenar encima'} | "
          f"LISTO en {out['minutes_total']} min", flush=True)


if __name__ == "__main__":
    main()
