"""
exp016 — tarea VERIFICABLE de suma byte-level + oraculo chequeable (no circular) para H-LEARN-1.

Formato byte-level (vocab 256 nativo de HybridLM): prompt ASCII b"A+B=" (A,B enteros decimales sin ceros
a la izquierda), respuesta = digitos de A+B + terminador b"\n". Ejemplo completo: b"47+8=55\n".
Longitud max = len("99+99=198\n")=10 -> L=12 (peor caso + holgura). PAD=0 (target -100, ignorado).

El ORACULO es codigo Python puro (int(A)+int(B)), NUNCA el modelo juzgandose -> no circular. El MISMO
oraculo (a) mide la accuracy en el test held-out REAL y (b) filtra las auto-generaciones correctas.

Supervision (teacher forcing next-token): en la secuencia seq=prompt+answer(+pad), el target en la
posicion i es seq[i+1], y SOLO se supervisa cuando seq[i+1] es un byte de la RESPUESTA (los digitos de C
y el '\n'); el prompt y el PAD van con -100. Asi el modelo aprende a PRODUCIR la respuesta tras ver "A+B=".
"""
import re

import numpy as np
import torch

PAD = 0
NEWLINE = 10
L = 12                 # longitud fija de secuencia (cabe "99+99=198\n"=10 + holgura)
N_NEW = 4              # bytes a generar en decode (cubre "198\n" = 3 digitos + terminador)

_PROMPT_RE = re.compile(rb"^(\d{1,2})\+(\d{1,2})=$")


def make_prompt(a, b):
    """bytes del prompt 'A+B=' (A,B sin ceros a la izquierda)."""
    return "{}+{}=".format(a, b).encode("ascii")


def correct_answer(a, b):
    """bytes de la respuesta CORRECTA 'C\\n' (C=A+B)."""
    return "{}\n".format(a + b).encode("ascii")


def sample_pairs(rng, n, lo, hi):
    """n pares (A,B) con A,B in [lo,hi] (inclusive), muestreados con el rng dado."""
    a = rng.integers(lo, hi + 1, size=n)
    b = rng.integers(lo, hi + 1, size=n)
    return [(int(x), int(y)) for x, y in zip(a, b)]


def oracle_correct(prompt_bytes, gen_bytes):
    """True si los bytes generados decodifican a un entero == A+B del prompt. Parseo DEFENSIVO:
    formato malo / no-digito / sin '\\n' cuentan como INCORRECTO (no lanza). NO usa el modelo."""
    try:
        m = _PROMPT_RE.match(bytes(prompt_bytes))
        if not m:
            return False
        a, b = int(m.group(1)), int(m.group(2))
        truth = a + b
        g = bytes(gen_bytes)
        nl = g.find(NEWLINE)            # cortar en el PRIMER '\n'
        if nl < 0:
            return False                # sin terminador en los n_new bytes -> incorrecto
        resp = g[:nl]
        if len(resp) == 0 or not resp.isdigit():
            return False
        return int(resp) == truth
    except Exception:
        return False


def emitted_answer(gen_bytes):
    """Normaliza la respuesta EMITIDA por el modelo a bytes 'digits\\n' (lo que se entrenara en naive).
    Toma hasta el primer '\\n' (incluido); si no hay '\\n', toma los n_new bytes y añade '\\n'."""
    g = bytes(gen_bytes)
    nl = g.find(NEWLINE)
    if nl < 0:
        return g + bytes([NEWLINE])
    return g[:nl + 1]


def example_to_seq_target(prompt_bytes, answer_bytes):
    """(seq, target) de longitud L. seq = prompt+answer padeado; target[i]=seq[i+1] supervisado SOLO en
    la region de respuesta (digitos de C + '\\n'); prompt y PAD -> -100. Trunca si excede L."""
    p = list(bytes(prompt_bytes))
    a = list(bytes(answer_bytes))
    full = (p + a)[:L]
    seq = full + [PAD] * (L - len(full))
    target = [-100] * L
    ans_start = len(p)                 # primer indice de la respuesta dentro de seq
    ans_end = min(len(p) + len(a), L)  # fin (exclusivo) de la respuesta dentro de seq
    for i in range(L - 1):
        nxt = i + 1
        if ans_start <= nxt < ans_end:  # se predice un byte de la RESPUESTA -> supervisar
            target[i] = seq[nxt]
    return seq, target


def batch_from_examples(examples, device):
    """examples = list[(prompt_bytes, answer_bytes)] -> (x,y) tensores (B,L) con y enmascarado."""
    seqs, tgts = [], []
    for p, a in examples:
        s, t = example_to_seq_target(p, a)
        seqs.append(s)
        tgts.append(t)
    x = torch.tensor(seqs, dtype=torch.long, device=device)
    y = torch.tensor(tgts, dtype=torch.long, device=device)
    return x, y


def make_seed_batch(rng, batch, lo, hi, device):
    """Batch de ejemplos CORRECTOS (prompt + respuesta correcta) para entrenar el base supervisado."""
    pairs = sample_pairs(rng, batch, lo, hi)
    examples = [(make_prompt(a, b), correct_answer(a, b)) for a, b in pairs]
    return batch_from_examples(examples, device)


def build_split(lo, hi, test_frac, split_seed=12345):
    """Partición DISJUNTA del espacio de problemas {(a,b): lo<=a,b<=hi} en (train_pairs, test_pairs),
    determinista por split_seed (FIJO, independiente del seed del modelo -> la tarea es la misma en
    todos los seeds). Anti-leakage: seed+pool se muestrean SOLO de train; el test es held-out puro ->
    mide GENERALIZACIÓN (problemas nunca vistos en entrenamiento), no memorización."""
    rng = np.random.default_rng(split_seed)
    allp = [(a, b) for a in range(lo, hi + 1) for b in range(lo, hi + 1)]
    rng.shuffle(allp)
    n_test = int(round(len(allp) * test_frac))
    test = [(int(a), int(b)) for a, b in allp[:n_test]]
    train = [(int(a), int(b)) for a, b in allp[n_test:]]
    return train, test


def test_from_pairs(test_pairs):
    """Convierte test_pairs (disjuntos) en el test held-out [(prompt_bytes, A, B), ...]."""
    return [(make_prompt(a, b), a, b) for a, b in test_pairs]


@torch.no_grad()
def eval_accuracy(model, test, device, batches_of=128):
    """Accuracy oraculo en el test held-out (decode DETERMINISTA: generate n_new=4, top_k=1=argmax).
    Devuelve (acc, correct_count, total). Batchea la generacion para velocidad."""
    model.eval()
    hits = 0
    total = len(test)
    for j in range(0, total, batches_of):
        chunk = test[j:j + batches_of]
        # prompts de distinta longitud -> generar uno a uno por simplicidad/correctitud (L chico, barato).
        for prompt_bytes, a, b in chunk:
            idx = torch.tensor([list(bytes(prompt_bytes))], dtype=torch.long, device=device)
            gen = model.generate(idx, n_new=N_NEW, temperature=1.0, top_k=1)  # argmax determinista
            gen_new = bytes(gen[0].tolist()[len(prompt_bytes):])              # solo los bytes nuevos
            if oracle_correct(prompt_bytes, gen_new):
                hits += 1
    model.train()
    return hits / max(1, total), hits, total
