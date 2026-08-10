"""
cognia/agent/lazo_chat.py
=========================
Loop thinking para RESPUESTAS de chat (/lazo, opt-in de sesion).

POR QUE EXISTE: /pulir ya es el lazo de PRODUCTOS web (juez visual + gate) y
horizonte.py el lazo-con-sello de tareas de agente; para el chat no existia
nada. Este modulo clona el patron lazo+sello+corte pero sobre la respuesta
de un turno: borrador -> extraer claims verificables -> verificar CADA claim
con tools REALES del registry -> si algo reprueba, UNA sola revision con el
output CRUDO del tool -> keep-best.

REGLAS QUE LA EVIDENCIA DEL REPO IMPONE (no son opinion):
  - P8: el critico EJECUTA, jamas opina. El veredicto lo da calcular /
    py_validar / ejecutar; para lo factual las tools solo aportan EVIDENCIA
    y el claim queda incierto (ok=None) — un LLM-juez esta prohibido.
  - Sin senal verificable NO se abre el lazo (Huang et al. ICLR 2024,
    arXiv 2310.01798: el self-critique intrinseco DEGRADA; patron
    sin_oraculo de deliberation.py).
  - max_rondas=1: politica adoptada por medicion (nocturna 27/28: rondas
    con sello al azar dieron neto -3 y -7; MANAGER_LOG.md:9546-9561).
  - keep-best SIEMPRE: si la revision reprueba igual o mas que el original,
    se devuelve el original. Con sello al azar el lazo asi NUNCA entrega
    peor que la primera respuesta (la propiedad que falto esa nocturna).
  - Negativa del modelo -> keep-best declarado (el contraejemplo TRIPLICA
    la probabilidad de 'Sorry, I cannot'; MANAGER_LOG.md:11205-11264).
  - ok=None (incierto) NO dispara revision (regla CoVe: no inventar el
    veredicto cuando el tool no lo da).
  - Toda degradacion se DECLARA en el motivo; un lazo que se salta en
    silencio repite el fallo tipico de Cognia.
"""
from __future__ import annotations

import ast
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field

# Techo de claims por respuesta: presupuesto, no capacidad. Cada claim cuesta
# al menos una tool; 5 cubre el chat real sin abrir la puerta a un scan caro.
MAX_CLAIMS = 5

# Motivos posibles de ResultadoLazo.motivo (contrato del render en cli.py).
MOTIVOS = frozenset({
    "sin_sello",                  # nada verificable: respuesta directa
    "sello_ok",                   # todos los claims verificados pasaron
    "revisado_ok",                # hubo reprobados y la revision los corrigio
    "revision_peor_keep_best",    # la revision reprueba >= que el original
    "revision_negada_keep_best",  # el modelo se nego o no cambio nada
    "infra",                      # registry roto / sin chat_fn / chat caido
})


@dataclass(frozen=True)
class Claim:
    texto: str   # el enunciado tal como aparece en la respuesta
    tipo: str    # 'computo' | 'codigo' | 'factual'
    expr: str    # lo ejecutable: 'lhs = rhs' aritmetico, bloque de codigo, o query


@dataclass
class Veredicto:
    claim: Claim
    ok: bool | None      # None = no se pudo verificar -> NO cuenta como reprobado
    evidencia: str       # output CRUDO del tool (resultado, traceback, snippet)
    tool: str            # 'calcular' | 'py_validar' | 'ejecutar' | 'recordar' | 'kg_buscar' | 'buscar'


@dataclass
class ResultadoLazo:
    final: str                        # la respuesta entregada (keep-best)
    veredictos: list = field(default_factory=list)
    rondas: int = 0                   # 0 = no se abrio el lazo
    motivo: str = "sin_sello"


