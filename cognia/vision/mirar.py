"""
cognia/vision/mirar.py
======================
El puente entre los OJOS de Cognia y su cerebro de texto: `/ver` en el CLI.

`cognia/vision/percepcion.py` ya sabe mirar la pantalla (captura + arbol UIA ->
texto, con las ventanas sensibles redactadas), y esta verificado. Lo que faltaba
era el ultimo metro: el usuario no tenia NINGUNA forma de alcanzarlo. Era
capacidad construida, probada y desconectada — la peor clase de deuda, porque
esta pagada y no se entrega.

Este modulo hace una sola cosa: percibir la pantalla y devolver esa percepcion
como texto, opcionalmente respondiendo una pregunta del usuario SOBRE lo que se
ve, usando el mismo cerebro de siempre (sin VLM, sin VRAM extra).

Concreto: dos funciones planas. Sin estado, sin clases nuevas.
"""
from __future__ import annotations

# Cuanto de la percepcion viaja al cerebro. El arbol UIA de una ventana con
# muchos controles se va facil a miles de chars y ahoga la pregunta.
MAX_CONTEXTO = 1800


def percibir_pantalla(max_controles: int = 12, guardar_en: str | None = None) -> dict:
    """Una mirada a la pantalla AHORA. Devuelve {"ok", "texto", "ventana", "error"}.

    Nunca lanza: si faltan las dependencias del sistema (mss/uiautomation) o la
    captura falla, devuelve ok=False con el motivo en claro. El CLI necesita
    poder decirle al usuario QUE le falta, no morir con un traceback.
    """
    try:
        from cognia.vision.percepcion import ServicioPercepcion, describir
    except Exception as e:                      # dependencias del SO ausentes
        return {"ok": False, "texto": "", "ventana": "",
                "error": f"el modulo de percepcion no cargo: {e}"}
    try:
        servicio = ServicioPercepcion()
        p = servicio.instantanea(guardar_en=guardar_en)
        return {"ok": True, "texto": describir(p, max_controles=max_controles),
                "ventana": getattr(p, "ventana", ""), "sensible": getattr(p, "sensible", False),
                "ruta_frame": getattr(p, "ruta_frame", None), "error": ""}
    except Exception as e:
        return {"ok": False, "texto": "", "ventana": "",
                "error": f"no pude mirar la pantalla: {e}"}


def ver(pregunta: str = "", ai=None, max_controles: int = 12) -> str:
    """Lo que el comando /ver le muestra al usuario.

    Sin `pregunta`: describe lo que hay en pantalla.
    Con `pregunta` y un `ai`: se la contesta USANDO lo que ve como contexto.
    """
    p = percibir_pantalla(max_controles=max_controles)
    if not p["ok"]:
        return (f"No pude mirar la pantalla: {p['error']}\n"
                "En Windows esto necesita 'mss' y 'uiautomation' "
                "(pip install mss uiautomation).")
    if p.get("sensible"):
        # describir() ya devuelve el texto redactado; se respeta y no se insiste
        return p["texto"]
    if not pregunta.strip() or ai is None:
        return p["texto"]

    prompt = (
        "Esto es lo que hay AHORA en la pantalla del usuario:\n"
        f"{p['texto'][:MAX_CONTEXTO]}\n\n"
        f"Pregunta del usuario sobre lo que ve: {pregunta.strip()}\n\n"
        "Responde en espanol, breve y concreto, usando SOLO lo que se ve arriba. "
        "Si la pantalla no alcanza para responder, decilo en una linea."
    )
    try:
        orch = getattr(ai, "_orchestrator", None)
        if orch is None:
            from shattering.orchestrator import ShatteringOrchestrator
            orch = ShatteringOrchestrator(mode="local")
            try:
                ai._orchestrator = orch
            except Exception:
                pass
        respuesta = (orch.infer(prompt, max_tokens=320, temperature=0.3).text or "").strip()
        if not respuesta:
            return p["texto"]                   # sin backend: al menos lo que ve
        return f"{respuesta}\n\n[visto: {p['texto'][:200]}]"
    except Exception as e:
        return f"{p['texto']}\n\n(no pude razonar sobre la pantalla: {e})"
