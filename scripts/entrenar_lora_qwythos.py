# -*- coding: utf-8 -*-
"""
entrenar_lora_qwythos.py — QLoRA 4bit del cerebro Qwythos-9B sobre trazas
chatml verificadas de Cognia (plan LoRA Qwythos 2026-08-09, diseno (c)).

POR QUE QLoRA y no LoRA pelado: la base bf16 pesa 19,3 GB > 16.311 MiB de
VRAM — cargar en bf16 ya no cabe. nf4 + double quant + gradient checkpointing
es la unica via local (decidido, no opcional). La estimacion de memoria es
HIPOTESIS hasta el smoke F-2 (la formula de KV ya erro 6x en este repo).

POR QUE atencion-solo (q/k/v/o): el conversor convert_lora_to_gguf b10066
revienta con tensores de expertos/MLP raros (F2 del prereg de LoRAs) y la
ruta solo-atencion esta PROBADA (192/192 tensores sobre gpt-oss). Nada de
gate/up/down ni embeddings.

POR QUE apply_chat_template del repo base y no ChatML a mano: Qwythos es
familia Qwen3.5 con su chat_template.jinja propio — la MISMA plantilla que
llama-server aplica con --jinja. Renderizar otra cosa entrenaria contra un
instrumento distinto del de inferencia (asimetria medida en F1 de LoRAs).

Masking por spans: por cada turno assistant k, len_pre = render de
messages[:k] con add_generation_prompt=True; len_post = render de
messages[:k+1]; labels = -100 fuera de [len_pre, len_post). Solo se entrena
lo que el assistant emitio (tool_calls con JSON crudo + prosa final). Un
ejemplo cuyos renders de prefijo NO son prefijo del render completo (la
plantilla reescribe turnos viejos, p.ej. poda de <think>) se DESCARTA y se
reporta — jamas se enmascara a ciegas.

Corre en venv312gpu (torch cu128 + bitsandbytes + peft). Receta E-GROK:
1 epoch, lr 3e-4, warmup 10% + cosine, AdamW, batch 1 x grad-accum 16,
seed 20260809. Ejemplos mas largos que --seq-len se DESCARTAN (no truncar
a mitad de tool_call) y se reporta cuantos.

Uso:
  venv312gpu\\Scripts\\python.exe scripts\\entrenar_lora_qwythos.py
      --dataset %USERPROFILE%\\.cognia\\data\\datasets\\qwythos_tools_v1.jsonl
      [--base %USERPROFILE%\\.cognia\\models\\qwythos-9b-base]
      [--out %USERPROFILE%\\.cognia\\loras\\qwythos-tools-v1]
      [--seq-len 8192] [--smoke]

--smoke = gate F-2 del prereg: carga 4bit + 5 pasos forward/backward con el
ejemplo p95 midiendo torch.cuda.max_memory_allocated; PASS < 15,0 GB.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

SEED = 20260809
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj"]   # requisito duro (F2)
BASE_DEFAULT = Path.home() / ".cognia" / "models" / "qwythos-9b-base"
OUT_DEFAULT = Path.home() / ".cognia" / "loras" / "qwythos-tools-v1"
SMOKE_LIMITE_GIB = 15.0        # PASS de F-2, congelado en el prereg
SMOKE_PASOS = 5
WARMUP_FRAC = 0.10
VRAM_AJENA_MIB = 2000          # mas que esto usado al arrancar = flota viva


# ---------------------------------------------------------------------------
# Puras / testeables en CPU (sin torch)
# ---------------------------------------------------------------------------

def cargar_dataset(ruta: str | Path) -> tuple[list[dict], int]:
    """Lee el JSONL {messages, tools, meta} de trazas_a_dataset.py.
    Devuelve (ejemplos, lineas_rotas). Una linea rota NO tumba la corrida
    pero se cuenta y se reporta (degradacion visible)."""
    ejemplos, rotas = [], 0
    with open(ruta, "r", encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                ej = json.loads(linea)
                if not isinstance(ej.get("messages"), list) or not ej["messages"]:
                    raise ValueError("sin messages")
                ejemplos.append(ej)
            except Exception:
                rotas += 1
    return ejemplos, rotas


def verificar_chat_template(tokenizer, base_dir: str | Path) -> tuple[bool, str]:
    """El masking depende de la plantilla del repo base: sin chat_template
    NO se entrena (abortar visible). Si el tokenizer no la trae cargada pero
    chat_template.jinja esta en el dir, se inyecta desde el archivo."""
    if getattr(tokenizer, "chat_template", None):
        return True, "chat_template presente en el tokenizer"
    jinja = Path(base_dir) / "chat_template.jinja"
    if jinja.is_file() and jinja.stat().st_size > 0:
        tokenizer.chat_template = jinja.read_text(encoding="utf-8")
        return True, "chat_template inyectada desde chat_template.jinja"
    return False, ("el tokenizer de %s no tiene chat_template ni existe "
                   "chat_template.jinja — correr scripts/descargar_qwythos_hf.py"
                   % base_dir)


def _normalizar_tool_calls(messages: list) -> list:
    """Adapta los tool_calls del formato OpenAI anidado ({type, function:
    {name, arguments:str-json}}) al que espera el chat_template de Qwen3.5:
    APLANADO ({name, arguments:dict}). El template hace `tool_call.name` y
    `tool_call.arguments|items`, asi que arguments TIENE que ser un mapping.

    POR QUE en el trainer y no en el dataset: el dataset conserva el formato
    OpenAI canonico (lo que emite el server y consume run_tool); la
    plantilla del modelo es un detalle del RENDER, no del dato. Devuelve
    copias — no muta los messages del dataset."""
    import json as _json
    out = []
    for m in messages:
        tcs = m.get("tool_calls")
        if not tcs:
            out.append(m)
            continue
        nuevos = []
        for tc in tcs:
            fn = tc.get("function", tc)
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = _json.loads(args)
                except (ValueError, TypeError):
                    args = {"_raw": args}
            nuevos.append({"name": fn.get("name", ""), "arguments": args})
        nm = dict(m)
        nm["tool_calls"] = nuevos
        out.append(nm)
    return out


def codificar_ejemplo(tokenizer, messages: list, tools: list,
                      seq_len: int) -> tuple[tuple[list, list] | None, str]:
    """(input_ids, labels) con masking por spans, o (None, motivo_descarte).

    Motivos: 'largo' (render completo > seq_len; no se trunca jamas a mitad
    de tool_call), 'plantilla_inconsistente' (el render de un prefijo no es
    prefijo token a token del render completo: enmascarar seria adivinar),
    'sin_labels' (ningun token entrenable tras el shift causal)."""
    messages = _normalizar_tool_calls(messages)

    def _render(msgs, gen):
        # tokenize=False + tok() y NO apply_chat_template(tokenize=True): en
        # transformers 5.14 esta ultima devuelve un BatchEncoding (no una
        # lista de ints), y list() sobre el da 2 (sus claves) en vez de los
        # tokens — el masking por spans quedaba vacio ('sin_labels' en todo).
        # El render de texto es fiel (add_special_tokens=False: los
        # <|im_start|> ya vienen en la plantilla).
        texto = tokenizer.apply_chat_template(
            msgs, tools=tools or None, tokenize=False,
            add_generation_prompt=gen)
        return tokenizer(texto, add_special_tokens=False)["input_ids"]

    ids = _render(messages, False)
    if len(ids) > seq_len:
        return None, "largo"
    labels = [-100] * len(ids)
    for k, m in enumerate(messages):
        if m.get("role") != "assistant":
            continue
        pre = _render(messages[:k], True)
        post = _render(messages[:k + 1], False)
        if ids[:len(pre)] != pre or ids[:len(post)] != post:
            return None, "plantilla_inconsistente"
        for i in range(len(pre), len(post)):
            labels[i] = ids[i]
    if all(l == -100 for l in labels[1:]):
        return None, "sin_labels"
    return (ids, labels), ""


def codificar_dataset(tokenizer, ejemplos: list[dict],
                      seq_len: int) -> tuple[list[tuple[list, list]], dict]:
    """Codifica todo el dataset. Devuelve (codificados, descartes_por_causa).
    El conteo de descartes SIEMPRE se reporta (regla del diseno)."""
    codificados, descartes = [], {"largo": 0, "plantilla_inconsistente": 0,
                                  "sin_labels": 0}
    for ej in ejemplos:
        par, motivo = codificar_ejemplo(
            tokenizer, ej["messages"], ej.get("tools") or [], seq_len)
        if par is None:
            descartes[motivo] = descartes.get(motivo, 0) + 1
        else:
            codificados.append(par)
    return codificados, descartes


def factor_lr(paso: int, total: int, frac_warmup: float = WARMUP_FRAC) -> float:
    """Multiplicador de lr: warmup lineal el primer frac_warmup de los pasos
    y coseno hasta ~0 al final (receta E-GROK, LambdaLR)."""
    total = max(1, total)
    warmup = max(1, int(round(total * frac_warmup)))
    if paso < warmup:
        return (paso + 1) / warmup
    resto = max(1, total - warmup)
    return 0.5 * (1.0 + math.cos(math.pi * (paso - warmup) / resto))


def indice_p95(largos: list[int]) -> int:
    """Indice del ejemplo con largo p95 (el que estresa memoria en F-2 sin
    ser el outlier maximo). Lista no vacia."""
    orden = sorted(range(len(largos)), key=lambda i: largos[i])
    return orden[min(len(orden) - 1, int(math.floor(0.95 * (len(orden) - 1))))]


def vram_usada_mib() -> int:
    """MiB usados segun nvidia-smi; -1 si no se pudo medir. Se usa para el
    chequeo QUE CORRE de 'flota apagada' antes de entrenar."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20)
        return int(r.stdout.strip().splitlines()[0])
    except Exception:
        return -1


