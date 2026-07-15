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


def analizar_calibracion(path=None) -> dict:
    """Mejora continua (Future AGI nativo): analiza el ledger REAL para juzgar
    si la cascada MoM está bien calibrada, y RECOMIENDA. Read-only, no cambia
    el sampling (sin gate): mide y aconseja, no auto-ajusta. Señales:
    - ¿el escalado al 7B correlaciona con más dificultad? (umbral sano)
    - ¿el 7B mejora sobre el 3B cuando entra? (score_7b vs score_3b)
    - ¿dónde falla el pipeline por banda de dificultad?"""
    filas = _leer_bon(path)
    if len(filas) < 5:
        return {"n": len(filas), "recomendaciones": [
            "Muy pocos registros para calibrar (min 5)."]}
    esc = [f for f in filas if f.get("escalado_7b")]
    no_esc = [f for f in filas if not f.get("escalado_7b")]
    def _media_dif(fs):
        d = [f.get("difficulty") for f in fs
             if isinstance(f.get("difficulty"), (int, float))]
        return round(sum(d) / len(d), 3) if d else None
    dif_esc, dif_no = _media_dif(esc), _media_dif(no_esc)

    # ¿el 7B ayudó? (cuando hay ambos scores y total)
    ayudo = mantuvo = 0
    for f in esc:
        s3, s7, tot = f.get("score_3b"), f.get("score_7b"), f.get("total")
        if isinstance(s3, int) and isinstance(s7, int):
            if s7 > s3:
                ayudo += 1
            else:
                mantuvo += 1

    # éxito por banda de dificultad
    bandas = {"facil (<0.3)": [], "media (0.3-0.6)": [], "dura (>=0.6)": []}
    for f in filas:
        d, tot, sc = (f.get("difficulty"), f.get("total"), f.get("score"))
        if not isinstance(d, (int, float)) or not tot:
            continue
        ok = 1 if (sc is not None and sc >= tot) else 0
        b = ("facil (<0.3)" if d < 0.3
             else "media (0.3-0.6)" if d < 0.6 else "dura (>=0.6)")
        bandas[b].append(ok)
    exito_banda = {k: (f"{sum(v)}/{len(v)}" if v else "s/d")
                   for k, v in bandas.items()}

    rec = []
    if dif_esc is not None and dif_no is not None:
        if dif_esc > dif_no + 0.1:
            rec.append(f"Umbral de escalado SANO: el 7B entra en tareas más "
                       f"duras (dif media {dif_esc} vs {dif_no}).")
        else:
            rec.append(f"REVISAR umbral: el escalado NO discrimina dificultad "
                       f"(esc {dif_esc} vs no-esc {dif_no}).")
    if esc:
        tasa = round(len(esc) / len(filas), 2)
        rec.append(f"Escala al 7B en {tasa:.0%} de las tareas.")
        if ayudo + mantuvo > 0:
            rec.append(f"Cuando el 7B entra con datos comparables: mejoró "
                       f"{ayudo}, mantuvo {mantuvo}.")
    dura = bandas["dura (>=0.6)"]
    if dura and sum(dura) / len(dura) < 0.5:
        rec.append("El pipeline falla la mayoría de las tareas DURAS "
                   "(candidato al superorganismo, COGNIA_SUPERORGANISMO=1).")
    return {"n": len(filas), "dif_media_escalado": dif_esc,
            "dif_media_no_escalado": dif_no,
            "7b_mejoro": ayudo, "7b_mantuvo": mantuvo,
            "exito_por_banda": exito_banda, "recomendaciones": rec}


def panel(user_id="default") -> dict:
    """El panel completo (dict serializable)."""
    return {
        "codigo": resumen_codigo(),
        "features": resumen_features(user_id=user_id),
        "eventos": resumen_eventos(),
        "calibracion": analizar_calibracion(),
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

    cal = p.get("calibracion")
    if cal and cal.get("recomendaciones"):
        L.append(f"\nMEJORA CONTINUA (calibracion sobre {cal['n']} tareas):")
        if cal.get("exito_por_banda"):
            eb = ", ".join(f"{k}:{v}"
                           for k, v in cal["exito_por_banda"].items())
            L.append(f"  exito por dificultad: {eb}")
        for r in cal["recomendaciones"]:
            L.append(f"  - {r}")
    return "\n".join(L)
