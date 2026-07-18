"""
expert_forge/expert_maker_dataset.py
====================================
Dataset del META-MODELO creador de expertos: convierte una peticion libre
del usuario en la spec JSON de un experto (id, nombre, dedicacion,
model_key, backend).

Generacion determinista por plantillas (seed fija). El parafraseo con el
7B local es una mejora v1 declarada: v0 usa 100% plantillas para que el
dataset sea reproducible y el gate de calidad mida el fine-tune, no la
suerte del generador.
"""

from __future__ import annotations

import json
import random

# (dominio, dedicacion, model_key) — model_key coherente con la flota real:
# codigo -> coder-14b; conversacion/redaccion -> chat-7b; tareas simples -> coder-0.5b
_DOMINIOS = [
    ("abogado", "asesoria legal general y contratos", "chat-7b"),
    ("chef", "recetas, tecnica de cocina y menus", "chat-7b"),
    ("profesor de fisica", "explicar fisica con ejemplos claros", "chat-7b"),
    ("traductor", "traduccion espanol-ingles cuidando matices", "chat-7b"),
    ("analista de datos", "analisis de datos y scripts de pandas", "coder-14b"),
    ("poeta", "poemas y prosa lirica en espanol", "chat-7b"),
    ("dungeon master", "dirigir partidas de rol con narrativa viva", "chat-7b"),
    ("coach de habitos", "habitos, metas y seguimiento amable", "chat-7b"),
    ("programador web", "frontend y backend con codigo limpio", "coder-14b"),
    ("experto en excel", "formulas y automatizacion de hojas", "coder-0.5b"),
    ("medico orientador", "orientacion de salud general no diagnostica", "chat-7b"),
    ("historiador", "historia universal con fuentes y contexto", "chat-7b"),
    ("psicologo de apoyo", "escucha activa y tecnicas de bienestar", "chat-7b"),
    ("experto en marketing", "campanas, copy y redes sociales", "chat-7b"),
    ("ingeniero devops", "CI/CD, docker y automatizacion de infra", "coder-14b"),
    ("corrector de estilo", "corregir ortografia y estilo en espanol", "coder-0.5b"),
    ("nutricionista", "planes de alimentacion balanceados", "chat-7b"),
    ("experto en sql", "consultas SQL y modelado de datos", "coder-14b"),
    ("guionista", "guiones, dialogos y estructura narrativa", "chat-7b"),
    ("profesor de matematica", "matematica paso a paso sin saltos", "chat-7b"),
    ("experto en ciberseguridad", "buenas practicas defensivas y auditoria", "coder-14b"),
    ("asistente de resumen", "resumir textos largos en puntos claros", "coder-0.5b"),
    ("experto en python", "python idiomatico, tests y debugging", "coder-14b"),
    ("sommelier", "vinos, maridajes y cata", "chat-7b"),
    ("astronomo", "astronomia y observacion del cielo", "chat-7b"),
    ("experto en regex", "expresiones regulares explicadas", "coder-0.5b"),
    ("consultor de negocio", "estrategia y modelos de negocio", "chat-7b"),
    ("profesor de ingles", "clases de ingles conversacional", "chat-7b"),
    ("experto en git", "flujos de git, rebase y resolucion de conflictos", "coder-0.5b"),
    ("disenador ux", "principios de UX y critica de interfaces", "chat-7b"),
    ("meteorologo", "clima, pronosticos y fenomenos atmosfericos", "chat-7b"),
    ("experto en linux", "shell, permisos y administracion de sistemas", "coder-14b"),
]

_FRASES = [
    "quiero un experto que sea {d}",
    "necesito un asistente {d}",
    "creame un experto para {ded}",
    "me gustaria tener un {d} en mi cognia",
    "agrega un especialista en {ded}",
    "quiero alguien que me ayude con {ded}",
]


def _slug(texto: str) -> str:
    limpio = "".join(c if c.isalnum() or c == " " else "" for c in texto.lower())
    return "-".join(limpio.split())[:40]


def make_spec(dominio: str, dedicacion: str, model_key: str) -> dict:
    """Spec canonica de experto para un dominio del catalogo."""
    return {
        "id": _slug(dominio),
        "nombre": dominio.title(),
        "dedicacion": dedicacion,
        "model_key": model_key,
        "backend": "gguf",
    }


def build_dataset(n: int = 150, llm_fn=None, seed: int = 42) -> list[dict]:
    """n ejemplos {'prompt','completion'} deterministas por seed.

    llm_fn queda aceptado por firma (mejora v1: parafraseo con el 7B) pero
    v0 NO lo usa — 100% plantillas para reproducibilidad del gate.
    n se capea al numero de combinaciones unicas dominio x frase (192).
    """
    # Combinacion determinista dominio x frase SIN repeticion hasta agotar el
    # producto cartesiano (32x6=192): evita duplicados exactos que cruzarian
    # el split train/val como fuga (cazado por test_sin_fuga).
    max_unicos = len(_DOMINIOS) * len(_FRASES)
    if n > max_unicos:
        n = max_unicos
    out = []
    for i in range(n):
        dominio, dedicacion, model_key = _DOMINIOS[i % len(_DOMINIOS)]
        frase = _FRASES[(i // len(_DOMINIOS)) % len(_FRASES)]
        peticion = frase.format(d=dominio, ded=dedicacion)
        spec = make_spec(dominio, dedicacion, model_key)
        out.append({
            "prompt": f"Peticion: {peticion}\nSpec JSON:",
            "completion": " " + json.dumps(spec, ensure_ascii=False),
        })
    # El seed baraja el ORDEN (los ejemplos son el producto determinista de
    # dominios x frases; el seed no cambia su contenido, solo la permutacion).
    random.Random(seed).shuffle(out)
    return out


def split_dataset(dataset: list[dict], val_frac: float = 0.2,
                  seed: int = 42) -> tuple[list[dict], list[dict]]:
    """Split train/val determinista SIN fuga (por indice barajado)."""
    rng = random.Random(seed)
    idx = list(range(len(dataset)))
    rng.shuffle(idx)
    n_val = max(1, int(len(dataset) * val_frac))
    val_idx = set(idx[:n_val])
    train = [d for i, d in enumerate(dataset) if i not in val_idx]
    val = [d for i, d in enumerate(dataset) if i in val_idx]
    return train, val


_CLAVES = ("id", "nombre", "dedicacion", "model_key", "backend")
_MODEL_KEYS = ("coder-0.5b", "chat-7b", "coder-14b")


def eval_json_validity(outputs: list[str]) -> float:
    """% de outputs que son JSON parseable con las 5 claves y model_key valido.

    Funcion PURA (testeable): recibe los textos generados, extrae el primer
    objeto {...} de cada uno y valida contra el contrato de la spec.
    """
    if not outputs:
        return 0.0
    ok = 0
    for text in outputs:
        try:
            start = text.index("{")
            depth, end = 0, None
            for j, ch in enumerate(text[start:], start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = j + 1
                        break
            if end is None:
                continue
            spec = json.loads(text[start:end])
            if (all(k in spec for k in _CLAVES)
                    and spec["model_key"] in _MODEL_KEYS
                    and isinstance(spec["id"], str) and spec["id"]):
                ok += 1
        except (ValueError, KeyError, TypeError):
            continue
    return ok / len(outputs)
