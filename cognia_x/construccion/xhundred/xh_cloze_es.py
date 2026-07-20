r"""
XH-CLOZE-ES — batería mini-cloze de español (40 ítems, 3 opciones, azar=33.3%) para la definición
pre-registrada de "estado funcional" del 100M. Scoring: NLL media por token de cada continuación
dada la prompt; gana la de menor NLL. Categorías: concordancia (12), conocimiento (12),
semántica (10), sintaxis/preposiciones (6).

Como __main__: mide el BASELINE del modelo precedente 37.7M byte-level (xfinal_model.pt) para
anclar el gate con un número real, no inventado.
USO: venv312\Scripts\python.exe cognia_x/construccion/xhundred/xh_cloze_es.py
"""
import math

CLOZE_ES = [
    # ── concordancia (género/número/persona) ──
    {"cat": "concordancia", "prompt": "Las casas del pueblo son", "opts": [" blancas", " blanca", " blanco"], "ans": 0},
    {"cat": "concordancia", "prompt": "El niño está muy", "opts": [" cansado", " cansada", " cansadas"], "ans": 0},
    {"cat": "concordancia", "prompt": "Los libros están sobre la", "opts": [" mesa", " mesas", " meso"], "ans": 0},
    {"cat": "concordancia", "prompt": "María es una mujer muy", "opts": [" inteligente", " inteligentes", " inteligento"], "ans": 0},
    {"cat": "concordancia", "prompt": "Nosotros", "opts": [" somos amigos", " sois amigos", " soy amigos"], "ans": 0},
    {"cat": "concordancia", "prompt": "Ellos", "opts": [" tienen dinero", " tiene dinero", " tengo dinero"], "ans": 0},
    {"cat": "concordancia", "prompt": "Yo", "opts": [" tengo hambre", " tienes hambre", " tiene hambre"], "ans": 0},
    {"cat": "concordancia", "prompt": "El agua del lago está muy", "opts": [" fría", " frío", " fríos"], "ans": 0},
    {"cat": "concordancia", "prompt": "Es un problema muy", "opts": [" difícil", " difícila", " difíciles"], "ans": 0},
    {"cat": "concordancia", "prompt": "Las flores del jardín son", "opts": [" hermosas", " hermosos", " hermosa"], "ans": 0},
    {"cat": "concordancia", "prompt": "Mi hermano y yo", "opts": [" vamos al parque", " van al parque", " va al parque"], "ans": 0},
    {"cat": "concordancia", "prompt": "Ayer por la tarde", "opts": [" fuimos al cine", " iremos al cine", " vamos a ir al cine"], "ans": 0},
    # ── conocimiento del mundo ──
    {"cat": "conocimiento", "prompt": "La capital de Francia es", "opts": [" París", " Madrid", " Roma"], "ans": 0},
    {"cat": "conocimiento", "prompt": "La capital de España es", "opts": [" Madrid", " Barcelona", " Lisboa"], "ans": 0},
    {"cat": "conocimiento", "prompt": "El sol sale por el", "opts": [" este", " oeste", " norte"], "ans": 0},
    {"cat": "conocimiento", "prompt": "El agua hierve a cien", "opts": [" grados", " metros", " litros"], "ans": 0},
    {"cat": "conocimiento", "prompt": "La Tierra gira alrededor del", "opts": [" Sol", " mar", " viento"], "ans": 0},
    {"cat": "conocimiento", "prompt": "El océano más grande del mundo es el", "opts": [" Pacífico", " Atlántico", " Índico"], "ans": 0},
    {"cat": "conocimiento", "prompt": "Cervantes escribió Don", "opts": [" Quijote", " Juan", " Pedro"], "ans": 0},
    {"cat": "conocimiento", "prompt": "La Segunda Guerra Mundial terminó en", "opts": [" 1945", " 1918", " 1989"], "ans": 0},
    {"cat": "conocimiento", "prompt": "El río más largo de Sudamérica es el", "opts": [" Amazonas", " Nilo", " Danubio"], "ans": 0},
    {"cat": "conocimiento", "prompt": "La moneda de Estados Unidos es el", "opts": [" dólar", " euro", " peso"], "ans": 0},
    {"cat": "conocimiento", "prompt": "Los seres humanos respiran", "opts": [" oxígeno", " helio", " carbono"], "ans": 0},
    {"cat": "conocimiento", "prompt": "La fotosíntesis la realizan las", "opts": [" plantas", " piedras", " nubes"], "ans": 0},
    # ── coherencia semántica ──
    {"cat": "semantica", "prompt": "El hielo es muy", "opts": [" frío", " caliente", " ruidoso"], "ans": 0},
    {"cat": "semantica", "prompt": "Por la noche se puede ver la", "opts": [" luna", " playa", " lluvia"], "ans": 0},
    {"cat": "semantica", "prompt": "El fuego produce calor y", "opts": [" luz", " hielo", " silencio"], "ans": 0},
    {"cat": "semantica", "prompt": "Los pájaros vuelan por el", "opts": [" cielo", " mar", " subsuelo"], "ans": 0},
    {"cat": "semantica", "prompt": "En invierno hace mucho", "opts": [" frío", " calor", " ruido"], "ans": 0},
    {"cat": "semantica", "prompt": "Los peces viven en el", "opts": [" agua", " aire", " fuego"], "ans": 0},
    {"cat": "semantica", "prompt": "Para escribir se usa un", "opts": [" lápiz", " zapato", " plato"], "ans": 0},
    {"cat": "semantica", "prompt": "El bebé llora porque tiene", "opts": [" hambre", " biblioteca", " montaña"], "ans": 0},
    {"cat": "semantica", "prompt": "La lluvia cae desde las", "opts": [" nubes", " raíces", " piedras"], "ans": 0},
    {"cat": "semantica", "prompt": "El médico trabaja en el", "opts": [" hospital", " bosque", " océano"], "ans": 0},
    # ── sintaxis / preposiciones ──
    {"cat": "sintaxis", "prompt": "Todos los días voy", "opts": [" a la escuela", " en la escuela", " de la escuela"], "ans": 0},
    {"cat": "sintaxis", "prompt": "El libro está encima", "opts": [" de la mesa", " a la mesa", " por la mesa"], "ans": 0},
    {"cat": "sintaxis", "prompt": "Yo soy", "opts": [" de Madrid", " a Madrid", " por Madrid"], "ans": 0},
    {"cat": "sintaxis", "prompt": "Estoy pensando", "opts": [" en ti", " de ti", " a ti"], "ans": 0},
    {"cat": "sintaxis", "prompt": "La decisión depende", "opts": [" de ti", " a ti", " en ti"], "ans": 0},
    {"cat": "sintaxis", "prompt": "Gracias", "opts": [" por tu ayuda", " de tu ayuda", " a tu ayuda"], "ans": 0},
]


