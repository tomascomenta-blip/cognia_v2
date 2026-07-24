"""
cognia/pensamiento_profundo.py
==============================
Pensamiento profundo en TRES ACTOS: SONAR -> PLANIFICAR -> EJECUTAR.

Antes, "pensar profundo" era una sola cosa: `razonador.razonar()` mandaba el
prompt al modelo thinking y devolvia una respuesta. Util para preguntas,
pobre para CREAR: el modelo se cine a lo literal del pedido y no produce nada
ejecutable.

El pedido del dueno (2026-07-23) es un pipeline explicito:

  1. IDEA      -- leer el prompt y SONAR. Imaginar MAS ALLA de lo pedido,
                  agregar lo que nadie pidio, y bajarlo a un documento
                  exhaustivo (temperatura alta: aca se premia divergir).
  2. PLAN      -- recien entonces, convertir esa idea en pasos EJECUTABLES
                  por un agente con herramientas (temperatura baja: aca se
                  premia converger). Se materializa en el `Plan` mutable de
                  agent/plan_artifact.py, con estado por paso.
  3. EJECUCION -- recorrer el plan paso a paso con el agente real, llevando
                  la IDEA como contexto en CADA paso para que lo construido
                  siga siendo lo sonado y no una version aguada.

Dos cosas medidas en la maquina real que moldean el codigo:

* El modelo thinking (Qwen3-4B-Thinking) NO cierra `</think>` si se queda sin
  presupuesto: `razonar()` devuelve entonces todo el pensamiento como si fuera
  respuesta. `_cosecha()` lo detecta y rescata el contenido igual — el sueno
  truncado sigue siendo material valido, tirarlo seria perder 10k tokens.
* Razonador (4B, ~5GB VRAM) y agente (7B/14B) no tienen por que convivir: la
  fase 3 no vuelve a usar el razonador, asi que se lo descarta antes de
  arrancar el agente y la VRAM queda para quien trabaja.

Concreto: funciones planas + dicts, sin capas. El runner del agente se INYECTA
(`runner=`) en vez de importarse, porque el agente vive en cli.py y el import
seria circular.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

from cognia.agent.plan_artifact import Plan, parse_pasos, _plan_path

# Presupuestos de tokens por fase (GPU). En CPU se dividen (ver _cap()).
TOK_IDEA = 14000
TOK_PLAN = 6000

# Cuanta IDEA viaja con cada paso del agente. El sueno completo puede ser de
# 10k+ tokens; meterlo entero en CADA paso reventaria el ctx y ahogaria la
# instruccion del paso. Se manda la cabeza (vision + lo esencial).
IDEA_EN_CONTEXTO = 2200

MAX_PASOS = 14      # techo de pasos del plan (cada uno es una corrida de agente)


def _es_gpu() -> bool:
    from cognia.razonador import _es_gpu as _g
    return _g()


# Una PREGUNTA no se suena ni se ejecuta: se contesta. "por que el cielo es
# azul" no necesita un plan de 8 pasos ni un agente escribiendo archivos.
# Heuristica barata y explicita (interrogativo al inicio o '?' al final);
# cualquier otra cosa entra al pipeline de tres actos.
_INTERROGATIVOS = ("que ", "qué ", "por que", "por qué", "porque ", "como ",
                   "cómo ", "cual ", "cuál ", "quien ", "quién ", "cuando ",
                   "cuándo ", "donde ", "dónde ", "cuanto ", "cuánto ",
                   "explicame", "explicá", "explica ")


def es_pregunta(texto: str) -> bool:
    """True si el pedido es una pregunta a contestar, no algo a construir."""
    t = (texto or "").strip().lower()
    if not t:
        return False
    return t.endswith("?") or t.startswith(_INTERROGATIVOS)


def _cap(tokens: int) -> int:
    """Presupuesto real para esta maquina: en CPU, un tercio (o sonar tarda una era)."""
    return tokens if _es_gpu() else max(1500, tokens // 3)


def _limpiar_think(texto: str) -> str:
    """Saca tags de thinking sueltos, conservando el contenido."""
    return re.sub(r"</?think>", "", texto or "").strip()


def _cosecha(out: Optional[dict]) -> str:
    """El TEXTO UTIL de una corrida del razonador, pase lo que pase.

    Casos reales (medidos 2026-07-23 con Qwen3-4B-Thinking-2507):
      - normal: hay `pensamiento` y `respuesta` -> vale la respuesta.
      - truncado por limite: el modelo nunca cerro `</think>`, `pensamiento`
        queda vacio y `respuesta` es en realidad el monologo entero. Devolverlo
        igual (limpio de tags): es contenido, no basura.
      - respuesta vacia pero pensamiento lleno -> vale el pensamiento.
    """
    if not out:
        return ""
    resp = _limpiar_think(out.get("respuesta", ""))
    if resp:
        return resp
    return _limpiar_think(out.get("pensamiento", ""))


# ── ACTO 1: la IDEA ────────────────────────────────────────────────────────
_PROMPT_IDEA = """\
Sos la parte IMAGINATIVA de una mente. Tu unico trabajo ahora es SONAR una idea.
NO planifiques, NO escribas codigo, NO hagas listas de tareas: eso viene despues.