# ── acceso al registry real ────────────────────────────────────────────
def _run_tool_real():
    """run_tool del registry real, o None si el registry esta roto.

    POR QUE una funcion y no un import de modulo: el lazo debe degradar a
    'infra' (respuesta intacta) si tools.py no importa o quedo vacio, y los
    tests pueden monkeypatchear este punto unico."""
    try:
        from cognia.agent.tools import TOOLS, run_tool
    except Exception:
        return None
    if not TOOLS:
        return None
    return run_tool


# ── extraccion de claims (determinista PRIMERO) ────────────────────────
# Aritmetica inline 'expr = valor' (regex del plan A2). El lhs arranca en un
# digito para no casar 'x = 5' de un bloque de codigo o una asignacion.
_RE_ARITMETICA = re.compile(r"(\d[\d\s+*/().,-]{2,})\s*=\s*(-?[\d.,]+)")

# Fences de codigo python; el resto de fences se REMUEVE antes del scan
# aritmetico para no leer 'igualdades' dentro de codigo o logs.
_RE_FENCE_PY = re.compile(r"```(?:python|py)\s*\n(.*?)```", re.S | re.I)
_RE_FENCE_ANY = re.compile(r"```.*?```", re.S)

_OPS_ARITM = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
              ast.Pow, ast.USub, ast.UAdd)


