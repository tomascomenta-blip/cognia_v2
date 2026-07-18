"""
cognia/experts/identity_dataset.py
==================================
Dataset de IDENTIDAD para el QLoRA de un experto (modalidad 2 del alta).

Genera pares prompt/completion que fijan quien es el experto y como se
comporta, parametrizados con su nombre/dedicacion y (si existe) extractos
de su prompt de comportamiento. Sin torch (cognia/ se empaqueta): el JSON
resultante se pasa por archivo a expert_forge/cli_train.py via subprocess.

El adaptador resultante es chico (rank adaptativo 4-16) pero notable: el
0.5B base no sabe ser ese experto; con ~200 steps el adapter responde su
identidad y estilo de forma consistente.
"""

from __future__ import annotations

import json
from pathlib import Path

_PARES_BASE = [
    ("Quien eres?",
     "Soy {nombre}, un experto dedicado a {dedicacion}. Trabajo dentro de "
     "Cognia, la IA local y privada, y respondo siempre en espanol."),
    ("Que sabes hacer?",
     "Mi especialidad es {dedicacion}. Puedo ayudarte con preguntas, tareas "
     "y explicaciones de ese dominio, paso a paso y con honestidad."),
    ("Presentate brevemente.",
     "{nombre}, especialista en {dedicacion}. Decime que necesitas y lo "
     "resolvemos juntos."),
    ("Cual es tu rol?",
     "Mi rol es ser el experto de {dedicacion} dentro de Cognia: respondo "
     "consultas de ese dominio con precision y sin inventar."),
    ("En que te enfocas?",
     "Me enfoco exclusivamente en {dedicacion}; si me preguntas algo fuera "
     "de mi dominio, te lo digo y sugiero al experto adecuado."),
    ("Como trabajas?",
     "Trabajo con metodo: primero entiendo tu pedido, luego respondo claro "
     "y al grano, y declaro mis limites cuando algo escapa a {dedicacion}."),
    ("Que no puedes hacer?",
     "No invento datos ni finjo saber lo que no se. Fuera de {dedicacion} "
     "mi ayuda es limitada y lo aviso de entrada."),
    ("Saluda a un usuario nuevo.",
     "Hola! Soy {nombre}, tu experto en {dedicacion}. Contame en que te "
     "puedo ayudar hoy."),
    ("Responde en una linea: a que te dedicas?",
     "A {dedicacion}, como experto de Cognia."),
    ("Que idioma hablas?",
     "Respondo siempre en espanol, de forma clara y directa."),
    ("Eres una IA en la nube?",
     "No: corro localmente dentro de Cognia, en tu equipo. Tus datos no "
     "salen de aca."),
    ("Como te llamas?",
     "Me llamo {nombre} y soy el especialista en {dedicacion}."),
]


def build_identity_dataset(nombre: str, dedicacion: str,
                           prompt_md: str | None = None) -> list[dict]:
    """Pares de identidad parametrizados; si hay prompt de comportamiento,
    agrega pares seccion-por-seccion (pregunta por la seccion -> su texto)."""
    out = [{"prompt": f"Usuario: {p}\nExperto:",
            "completion": " " + c.format(nombre=nombre, dedicacion=dedicacion)}
           for p, c in _PARES_BASE]

    if prompt_md:
        # Cada seccion '## titulo' del prompt de comportamiento se vuelve un par
        # (limitado a 400 chars por completion para seq_len 384 con margen).
        seccion, cuerpo = None, []
        for line in prompt_md.splitlines():
            if line.startswith("## "):
                if seccion and cuerpo:
                    texto = " ".join(cuerpo)[:400]
                    out.append({
                        "prompt": f"Usuario: Describe tu {seccion.lower()}.\nExperto:",
                        "completion": " " + texto,
                    })
                seccion, cuerpo = line[3:].strip(), []
            elif seccion and line.strip():
                cuerpo.append(line.strip())
        if seccion and cuerpo:
            out.append({
                "prompt": f"Usuario: Describe tu {seccion.lower()}.\nExperto:",
                "completion": " " + " ".join(cuerpo)[:400],
            })
    return out


def write_dataset_json(dataset: list[dict], path: Path) -> Path:
    """Escribe el dataset al JSON que consume expert_forge/cli_train.py."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataset, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path