El pedido que llego es:
\"\"\"{pedido}\"\"\"

Ese pedido es apenas la SEMILLA. Tu obligacion es ir MUCHO MAS ALLA de lo que
dice: agregale todo lo que quien lo pidio no penso pero amaria encontrar. Si
pidio algo simple, imaginalo en su version ambiciosa. Sonar de menos es el unico
error posible en esta fase.

Desarrolla la idea con MUCHISIMO detalle, en prosa y sin ahorrar palabras:

1. VISION — que es esto en una frase, y por que es memorable y no generico.
2. EL MUNDO — la ambientacion, el tono, la historia detras, la estetica. Que se
   ve, que se escucha, que se siente. Inventa nombres propios concretos.
3. EL CORAZON — la mecanica/experiencia central, explicada hasta el ultimo
   detalle: que hace el usuario segundo a segundo y por que engancha.
4. LO QUE NADIE PIDIO — al menos CINCO agregados que no estaban en el pedido y
   que elevan la idea: sistemas secundarios, giros, secretos, detalles vivos.
   Este es el punto mas importante: es donde la idea deja de ser obvia.
5. DIFICULTAD Y PROGRESION — como empieza, como escala, como se domina.
6. DETALLES CONCRETOS — numeros, nombres, valores, colores, formulas. Nada de
   "algun tipo de enemigo": decime cual, como se llama, como se comporta.
7. EL MOMENTO — la escena que alguien contaria despues de probarlo.

Escribi la idea completa, exhaustiva y vivida. Cuanto mas concreta y mas larga,
mejor.

ESCRIBI TODO EN ESPANOL (el modelo thinking razona en ingles por defecto: la
idea tiene que quedar en espanol igual)."""


def imaginar(pedido: str, print_fn: Callable = None,
             max_tokens: int = None, temperature: float = 0.95) -> dict:
    """ACTO 1 — sonar la idea. Devuelve {"idea", "tokens", "rounds"}.

    Temperatura ALTA a proposito: esta fase existe para divergir. La
    convergencia es problema del acto 2.
    """
    from cognia.razonador import razonar
    if callable(print_fn):
        print_fn("[detail]ACTO 1/3 — sonando la idea (imaginacion libre)...[/detail]")
    out = razonar(_PROMPT_IDEA.format(pedido=pedido.strip()),
                  print_fn=print_fn,
                  max_tokens=max_tokens or _cap(TOK_IDEA),
                  temperature=temperature)
    idea = _cosecha(out)
    return {"idea": idea,
            "tokens": (out or {}).get("tokens", 0),
            "rounds": (out or {}).get("rounds", 0)}


# ── ACTO 2: el PLAN ────────────────────────────────────────────────────────
_PROMPT_PLAN = """\
Sos la parte EJECUTIVA de una mente. La parte imaginativa ya sono esta idea:

--- IDEA ---
{idea}
--- FIN IDEA ---

El pedido original era: "{pedido}"

Convertila en un PLAN de trabajo para un agente que tiene herramientas reales
(escribir archivos, leer archivos, ejecutar comandos, correr tests).