def _es_aritmetica(node) -> bool:
    """True si el AST es SOLO aritmetica de constantes (espejo del _safe_eval
    de tools.py: mismo contrato que 'calcular' aceptara)."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float))
    if isinstance(node, ast.BinOp) and isinstance(node.op, _OPS_ARITM):
        return _es_aritmetica(node.left) and _es_aritmetica(node.right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _OPS_ARITM):
        return _es_aritmetica(node.operand)
    return False


def _recortar_lhs(lhs: str) -> str:
    """El sufijo ejecutable mas largo del lhs, o '' si no hay ninguno.

    POR QUE: la clase de caracteres del regex incluye coma/espacio, asi que
    'en 1999, 2+2' entra entero; el claim real es solo '2+2'. Se prueban los
    sufijos tras cada coma/;/: y gana el primero (mas largo) que parsea como
    aritmetica CON operador — un numero pelado ('10 = 10') no es un claim
    ejecutable y se descarta."""
    lhs = lhs.strip()
    candidatos = [lhs] + [lhs[m.end():].strip()
                          for m in re.finditer(r"[,;:]", lhs)]
    for cand in candidatos:
        cand = cand.strip().strip(".,")
        if not cand or not re.search(r"[+*/-]", cand):
            continue
        try:
            arbol = ast.parse(cand, mode="eval").body
        except SyntaxError:
            continue
        if isinstance(arbol, ast.BinOp) and _es_aritmetica(arbol):
            return cand
    return ""


def _num(s: str) -> float:
    """Parsea un numero con separadores es/en ('1.234,56', '1,234.56', '3,14').

    Heuristica declarada: coma con exactamente 3 decimales y sin punto se lee
    como millar ('1,000' -> 1000); cualquier otra coma sola es decimal es."""
    s = s.strip().rstrip(".,;:").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):     # 1.234,56 (europeo)
            s = s.replace(".", "").replace(",", ".")
        else:                               # 1,234.56 (ingles)
            s = s.replace(",", "")
    elif "," in s:
        ent, _, dec = s.partition(",")
        s = (ent + dec) if len(dec) == 3 else (ent + "." + dec)
    return float(s)


def extraer_claims(respuesta: str, chat_fn=None) -> list:
    """Claims verificables de una respuesta de chat. Determinista PRIMERO.

    - aritmetica inline 'expr = valor' -> tipo 'computo'
    - fences ```python -> tipo 'codigo'
    - chat_fn (opcional) SOLO propone claims factuales atomicos con su query;
      todo claim propuesto SIN query se descarta (sin expr ejecutable no hay
      claim — regla del plan A2).
    Cap MAX_CLAIMS total (presupuesto)."""
    claims: list = []

    # codigo primero (y se remueven TODOS los fences antes del scan
    # aritmetico: una igualdad dentro de un bloque de codigo no es un claim
    # de la prosa, es el codigo mismo).
    for m in _RE_FENCE_PY.finditer(respuesta or ""):
        codigo = m.group(1).strip()
        if codigo:
            primera = codigo.splitlines()[0][:80]
            claims.append(Claim(texto=f"codigo: {primera}", tipo="codigo",
                                expr=codigo))
    prosa = _RE_FENCE_ANY.sub(" ", respuesta or "")

    for m in _RE_ARITMETICA.finditer(prosa):
        lhs = _recortar_lhs(m.group(1))
        if not lhs:
            continue      # sin expr ejecutable no hay claim
        rhs = m.group(2).strip().rstrip(".,;:")
        try:
            _num(rhs)
        except ValueError:
            continue
        claims.append(Claim(texto=f"{lhs} = {rhs}", tipo="computo",
                            expr=f"{lhs} = {rhs}"))

    # LLM solo PROPONE claims factuales (nunca juzga). Formato pedido:
    # una linea 'CLAIM: <enunciado> | QUERY: <consulta>' por hecho atomico.
    if chat_fn is not None and len(claims) < MAX_CLAIMS:
        try:
            crudo = chat_fn(
                "Lista los hechos ATOMICOS y verificables de esta respuesta, "
                "uno por linea, formato exacto:\n"
                "CLAIM: <enunciado> | QUERY: <consulta corta para verificarlo>\n"
                "Si no hay hechos verificables, responde: NINGUNO\n\n"
                f"Respuesta:\n{(respuesta or '')[:3000]}") or ""
            for linea in crudo.splitlines():
                mm = re.match(r"\s*CLAIM:\s*(.+?)\s*\|\s*QUERY:\s*(.+)", linea)
                if not mm:
                    continue
                texto, query = mm.group(1).strip(), mm.group(2).strip()
                if texto and query:
                    claims.append(Claim(texto=texto, tipo="factual", expr=query))
        except Exception:
            pass    # la extraccion LLM es opcional: su fallo no rompe el lazo

    return claims[:MAX_CLAIMS]


# ── verificacion (el critico EJECUTA, jamas opina) ─────────────────────
def _parse_calcular(out: str):
    """Valor numerico del 'RESULTADO calcular: expr = VAL', o None."""
    _, sep, cola = out.rpartition("=")
    if not sep:
        return None
    try:
        return float(cola.strip())
    except ValueError:
        return None


def verificar_claim(c: Claim, registry) -> Veredicto:
    """Despacha UN claim a la tool real que lo puede sellar.

    ``registry`` es el ctx (dict plano) que reciben las tools de tools.py
    (p.ej. {'ai': cognia} para recordar/kg_buscar; puede ir vacio para
    calcular/py_validar/ejecutar). run_tool ya atrapa toda excepcion de tool
    y la devuelve como string 'RESULTADO ... ERROR: ...', asi que aca solo
    se interpreta el formato RESULTADO — nunca se opina."""
    rt = _run_tool_real()
    if rt is None:
        return Veredicto(c, None, "registry de tools no disponible", "")
    ctx = registry if isinstance(registry, dict) else {}

    if c.tipo == "computo":
        lhs, _, rhs = c.expr.rpartition("=")
        out = rt("calcular", lhs.strip(), ctx)
        val = None if "ERROR" in out[:120] else _parse_calcular(out)
        if val is None:
            # calcular no dio veredicto (expr rara): incierto, NO reprobado.
            return Veredicto(c, None, out, "calcular")
        try:
            claimed = _num(rhs)
        except ValueError:
            return Veredicto(c, None, out, "calcular")
        ok = abs(val - claimed) <= 1e-9 * max(1.0, abs(val))
        return Veredicto(c, ok, out, "calcular")

    if c.tipo == "codigo":
        # py_validar y ejecutar toman RUTA/comando: el bloque va a un .py
        # temporal (fuera del workspace del agente a proposito: es un chequeo
        # efimero, no un artefacto de tarea).
        fd, ruta = tempfile.mkstemp(suffix=".py", prefix="lazo_claim_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(c.expr + "\n")
            out = rt("py_validar", ruta, ctx)
            if "ERROR" in out:
                return Veredicto(c, False, out, "py_validar")
            # Sintaxis OK -> ejecutar en sandbox con timeout corto (plan A2).
            # Guard barato: un snippet con input() colgaria hasta el timeout y
            # uno con '...' es un placeholder ilustrativo, no un programa.
            if "input(" in c.expr or "..." in c.expr:
                return Veredicto(c, True, out + " (no ejecutado: snippet "
                                 "interactivo o con placeholder)", "py_validar")
            out2 = rt("ejecutar", f'"{sys.executable}" "{ruta}" | timeout=10',
                      ctx)
            if "(exit" in out2[:40] or "ERROR" in out2[:120]:
                # Import/Name ausentes suelen ser contexto ilustrativo del
                # chat (libreria no instalada, variable 'de antes'), no un
                # claim falso: incierto, se declara y NO dispara revision.
                if ("ModuleNotFoundError" in out2 or "ImportError" in out2
                        or "NameError" in out2):
                    return Veredicto(c, None, out2, "ejecutar")
                return Veredicto(c, False, out2, "ejecutar")
            return Veredicto(c, True, out2, "ejecutar")
        finally:
            try:
                os.unlink(ruta)
            except OSError:
                pass

    # factual: las tools aportan EVIDENCIA cruda; el veredicto true/false
    # exigiria juzgar semantica = LLM-juez, prohibido (P8). ok=None SIEMPRE:
    # incierto declarado, jamas dispara revision.
    for tool, vacio in (("recordar", "sin recuerdos relevantes"),
                        ("kg_buscar", "sin hechos"),
                        ("buscar", "sin resultados")):
        out = rt(tool, c.expr, ctx)
        if "ERROR" not in out[:120] and vacio not in out:
            return Veredicto(c, None, out, tool)
    return Veredicto(c, None, "sin evidencia en memoria/kg/repo", "buscar")


# ── la revision (UNA sola, con evidencia cruda) ────────────────────────
# Detector de negativa: el contraejemplo TRIPLICA la probabilidad de 'Sorry'
# (MANAGER_LOG.md:11205-11264); una negativa NO es una revision.
_RE_NEGATIVA = re.compile(
    r"(?i)\b(sorry|i can(?:no|')t|i cannot|no puedo|lo siento|me niego)\b")


def _es_negativa(texto: str) -> bool:
    return bool(_RE_NEGATIVA.search((texto or "")[:200]))


def _prompt_revision(pregunta: str, respuesta: str, reprobados: list) -> str:
    """El prompt de la unica revision: SOLO evidencia cruda de tools (P8) —
    el error EXACTO, jamas 'esta mal' ni critica verbal."""
    lineas = []
    for v in reprobados:
        lineas.append(f"- afirmacion: {v.claim.texto}\n"
                      f"  evidencia ({v.tool}): {v.evidencia[:400]}")
    return ("Herramientas ejecutadas contradicen parte de tu respuesta.\n\n"
            f"Pregunta original:\n{pregunta}\n\n"
            f"Tu respuesta:\n{respuesta}\n\n"
            "Evidencia cruda (output exacto de las herramientas):\n"
            + "\n".join(lineas) +
            "\n\nReescribe la respuesta completa corrigiendo SOLO lo que la "
            "evidencia contradice. No cambies lo demas.")


def _emitir(on_evento, v: Veredicto) -> None:
    """Render en vivo best-effort: un fallo del render jamas toca el lazo."""
    if on_evento is None:
        return
    try:
        on_evento(v)
    except Exception:
        pass


def lazo_respuesta(pregunta: str, respuesta: str, chat_fn, registry,
                   max_rondas: int = 1, on_evento=None) -> ResultadoLazo:
    """El lazo completo de un turno de chat. Keep-best garantizado.

    Contrato de salida (siempre uno de MOTIVOS):
      sin_sello  -> nada verificable (o todo incierto): respuesta INTACTA
      sello_ok   -> todo lo verificado paso: respuesta intacta, 0 rondas
      revisado_ok / revision_peor_keep_best / revision_negada_keep_best
                 -> hubo reprobados; 1 ronda, keep-best decide el final
      infra      -> registry roto / sin chat_fn / chat caido: intacta
    """
    respuesta = respuesta or ""
    if _run_tool_real() is None:
        # Registry roto: no hay con que verificar. Se declara, no se esconde.
        return ResultadoLazo(respuesta, [], 0, "infra")

    # Extraccion DETERMINISTA aca (sin chat_fn): la propuesta LLM de claims
    # factuales cuesta una llamada por turno y lo factual sale incierto
    # igual (P8) — extraer_claims(chat_fn=...) queda para quien lo pida.
    claims = extraer_claims(respuesta)
    if not claims:
        return ResultadoLazo(respuesta, [], 0, "sin_sello")

    veredictos = []
    for c in claims:
        v = verificar_claim(c, registry)
        veredictos.append(v)
        _emitir(on_evento, v)

    reprobados = [v for v in veredictos if v.ok is False]
    if not reprobados:
        # sello_ok solo si ALGO paso de verdad; claims todos inciertos no son
        # un sello (decir 'sello_ok' con 0 verificados seria mentir).
        motivo = "sello_ok" if any(v.ok is True for v in veredictos) else "sin_sello"
        return ResultadoLazo(respuesta, veredictos, 0, motivo)

    if max_rondas < 1 or not callable(chat_fn):
        # Hay reprobados pero no hay con que revisar: infraestructura del
        # lazo incompleta. Respuesta intacta y motivo declarado.
        return ResultadoLazo(respuesta, veredictos, 0, "infra")

    # UNA revision (max_rondas=1 por politica medida; el parametro existe
    # para el dia que un verificador fiable justifique subirlo).
    try:
        revision = (chat_fn(_prompt_revision(pregunta, respuesta, reprobados))
                    or "").strip()
    except Exception:
        return ResultadoLazo(respuesta, veredictos, 1, "infra")
    if (not revision or _es_negativa(revision)
            or revision == respuesta.strip()):
        # Negativa, vacio o texto identico: el modelo no tiene mas que dar.
        # Keep-best con motivo declarado (jamas re-juzgar lo identico: seria
        # muestrear el ruido del verificador).
        return ResultadoLazo(respuesta, veredictos, 1,
                             "revision_negada_keep_best")

    # Re-verificar SOLO lo que reprobo: se re-extraen los claims de la
    # revision y se verifican los de los MISMOS tipos que fallaron (el claim
    # corregido ya no es textualmente el original; anclar por tipo acota el
    # costo sin perder el contrafactual).
    tipos_rep = {v.claim.tipo for v in reprobados}
    verds_rev = []
    for c in [c for c in extraer_claims(revision) if c.tipo in tipos_rep]:
        v = verificar_claim(c, registry)
        verds_rev.append(v)
        _emitir(on_evento, v)
    rep_rev = [v for v in verds_rev if v.ok is False]

    if len(rep_rev) >= len(reprobados):
        # Keep-best: la revision no mejoro el sello -> ORIGINAL. Esta es la
        # propiedad que garantiza neto >= 0 aun con un sello al azar.
        return ResultadoLazo(respuesta, veredictos + verds_rev, 1,
                             "revision_peor_keep_best")
    return ResultadoLazo(revision, veredictos + verds_rev, 1, "revisado_ok")
