# -*- coding: utf-8 -*-
"""Dataset sintético de HISTORIAL LARGO con hechos sembrados, para medir memoria externa.

Genera una conversación de agente realista (turnos user/assistant/tool: listados,
lecturas de ficheros, salidas de pytest, logs) de N tokens, y siembra en posiciones
ALEATORIAS hechos de siete clases que luego se preguntan:

  A  recordar_antiguo      decisión sembrada muy al principio, pregunta al final
  B  ignorar_irrelevante   distractores con el mismo vocabulario y OTRA entidad
  C  contradiccion         "X = A" al principio, "X pasa a B porque ..." después
  D  decision_actualizada  igual que C pero con dos actualizaciones (A → B → C)
  E  codigo                función definida en un fichero leído; pregunta "cómo funciona"
  F  restriccion           restricción del dueño ("nunca usar X") que debe sobrevivir
  G  error_solucion        un error y su solución, separados por mucho ruido

Determinista por `--semilla`. Los tokens se ESTIMAN con chars/2.5 (calibrado contra /tokenize) (calibrable con
`--chars-por-token` tras medir contra /tokenize del server). No envía nada al modelo.

Uso:
  python scripts/memoria_larga/generar_dataset.py --tokens 100000 --salida scratchpad/ml/100k
  → mensajes.jsonl (cada línea: {i, role, content, pos_tokens, tool, sembrado})
  → preguntas.json (lista de {id, tipo, pregunta, esperado: [claves], evitar: [claves], pos_tokens: [...]})
  → resumen.json
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

CHARS_POR_TOKEN = 2.5   # calibrado 2026-09-04 contra /tokenize del Qwen3.8-27B: 2,52 sobre este material

_MODULOS = ["facturas", "clientes", "pedidos", "inventario", "usuarios", "reportes", "auth",
            "pagos", "envios", "catalogo", "notificaciones", "auditoria", "cache", "colas"]
_COMPONENTES = ["base de datos", "cola de mensajes", "cache", "autenticación", "logger",
                "cliente HTTP", "planificador", "serializador", "motor de plantillas"]
_OPCIONES = {
    "base de datos": ["SQLite", "PostgreSQL", "MySQL", "DuckDB"],
    "cola de mensajes": ["Redis Streams", "RabbitMQ", "Kafka", "una tabla en SQLite"],
    "cache": ["diskcache", "Redis", "un dict en memoria", "memcached"],
    "autenticación": ["JWT", "sesiones firmadas", "OAuth2", "API keys"],
    "logger": ["logging estándar", "structlog", "loguru", "print a fichero"],
    "cliente HTTP": ["httpx", "requests", "urllib", "aiohttp"],
    "planificador": ["APScheduler", "cron del sistema", "celery beat", "un bucle propio"],
    "serializador": ["pydantic", "dataclasses + json", "marshmallow", "attrs"],
    "motor de plantillas": ["Jinja2", "Mako", "f-strings", "Chameleon"],
}
_MOTIVOS = ["el rendimiento en la prueba de carga fue 4× peor", "no soporta transacciones anidadas",
            "el dueño lo prohibió por licencia", "rompía en Windows con rutas con espacios",
            "el equipo ya lo conoce", "consumía 2 GB de RAM en reposo", "no tiene wheel para Python 3.12"]


class Gen:
    def __init__(self, semilla: int):
        self.r = random.Random(semilla)
        self.i = 0
        self.pos_chars = 0
        self.mensajes: list[dict] = []

    def tokens(self) -> int:
        return int(self.pos_chars / CHARS_POR_TOKEN)

    def add(self, role: str, content: str, tool: str | None = None, sembrado: str | None = None) -> dict:
        m = {"i": self.i, "role": role, "content": content, "pos_tokens": self.tokens(),
             "tool": tool, "sembrado": sembrado}
        self.mensajes.append(m)
        self.i += 1
        self.pos_chars += len(content)
        return m

    # ── relleno realista ────────────────────────────────────────────────────
    def relleno(self) -> None:
        k = self.r.random()
        mod = self.r.choice(_MODULOS)
        if k < 0.30:
            n = self.r.randint(8, 40)
            lineas = "\n".join(f"{i:4d}| " + self.r.choice([
                f"def {self.r.choice(['obtener','listar','guardar','validar','normalizar'])}_{mod}_{self.r.randint(1,99)}(x):",
                f"    return x.get('{mod}', {self.r.randint(0,9)})",
                f"    # TODO revisar {mod}", "", f"import {self.r.choice(['os','json','re','pathlib'])}",
                f"    if not x: raise ValueError('{mod} vacío')"]) for i in range(1, n + 1))
            self.add("assistant", "", tool="leer_archivo")
            self.add("tool", f"RESULTADO leer_archivo {mod}/{self.r.choice(['modelo','servicio','vista','tests'])}.py:\n{lineas}", tool="leer_archivo")
        elif k < 0.55:
            ok = self.r.randint(3, 60)
            fail = self.r.choice([0, 0, 0, 1, 2])
            salida = f"RESULTADO tests: rc={1 if fail else 0} {ok} passed" + (f", {fail} failed" if fail else "") + f" in {self.r.uniform(0.2, 9):.2f}s"
            if fail:
                salida += f"\nFAILED tests/test_{mod}.py::test_{self.r.choice(['borde','vacio','unicode','concurrencia'])} - AssertionError"
            self.add("assistant", "", tool="tests")
            self.add("tool", salida, tool="tests")
        elif k < 0.75:
            files = "\n".join(f"{mod}/{self.r.choice(['modelo','servicio','vista','tests','__init__'])}.py  {self.r.randint(200, 9000)} B" for _ in range(self.r.randint(3, 12)))
            self.add("assistant", "", tool="listar")
            self.add("tool", f"RESULTADO listar {mod}/:\n{files}", tool="listar")
        elif k < 0.90:
            self.add("assistant", self.r.choice([
                f"Reviso el módulo {mod} antes de tocar nada.",
                f"Los tests de {mod} pasan; sigo con la siguiente subtarea.",
                f"Ajusto el manejo de errores en {mod} y vuelvo a correr la suite.",
                f"Anoto que {mod} depende de {self.r.choice(_MODULOS)}; lo tendré en cuenta al refactorizar."]))
        else:
            self.add("user", self.r.choice([
                f"seguí con {mod}", "ok", "dale", f"¿cómo va {mod}?", "continuá, no te frenes",
                f"revisá que {mod} no rompa nada"]))

    # ── hechos sembrados ────────────────────────────────────────────────────
    def decision(self, comp: str, valor: str, motivo: str | None = None, tag: str = "") -> dict:
        txt = f"Decisión: para la {comp} usamos {valor}." + (f" Motivo: {motivo}." if motivo else "")
        return self.add("user", txt, sembrado=tag)

    def cambio(self, comp: str, viejo: str, nuevo: str, motivo: str, tag: str) -> dict:
        txt = (f"Cambio de decisión: la {comp} deja de ser {viejo} y pasa a ser {nuevo}, "
               f"porque {motivo}. Actualizá lo que haga falta.")
        return self.add("user", txt, sembrado=tag)

    def restriccion(self, texto: str, tag: str) -> dict:
        return self.add("user", f"Restricción, no negociable: {texto}.", sembrado=tag)

    def codigo(self, nombre: str, fichero: str, tag: str) -> dict:
        cuerpo = (f"RESULTADO leer_archivo {fichero}:\n"
                  f"   1| def {nombre}(importe, tramo):\n"
                  f"   2|     \"\"\"Calcula el recargo por tramo: 0-100 → 2 %, 100-1000 → 5 %, >1000 → 9 %,\n"
                  f"   3|     y suma un fijo de 1.50 si el tramo es 'urgente'. Redondea a 2 decimales.\"\"\"\n"
                  f"   4|     pct = 0.02 if importe <= 100 else 0.05 if importe <= 1000 else 0.09\n"
                  f"   5|     fijo = 1.50 if tramo == 'urgente' else 0.0\n"
                  f"   6|     return round(importe * pct + fijo, 2)\n")
        self.add("assistant", "", tool="leer_archivo")
        return self.add("tool", cuerpo, tool="leer_archivo", sembrado=tag)

    def error_solucion(self, tag: str) -> tuple[dict, dict]:
        mod = self.r.choice(_MODULOS)
        err = self.add("tool", f"RESULTADO tests: rc=1 12 passed, 1 failed\nFAILED tests/test_{mod}.py::test_fecha_limite - "
                               f"TypeError: can't compare offset-naive and offset-aware datetimes", tool="tests", sembrado=tag + "_error")
        return err, None

    def solucion(self, tag: str) -> dict:
        return self.add("assistant", f"Arreglado el fallo de fechas: el problema era comparar un datetime naive con uno aware; "
                                     f"ahora normalizo todo a UTC con `.replace(tzinfo=timezone.utc)` en el parser de entrada.",
                        sembrado=tag + "_solucion")


def generar(tokens_objetivo: int, semilla: int) -> tuple[list[dict], list[dict]]:
    g = Gen(semilla)
    r = g.r
    preguntas: list[dict] = []
    total_chars = int(tokens_objetivo * CHARS_POR_TOKEN)
    comps = r.sample(_COMPONENTES, 6)
    # planificación de posiciones (fracciones del historial)
    plan = []
    cA, cC, cD, cF = comps[0], comps[1], comps[2], comps[3]
    vA = r.choice(_OPCIONES[cA])
    vC1, vC2 = r.sample(_OPCIONES[cC], 2)
    vD1, vD2, vD3 = r.sample(_OPCIONES[cD], 3)
    motC, motD2, motD3 = r.sample(_MOTIVOS, 3)
    fn_nombre = f"calcular_recargo_{r.randint(100, 999)}"
    fn_fichero = f"{r.choice(_MODULOS)}/tarifas.py"
    restr = r.choice(["nunca escribir fuera de src/ ni de tests/", "no instalar dependencias nuevas sin avisar",
                      "todo mensaje al usuario en español", "no borrar ficheros .md del repo"])
    plan += [(0.02, "A", lambda: g.decision(cA, vA, r.choice(_MOTIVOS), "A")),
             (0.05, "F", lambda: g.restriccion(restr, "F")),
             (r.uniform(0.05, 0.25), "C1", lambda: g.decision(cC, vC1, None, "C1")),
             (r.uniform(0.55, 0.85), "C2", lambda: g.cambio(cC, vC1, vC2, motC, "C2")),
             (r.uniform(0.05, 0.20), "D1", lambda: g.decision(cD, vD1, None, "D1")),
             (r.uniform(0.30, 0.50), "D2", lambda: g.cambio(cD, vD1, vD2, motD2, "D2")),
             (r.uniform(0.65, 0.90), "D3", lambda: g.cambio(cD, vD2, vD3, motD3, "D3")),
             (r.uniform(0.10, 0.60), "E", lambda: g.codigo(fn_nombre, fn_fichero, "E")),
             (r.uniform(0.15, 0.45), "G_error", lambda: g.error_solucion("G")[0]),
             (r.uniform(0.50, 0.80), "G_solucion", lambda: g.solucion("G"))]
    # distractores B: misma componente que A pero en OTRO proyecto/entidad, y opciones distintas
    cB = cA
    vB = r.choice([v for v in _OPCIONES[cB] if v != vA])
    for f in (r.uniform(0.2, 0.9) for _ in range(3)):
        plan.append((f, "B", lambda vB=vB, cB=cB: g.add(
            "user", f"Aparte, en el proyecto del vecino usan {vB} para la {cB}; no aplica aquí, es solo un comentario.", sembrado="B")))
    plan.sort(key=lambda x: x[0])
    idx = 0
    g.add("user", f"Vamos a construir el sistema de {r.choice(_MODULOS)} paso a paso. Mantené un registro de las decisiones.")
    g.add("assistant", "Entendido. Empiezo revisando la estructura y anotando cada decisión.")
    while g.pos_chars < total_chars:
        frac = g.pos_chars / total_chars
        while idx < len(plan) and plan[idx][0] <= frac:
            m = plan[idx][2]()
            plan[idx] = (plan[idx][0], plan[idx][1], m)
            idx += 1
        g.relleno()
    while idx < len(plan):
        m = plan[idx][2]()
        plan[idx] = (plan[idx][0], plan[idx][1], m)
        idx += 1
    pos = {tag: m["pos_tokens"] for _, tag, m in plan}
    preguntas += [
        {"id": "A", "tipo": "recordar_antiguo", "pregunta": f"¿Qué decidimos usar para la {cA} y por qué?",
         "esperado": [vA], "evitar": [vB], "pos_tokens": [pos["A"]]},
        {"id": "B", "tipo": "ignorar_irrelevante", "pregunta": f"¿Qué usa NUESTRO proyecto para la {cB}?",
         "esperado": [vA], "evitar": [vB], "pos_tokens": [pos["A"]]},
        {"id": "C", "tipo": "contradiccion", "pregunta": f"¿Cuál es la {cC} actual del proyecto y por qué se cambió?",
         "esperado": [vC2, motC.split(" ")[1]], "evitar": [], "actual": vC2, "anterior": vC1,
         "pos_tokens": [pos["C1"], pos["C2"]]},
        {"id": "D", "tipo": "decision_actualizada", "pregunta": f"Historial completo de la decisión sobre la {cD}: ¿qué valores tuvo y cuál es el vigente?",
         "esperado": [vD3], "secuencia": [vD1, vD2, vD3], "evitar": [], "pos_tokens": [pos["D1"], pos["D2"], pos["D3"]]},
        {"id": "E", "tipo": "codigo", "pregunta": f"¿Cómo funciona {fn_nombre}? ¿Qué porcentaje aplica por encima de 1000 y qué fijo suma si es urgente?",
         "esperado": ["9", "1.50"], "evitar": [], "fichero": fn_fichero, "pos_tokens": [pos["E"]]},
        {"id": "F", "tipo": "restriccion", "pregunta": "¿Qué restricciones no negociables puso el dueño en esta tarea?",
         "esperado": [restr.split(" ")[0], restr.split(" ")[-1]], "evitar": [], "texto": restr, "pos_tokens": [pos["F"]]},
        {"id": "G", "tipo": "error_solucion", "pregunta": "Tuvimos un error de datetimes en los tests: ¿cuál era y cómo se resolvió?",
         "esperado": ["naive", "UTC"], "evitar": [], "pos_tokens": [pos["G_error"], pos["G_solucion"]]},
    ]
    return g.mensajes, preguntas


def main() -> int:
    global CHARS_POR_TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokens", type=int, required=True)
    ap.add_argument("--semilla", type=int, default=7)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--chars-por-token", type=float, default=CHARS_POR_TOKEN)
    a = ap.parse_args()
    CHARS_POR_TOKEN = a.chars_por_token
    out = Path(a.salida)
    out.mkdir(parents=True, exist_ok=True)
    mensajes, preguntas = generar(a.tokens, a.semilla)
    with open(out / "mensajes.jsonl", "w", encoding="utf-8") as f:
        for m in mensajes:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    (out / "preguntas.json").write_text(json.dumps(preguntas, ensure_ascii=False, indent=1), encoding="utf-8")
    chars = sum(len(m["content"]) for m in mensajes)
    resumen = {"tokens_objetivo": a.tokens, "tokens_estimados": int(chars / CHARS_POR_TOKEN), "chars": chars,
               "mensajes": len(mensajes), "sembrados": sum(1 for m in mensajes if m["sembrado"]),
               "semilla": a.semilla, "chars_por_token": CHARS_POR_TOKEN,
               "posiciones": {p["id"]: p["pos_tokens"] for p in preguntas}}
    (out / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(resumen, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