def score_cloze(nll_fn):
    """nll_fn(prompt, continuation) -> NLL media por token de la continuación dada la prompt.
    Devuelve dict con accuracy total y por categoría (azar = 1/3)."""
    per_cat, correct = {}, 0
    for item in CLOZE_ES:
        nlls = [nll_fn(item["prompt"], o) for o in item["opts"]]
        ok = min(range(len(nlls)), key=lambda i: nlls[i]) == item["ans"]
        correct += ok
        c = per_cat.setdefault(item["cat"], [0, 0])
        c[0] += ok
        c[1] += 1
    out = {"total": round(correct / len(CLOZE_ES), 4), "n": len(CLOZE_ES)}
    for cat, (k, n) in per_cat.items():
        out[cat] = round(k / n, 4)
    return out


def _main():
    """Baseline: mide el precedente 37.7M byte-level (xfinal_model.pt) en esta batería."""
    import sys
    from pathlib import Path
    import numpy as np
    import torch
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from xfinal_kernel import FinalLM, ARCH_D, ARCH_HEADS, ARCH_LAYER_WINDOWS

    ckpt = Path(__file__).resolve().parent.parent / "results_xfinal" / "xfinal_model.pt"
    sd = torch.load(ckpt, map_location="cpu")
    model = FinalLM(256, ARCH_D, ARCH_HEADS, ARCH_LAYER_WINDOWS)
    model.load_state_dict({k: v.float() for k, v in sd.items()})
    model.eval()

    @torch.no_grad()
    def nll_fn(prompt, cont):
        p = np.frombuffer(prompt.encode("utf-8"), dtype=np.uint8).astype(np.int64)
        c = np.frombuffer(cont.encode("utf-8"), dtype=np.uint8).astype(np.int64)
        ids = torch.from_numpy(np.concatenate([p, c])).unsqueeze(0)
        logits, _ = model(ids[:, :-1])
        logp = torch.log_softmax(logits[0].float(), dim=-1)
        tgt = ids[0, 1:]
        span = logp[len(p) - 1:, :].gather(1, tgt[len(p) - 1:, None])
        return -float(span.mean())

    res = score_cloze(nll_fn)
    print(f"[cloze-es] BASELINE xfinal 37.7M byte-level: {res}")


if __name__ == "__main__":
    _main()