# ---------------------------------------------------------------------------
# GPU (solo dentro de main; imports perezosos de torch/peft/transformers)
# ---------------------------------------------------------------------------

def _cargar_modelo_4bit(base_dir: Path):
    """Base en nf4 double-quant compute bf16 + checkpointing + kbit prep +
    LoRA r16/alpha32 SOLO q/k/v/o. Devuelve el modelo peft listo."""
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoConfig, BitsAndBytesConfig

    bnb = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True)

    # La base de Qwythos es Qwen3.5 MULTIMODAL (Qwen3_5ForConditionalGeneration,
    # con text_config + vision_config): AutoModelForCausalLM no la instancia.
    # Se carga por la clase real (AutoModelForImageTextToText) y el LoRA de
    # tool-calling ataca SOLO la torre de lenguaje (target_modules q/k/v/o del
    # language_model; la vision se congela — no la estamos adaptando). Fallback
    # a CausalLM para bases no-multimodales de la misma familia (contingencia
    # del prereg: entrenar sobre un 7B/3B de texto puro).
    cfg = AutoConfig.from_pretrained(str(base_dir))
    es_multimodal = hasattr(cfg, "vision_config") or "ConditionalGeneration" in \
        (cfg.architectures[0] if cfg.architectures else "")
    if es_multimodal:
        from transformers import AutoModelForImageTextToText
        modelo = AutoModelForImageTextToText.from_pretrained(
            str(base_dir), quantization_config=bnb, device_map={"": 0})
    else:
        from transformers import AutoModelForCausalLM
        modelo = AutoModelForCausalLM.from_pretrained(
            str(base_dir), quantization_config=bnb, device_map={"": 0})
    modelo = prepare_model_for_kbit_training(modelo)
    modelo.gradient_checkpointing_enable()
    modelo.config.use_cache = False   # incompatible con checkpointing

    # target_modules por SUFIJO de nombre: peft matchea q_proj/k_proj/... donde
    # esten (en multimodal viven bajo model.language_model.*.self_attn); la
    # torre visual no tiene esos nombres, asi que queda intacta sin listarla.
    lora = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, bias="none",
                      task_type="CAUSAL_LM", target_modules=TARGETS)
    modelo = get_peft_model(modelo, lora)
    modelo.print_trainable_parameters()
    return modelo