Reglas del plan:
- Entre 5 y {max_pasos} pasos, en orden de ejecucion.
- Cada paso es UNA linea numerada "N. ..." que empieza con un verbo de accion y
  dice QUE ARCHIVO se toca y QUE tiene que quedar funcionando al terminarlo.
- CADA PASO CREA UN ARCHIVO DISTINTO (modulos separados: por ejemplo motor.py,
  mundo.py, enemigos.py, interfaz.py, y al final main.py que los une). NO
  amontones todo en main.py: si varios pasos escriben el mismo archivo, cada
  uno pisa al anterior y el trabajo se pierde.
- Cada paso tiene que ser verificable: al terminarlo se puede decir si salio
  bien o mal.
- El primer paso crea la base ejecutable; los del medio agregan la mecanica
  central; los ultimos suman lo que la idea agrego de mas y cierran probando
  que todo corre.
- Sos fiel a la IDEA: los agregados que sono la parte imaginativa entran en el
  plan, no se recortan por comodidad.

Respondeme SOLO la lista numerada, EN ESPANOL. Nada de introduccion ni cierre."""


def planificar(pedido: str, idea: str, print_fn: Callable = None,
               max_pasos: int = MAX_PASOS, max_tokens: int = None) -> Plan:
    """ACTO 2 — bajar la idea a pasos ejecutables. Devuelve un `Plan` (guardado).

    Temperatura baja: aca se converge. Si el modelo no emite lista numerada se
    reintenta UNA vez con la instruccion endurecida (el thinking a veces se va
    en prosa); si tampoco, el Plan vuelve vacio y el caller decide.
    """
    from cognia.razonador import razonar
    if callable(print_fn):
        print_fn("[detail]ACTO 2/3 — bajando la idea a un plan ejecutable...[/detail]")
    prompt = _PROMPT_PLAN.format(idea=idea[:9000], pedido=pedido.strip(),
                                 max_pasos=max_pasos)
    pasos = []
    for intento in (1, 2):
        p = prompt if intento == 1 else (
            prompt + "\n\nIMPORTANTE: tu respuesta anterior no fue una lista. "
            "Respondeme UNICAMENTE lineas con el formato '1. hacer X en el "
            "archivo Y', una por linea.")
        out = razonar(p, print_fn=print_fn,
                      max_tokens=max_tokens or _cap(TOK_PLAN),
                      temperature=0.3)
        pasos = parse_pasos(_cosecha(out))
        if pasos:
            break
        if callable(print_fn):
            print_fn("[detail]el plan no salio como lista; reintentando...[/detail]")
    plan = Plan(objetivo=pedido.strip()[:200], pasos=pasos[:max_pasos])
    if plan.pasos:
        plan.pasos[0]["estado"] = "→"
        try:
            plan.guardar(_plan_path())
        except Exception:
            pass
    return plan


# ── ACTO 3: la EJECUCION ───────────────────────────────────────────────────
def _inventario(limite: int = 12) -> str:
    """Lo que YA existe en el workspace, con su tamano.

    Cazado en la primera corrida real (2026-07-23): sin esto, el paso 3
    reescribio `nodes.py` desde cero y lo dejo en 148 bytes (era 970, con la
    clase y el Enum) — un stub roto que referenciaba un tipo inexistente. El
    agente no destruia por malicia: no sabia que el archivo ya estaba hecho.
    """
    try:
        base = _plan_path().parent
        vistos = sorted(p for p in base.glob("*.py") if p.is_file())[:limite]
        if not vistos:
            return ""
        filas = "\n".join(f"  - {p.name} ({p.stat().st_size} bytes)" for p in vistos)
        return ("\nYA CONSTRUIDO — estos archivos existen y funcionan:\n" + filas
                + "\nSobre ESOS archivos esta PROHIBIDO usar escribir_archivo "
                  "(borra el archivo entero y se pierde lo hecho): usa "
                  "leer_archivo y despues editar_archivo o apendar_archivo. "
                  "escribir_archivo es SOLO para archivos nuevos.\n")
    except Exception:
        return ""


def _guia(idea: str, plan: Plan, i: int) -> str:
    """Contexto que viaja con CADA paso: la vision + el mapa + donde estamos.

    Sin esto el agente ejecuta el paso k como si fuera una tarea suelta y a los
    tres pasos ya no esta construyendo lo que se sono."""
    return (
        "IDEA QUE ESTAS CONSTRUYENDO (respetala, no la simplifiques):\n"
        + idea[:IDEA_EN_CONTEXTO].strip()
        + "\n\n" + plan.render()
        + _inventario()
        + f"\n\nEstas en el paso {i + 1} de {len(plan.pasos)}. Hace SOLO ese paso, "
          "completo y funcionando. Los demas pasos no son tu problema ahora.\n"
          "El nombre de archivo es EXACTAMENTE el que nombra el paso (por "
          "ejemplo 'commands.py'): nunca uses la frase del paso como ruta.\n"
          "El archivo tiene que ser CODIGO REAL Y COMPLETO: clases y funciones "
          "con su logica escrita, valores concretos de la idea (nombres, "
          "numeros, colores). Prohibido el stub — nada de 'pass', 'TODO' ni una "
          "funcion que solo imprime que existe. Si el modulo es corto, es que "
          "esta vacio: escribi la mecanica de verdad."
    )


def _rotos() -> list:
    """Los .py del workspace que NO parsean, con su error. `[(nombre, error)]`.

    Medido en la primera corrida real (2026-07-23): 4 de 8 archivos escritos
    por el agente tenian SyntaxError y el plan siguio avanzando igual, un paso
    sobre otro. Un paso no esta 'hecho' si dejo un archivo que ni compila.
    """
    import ast
    fallos = []
    try:
        base = _plan_path().parent
        for p in sorted(base.glob("*.py")):
            try:
                ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError as e:
                fallos.append((p.name, f"linea {e.lineno}: {e.msg}"))
            except Exception:
                pass
    except Exception:
        pass
    return fallos


def _reparar(rotos: list, runner: Callable, print_fn: Callable = None) -> list:
    """UNA pasada de reparacion sobre los archivos que no compilan.

    Una sola: el disyuntor del repo (CLAUDE.md regla 11) dice que insistir
    ciego empeora. Si tras esta pasada sigue roto, se reporta como roto y el
    plan sigue — mentir sobre el estado seria peor que dejarlo anotado.
    """
    for nombre, err in rotos:
        if callable(print_fn):
            print_fn(f"[detail]reparando {nombre} ({err})[/detail]")
        try:
            runner(f"El archivo {nombre} tiene un error de sintaxis ({err}). "
                   f"Leelo con leer_archivo, corregi SOLO ese error y "
                   f"reescribilo completo y valido con escribir_archivo.",
                   "Estas arreglando un archivo que ya existe: conserva todo "
                   "lo que ya hace y cambia unicamente lo que impide que "
                   "compile.")
        except Exception:
            pass
    return _rotos()


def ejecutar(plan: Plan, idea: str, runner: Callable,
             print_fn: Callable = None, soltar_razonador: bool = True) -> list:
    """ACTO 3 — recorrer el plan con el agente real, paso a paso.

    `runner(tarea, guidance) -> str` es el agente (se inyecta para no importar
    cli.py desde aca). Devuelve una lista de {"paso", "resultado", "ok"}.

    Antes de empezar suelta el razonador: la fase 3 no lo usa y son ~5GB de
    VRAM que el modelo del agente aprovecha mejor.
    """
    if soltar_razonador:
        try:
            from cognia.razonador import descartar
            descartar()
            if callable(print_fn):
                print_fn("[detail]razonador liberado (VRAM para el agente)[/detail]")
        except Exception:
            pass

    resultados = []
    total = len(plan.pasos)
    for i, paso in enumerate(plan.pasos):
        texto = paso["texto"]
        if callable(print_fn):
            print_fn(f"[detail]ACTO 3/3 — paso {i + 1}/{total}: {texto[:90]}[/detail]")
        plan.marcar(i, "en_curso")
        try:
            plan.guardar(_plan_path())
        except Exception:
            pass
        rotos_antes = {n for n, _ in _rotos()}
        try:
            res = runner(texto, _guia(idea, plan, i)) or ""
        except Exception as e:                      # un paso que revienta no
            res = f"ERROR en el paso: {e}"          # mata la corrida entera
        ok = bool(res) and not res.strip().startswith("ERROR")

        # COMPUERTA: el paso no cierra dejando codigo que no compila. Solo se
        # persiguen los archivos que ESTE paso rompio (los de arrastre ya
        # tuvieron su turno) y con UNA pasada de reparacion.
        nuevos = [(n, e) for n, e in _rotos() if n not in rotos_antes]
        if nuevos:
            quedan = _reparar(nuevos, runner, print_fn)
            sigue_roto = [n for n, _ in quedan if n not in rotos_antes]
            if sigue_roto:
                ok = False
                res += f"\n[paso cerrado con codigo invalido: {', '.join(sigue_roto)}]"
                if callable(print_fn):
                    print_fn(f"[detail]paso {i + 1}: sigue sin compilar "
                             f"{', '.join(sigue_roto)}[/detail]")
        plan.marcar(i, "hecho" if ok else "pendiente")
        try:
            plan.guardar(_plan_path())
        except Exception:
            pass
        resultados.append({"paso": texto, "resultado": res, "ok": ok})
    return resultados


# ── Orquestacion ───────────────────────────────────────────────────────────
def guardar_idea(idea: str, plan: Plan, pedido: str) -> Optional[Path]:
    """Deja la IDEA y el PLAN en el workspace (IDEA.md) para poder leerlos."""
    try:
        destino = _plan_path().parent / "IDEA.md"
        destino.write_text(
            f"# Idea — {pedido.strip()[:120]}\n\n{idea}\n\n---\n\n"
            + plan.render() + "\n", encoding="utf-8")
        return destino
    except Exception:
        return None


def pensar_profundo(pedido: str, runner: Callable = None,
                    print_fn: Callable = None, ejecutar_plan: bool = True,
                    max_pasos: int = MAX_PASOS) -> dict:
    """El pipeline completo: SONAR -> PLANIFICAR -> EJECUTAR.

    Devuelve {"idea", "plan", "resultados", "tokens_idea", "archivo_idea"}.
    Con `ejecutar_plan=False` corta despues del acto 2 (util para revisar el
    sueno antes de gastar el agente en construirlo).
    """
    im = imaginar(pedido, print_fn=print_fn)
    idea = im["idea"]
    if not idea:
        return {"idea": "", "plan": Plan(), "resultados": [],
                "tokens_idea": 0, "archivo_idea": None,
                "error": "el razonador no produjo idea (backend caido?)"}

    plan = planificar(pedido, idea, print_fn=print_fn, max_pasos=max_pasos)
    archivo = guardar_idea(idea, plan, pedido)
    if callable(print_fn):
        print_fn(f"[detail]idea: {len(idea)} chars ({im['tokens']} tokens) | "
                 f"plan: {len(plan.pasos)} pasos"
                 + (f" | guardado en {archivo}" if archivo else "") + "[/detail]")

    resultados = []
    if ejecutar_plan and plan.pasos and callable(runner):
        resultados = ejecutar(plan, idea, runner, print_fn=print_fn)
    return {"idea": idea, "plan": plan, "resultados": resultados,
            "tokens_idea": im["tokens"], "archivo_idea": archivo}


def resumen(res: dict) -> str:
    """Cierre legible de una corrida (lo que el CLI le muestra al usuario)."""
    if res.get("error"):
        return f"Pensamiento profundo fallo: {res['error']}"
    plan = res.get("plan") or Plan()
    hechos = sum(1 for r in res.get("resultados", []) if r["ok"])
    total = len(plan.pasos)
    lineas = [
        f"Idea sonada: {len(res.get('idea', ''))} chars "
        f"({res.get('tokens_idea', 0)} tokens de razonamiento).",
    ]
    if res.get("archivo_idea"):
        lineas.append(f"Idea completa en: {res['archivo_idea']}")
    lineas.append("")
    lineas.append(plan.render())
    if res.get("resultados"):
        lineas.append("")
        lineas.append(f"Ejecucion: {hechos}/{total} pasos completados.")
        ultimo = res["resultados"][-1]["resultado"]
        if ultimo:
            lineas.append("")
            lineas.append("Ultimo resultado: " + ultimo[:600])
    return "\n".join(lineas)
