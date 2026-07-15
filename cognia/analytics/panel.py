# -*- coding: utf-8 -*-
"""Panel de analíticas local (Plausible nativo, todo privado).

Gap del inventario 2026-07-14: Cognia tiene TRES fuentes de telemetría sin
capa de agregación común:
- _bon_telemetry.jsonl (agent/tools.py): cada generar_codigo con dificultad,
  rank_mode, score/total, costo, flags de escalado (7B/q35/mesa/superorg).
- feature_usage (analytics/usage_analytics.py): uso de features por día.
- MetricsCollector (monitoring): latencia/tokens/errores en memoria.
Y desde hoy, el historial del bus de eventos (cognia/events.py).

Este módulo las unifica en UN panel — sin dashboard externo, sin enviar
nada a la red (Plausible-style pero 100% local, como pide el mandato). Es
solo-lectura sobre lo ya registrado: no agrega instrumentación nueva ni
cambia el sampling. Alimenta el comando /analiticas y (a futuro) un panel
de la oficina.
"""
import json
from collections import Counter
from pathlib import Path

_BON_TELEMETRY = (Path(__file__).resolve().parents[1]
                  / "agent" / "generated_tools" / "_bon_telemetry.jsonl")


def _leer_bon(path=None, limite=2000) -> list:
    """Últimos `limite` registros del ledger BoN (tolerante a líneas rotas)."""
    p = Path(path) if path else _BON_TELEMETRY
    if not p.is_file():
        return []
    filas = []
    try:
        for ln in p.read_text(encoding="utf-8").splitlines()[-limite:]:
            ln = ln.strip()
            if not ln:
                continue
            try:
                filas.append(json.loads(ln))
            except Exception:
                continue
    except Exception:
        return []
    return filas


def resumen_codigo(path=None) -> dict:
    """Agrega el ledger de generar_codigo: cuántas tareas, mix de dificultad,
    cuántas escalaron a cada etapa de la cascada, costo medio, éxito."""
    filas = _leer_bon(path)
    if not filas:
        return {"n": 0}
    rank = Counter(f.get("rank_mode") or "?" for f in filas)
    dif = [f.get("difficulty") for f in filas if isinstance(
        f.get("difficulty"), (int, float))]
    secs = [f.get("secs") for f in filas if isinstance(
        f.get("secs"), (int, float))]
    def _cuenta(flag):
        return sum(1 for f in filas if f.get(flag))
    # éxito = score >= total (cuando hay tests visibles con total > 0)
    con_tests = [f for f in filas if f.get("total")]
    exitos = sum(1 for f in con_tests
                 if f.get("score") is not None
                 and f.get("score") >= f.get("total"))
    return {
        "n": len(filas),
        "rank_mode": dict(rank.most_common()),
        "dificultad_media": round(sum(dif) / len(dif), 3) if dif else None,
        "secs_medio": round(sum(secs) / len(secs), 1) if secs else None,
        "escalado_7b": _cuenta("escalado_7b"),
        "escalado_q35": _cuenta("escalado_q35"),
        "mesa_redonda": _cuenta("mesa_redonda"),
        "superorganismo": _cuenta("superorganismo"),
        "exito_tests_visibles": (f"{exitos}/{len(con_tests)}"
                                 if con_tests else "s/d"),
    }


def resumen_features(analytics=None, user_id="default", days=30) -> dict:
    """Top features y stats desde UsageAnalytics (SQLite)."""
    try:
        if analytics is None:
            from cognia.analytics.usage_analytics import UsageAnalytics
            analytics = UsageAnalytics()
        top = analytics.get_top_features(user_id=user_id, days=days, limit=8)
        stats = analytics.get_stats(user_id=user_id)
        return {"top": top, "stats": stats}
    except Exception:
        return {"top": [], "stats": {}}


def resumen_eventos(n=200) -> dict:
    """Conteo por tipo de evento del bus interno (esta sesión)."""
    try:
        from cognia.events import get_bus
        hist = get_bus().historial(n=n)
    except Exception:
        return {"total": 0, "por_tipo": {}}
    por_tipo = Counter(e.get("evento") for e in hist)
    # desglose útil: veredictos de Sentinel y ok de tools
    sentinel = Counter(e.get("veredicto") for e in hist
                       if e.get("evento") == "sentinel.evaluada")
    tools_ok = Counter(str(e.get("ok")) for e in hist
                       if e.get("evento") == "tool.ejecutada")
    return {"total": len(hist), "por_tipo": dict(por_tipo.most_common()),
            "sentinel": dict(sentinel), "tools_ok": dict(tools_ok)}


def panel(user_id="default") -> dict:
    """El panel completo (dict serializable)."""
    return {
        "codigo": resumen_codigo(),
        "features": resumen_features(user_id=user_id),
        "eventos": resumen_eventos(),
    }


def render_texto(p: dict = None, user_id="default") -> str:
    """Panel en texto plano para el CLI (/analiticas)."""
    p = p or panel(user_id=user_id)
    L = ["=== ANALITICAS COGNIA (local, privado) ==="]

    c = p["codigo"]
    if c.get("n"):
        L.append(f"\nCODIGO (generar_codigo): {c['n']} tareas registradas")
        L.append(f"  dificultad media: {c['dificultad_media']} | "
                 f"costo medio: {c['secs_medio']}s | "
                 f"exito tests visibles: {c['exito_tests_visibles']}")
        casc = (f"7B={c['escalado_7b']} q35={c['escalado_q35']} "
                f"mesa={c['mesa_redonda']} superorg={c['superorganismo']}")
        L.append(f"  escalados de cascada: {casc}")
        modos = ", ".join(f"{k}:{v}" for k, v in
                          list(c["rank_mode"].items())[:6])
        L.append(f"  modos: {modos}")
    else:
        L.append("\nCODIGO: sin registros de generar_codigo aun.")

    f = p["features"]
    if f.get("top"):
        top = ", ".join(f"{t['feature']}({t['total']})" for t in f["top"][:6])
        L.append(f"\nFEATURES mas usadas (30d): {top}")
        st = f.get("stats") or {}
        if st:
            L.append(f"  total eventos: {st.get('total_events', '?')} | "
                     f"dias activos: {st.get('active_days', '?')} | "
                     f"racha: {st.get('streak', '?')}")
    else:
        L.append("\nFEATURES: sin datos de uso aun.")

    e = p["eventos"]
    L.append(f"\nEVENTOS (bus, esta sesion): {e['total']}")
    if e["por_tipo"]:
        tipos = ", ".join(f"{k}:{v}" for k, v in
                          list(e["por_tipo"].items())[:6])
        L.append(f"  {tipos}")
    if e.get("sentinel"):
        L.append(f"  sentinel: {e['sentinel']}")
    return "\n".join(L)