def _paso_perdida(modelo, ids: list, labels: list) -> "object":
    """Un forward con labels (la CE causal con ignore_index=-100 la hace
    transformers). Batch 1, sin padding."""
    import torch
    t_ids = torch.tensor([ids], dtype=torch.long, device=modelo.device)
    t_lab = torch.tensor([labels], dtype=torch.long, device=modelo.device)
    return modelo(input_ids=t_ids, labels=t_lab).loss


def _smoke(modelo, codificados, args) -> int:
    """Gate F-2: 5 pasos forward/backward+step con el ejemplo p95 midiendo
    max_memory_allocated. PASS < 15,0 GiB. Escribe el JSON en b4_loras/."""
    import torch
    largos = [len(ids) for ids, _ in codificados]
    idx = indice_p95(largos)
    ids, labels = codificados[idx]
    print("smoke F-2: ejemplo p95 = %d tokens (de %d ejemplos)"
          % (len(ids), len(codificados)))
    params = [p for p in modelo.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=args.lr)
    torch.cuda.reset_peak_memory_stats()
    perdidas = []
    for paso in range(SMOKE_PASOS):
        perdida = _paso_perdida(modelo, ids, labels)
        perdida.backward()
        opt.step(); opt.zero_grad()
        perdidas.append(float(perdida.item()))
        print("  paso %d/%d perdida %.4f" % (paso + 1, SMOKE_PASOS, perdidas[-1]))
    pico_gib = torch.cuda.max_memory_allocated() / 1024 ** 3
    veredicto = "PASS" if pico_gib < SMOKE_LIMITE_GIB else "FALLA"
    print("smoke F-2: max_memory_allocated = %.2f GiB (limite %.1f) -> %s"
          % (pico_gib, SMOKE_LIMITE_GIB, veredicto))
    salida = Path(__file__).resolve().parent.parent / "b4_loras"
    salida.mkdir(exist_ok=True)
    (salida / "f2_smoke_qwythos_tools_v1.json").write_text(json.dumps({
        "prereg": "PREREG_LORA_QWYTHOS_20260809.md F-2",
        "veredicto": veredicto, "pico_gib": round(pico_gib, 3),
        "limite_gib": SMOKE_LIMITE_GIB, "tokens_p95": len(ids),
        "pasos": SMOKE_PASOS, "perdidas": perdidas, "seq_len": args.seq_len,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S")},
        indent=1, ensure_ascii=False), encoding="utf-8")
    print("-> %s" % (salida / "f2_smoke_qwythos_tools_v1.json"))
    return 0 if veredicto == "PASS" else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="QLoRA 4bit de Qwythos-9B sobre trazas verificadas")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--base", default=str(BASE_DEFAULT))
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--seq-len", type=int, default=8192)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--grad-accum", type=int, default=16)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--max-ejemplos", type=int, default=0,
                    help="tope para depurar (0 = todos)")
    ap.add_argument("--smoke", action="store_true",
                    help="gate F-2: 5 pasos con el ejemplo p95 y VRAM pico")
    ap.add_argument("--forzar", action="store_true",
                    help="saltar el chequeo de VRAM ajena (flota encendida)")
    args = ap.parse_args()
    base_dir, out_dir = Path(args.base), Path(args.out)

    # Chequeo QUE CORRE (no leccion en prosa): entrenar con la flota viva no
    # cabe en 16 GB; abortar visible antes de tocar nada.
    usada = vram_usada_mib()
    if usada > VRAM_AJENA_MIB and not args.forzar:
        print("FALLA: %d MiB de VRAM ya en uso (flota/oficina encendida?). "
              "Apagar con 'cognia flota parar' o pasar --forzar." % usada)
        return 2
    if usada < 0:
        print("AVISO: nvidia-smi no respondio; sin chequeo de VRAM ajena")

    from transformers import AutoTokenizer   # perezoso: dep pesada
    tokenizer = AutoTokenizer.from_pretrained(str(base_dir))
    ok, motivo = verificar_chat_template(tokenizer, base_dir)
    print("chat_template: %s" % motivo)
    if not ok:
        return 2

    ejemplos, rotas = cargar_dataset(args.dataset)
    if args.max_ejemplos:
        ejemplos = ejemplos[:args.max_ejemplos]
    print("dataset: %d ejemplos (%d lineas rotas)" % (len(ejemplos), rotas))
    codificados, descartes = codificar_dataset(tokenizer, ejemplos, args.seq_len)
    print("codificados: %d | descartes: %s" % (len(codificados), descartes))
    if not codificados:
        print("FALLA: ningun ejemplo codificable — nada que entrenar")
        return 2

    import torch   # perezoso: solo aca se exige GPU
    if not torch.cuda.is_available():
        print("FALLA: CUDA no disponible — este script corre en venv312gpu "
              "con la GPU libre (F-2/entrenamiento son [GPU-EXCL])")
        return 2
    torch.manual_seed(args.seed)

    modelo = _cargar_modelo_4bit(base_dir)
    if args.smoke:
        return _smoke(modelo, codificados, args)

    # ----- corrida completa: 1 epoch, batch 1 x accum 16 -------------------
    accum = max(1, args.grad_accum)
    pasos_totales = max(1, math.ceil(len(codificados) / accum))
    params = [p for p in modelo.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=args.lr)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: factor_lr(s, pasos_totales))
    g = torch.Generator().manual_seed(args.seed)
    orden = torch.randperm(len(codificados), generator=g).tolist()

    torch.cuda.reset_peak_memory_stats()
    perdidas, t0 = [], time.time()
    modelo.train()
    micro = 0
    for idx in orden:
        ids, labels = codificados[idx]
        perdida = _paso_perdida(modelo, ids, labels) / accum
        perdida.backward()
        perdidas.append(float(perdida.item()) * accum)
        micro += 1
        if micro % accum == 0 or micro == len(orden):
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step(); sched.step(); opt.zero_grad()
            paso = (micro + accum - 1) // accum
            print("  paso %d/%d perdida %.4f lr %.2e (%.0fs)"
                  % (paso, pasos_totales, perdidas[-1],
                     sched.get_last_lr()[0], time.time() - t0), flush=True)

    # inicial/final = media de los primeros/ultimos 10 micro-pasos: mas
    # barato que re-evaluar el dataset entero con un 9B y suficiente para el
    # log de tendencia (documentado: NO es la loss de eval del dataset).
    n = min(10, len(perdidas))
    pico_gib = torch.cuda.max_memory_allocated() / 1024 ** 3
    out_dir.mkdir(parents=True, exist_ok=True)
    modelo.save_pretrained(str(out_dir))   # adapter_model.safetensors + config
    registro = {
        "base": str(base_dir), "dataset": args.dataset,
        "ejemplos": len(codificados), "descartes": descartes,
        "lineas_rotas": rotas, "seq_len": args.seq_len, "lr": args.lr,
        "grad_accum": accum, "seed": args.seed, "epochs": 1,
        "targets": TARGETS, "r": 16, "alpha": 32,
        "perdida_inicial_media10": round(sum(perdidas[:n]) / n, 4),
        "perdida_final_media10": round(sum(perdidas[-n:]) / n, 4),
        "perdidas": perdidas, "vram_pico_gib": round(pico_gib, 3),
        "segundos": round(time.time() - t0, 1),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (out_dir / "entrenamiento.json").write_text(
        json.dumps(registro, indent=1, ensure_ascii=False), encoding="utf-8")
    print("adapter + entrenamiento.json -> %s" % out_dir)
    print("perdida %.4f -> %.4f | VRAM pico %.2f GiB"
          % (registro["perdida_inicial_media10"],
             registro["perdida_final_media10"], pico_gib))
    return 0


if __name__ == "__main__":
    sys.exit(main())
