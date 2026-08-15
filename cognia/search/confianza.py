# -*- coding: utf-8 -*-
"""Responder con CONFIANZA en vez de con sí/no, y que el número signifique algo.

EL PROBLEMA CON EL BINARIO. Un sistema que contesta "sí" con la misma cara
cuando lo leyó en una fuente que cuando lo recuerda a medias obliga al humano
a desconfiar de TODO por igual — y desconfiar de todo por igual es no tener
información. Peor: en este mismo repo, un veredicto binario mal atribuido
mandó un modelo con tool-calling perfecto al régimen degradado
(`capacidad.sondar`, 2026-08-14) porque "no llamó" y "no pudo llamar" daban
el mismo `False`.

DE DÓNDE SALE EL NÚMERO. No se le pide al modelo que se autoevalúe: los
modelos están mal calibrados hacia arriba y "¿qué tan seguro estás?" produce
0,9 casi siempre. La confianza se compone de señales que se pueden VERIFICAR
sin preguntarle a nadie:

  - la cita está literal en la página que se dice           (evidencia.py)
  - cuántos DOMINIOS independientes la sostienen
  - si alguna fuente la contradice
  - si la afirmación viene con fuente o es memoria del modelo

CUÁNDO SIRVE. Solo si está CALIBRADA: que las respuestas dadas con 0,8
acierten ~80% de las veces. Por eso este módulo trae su propio medidor (ECE y
Brier) y el número no se declara "bueno" hasta correrlo contra un banco. Una
confianza sin calibrar es un adorno más peligroso que no tener ninguno,
porque invita a confiar.

LA REGLA DE ACCIÓN. Por debajo de UMBRAL_INVESTIGAR el sistema no contesta a
medias: va a buscar. Ese es el enganche con el harness de búsqueda.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

# Por debajo de esto no se contesta: se investiga. 0,60 y no 0,50 porque el
# empate no es "medio bien", es no saber — y el coste de buscar (segundos)
# es mucho menor que el de afirmar algo falso.
UMBRAL_INVESTIGAR = 0.60
# Por debajo de esto, ni investigando se junta base: se ABSTIENE y lo dice.
UMBRAL_ABSTENERSE = 0.25

# Pesos de las señales. Suman 1,0 y están puestos con un criterio explícito:
# la cita verificada pesa más que todo lo demás junto porque es la única
# señal que no depende de lo que el modelo crea.
PESO_EVIDENCIA = 0.50
PESO_FUENTES = 0.30
PESO_ACUERDO = 0.20

# Piso de una afirmación SIN ninguna fuente (memoria pura del modelo). No es
# 0: el modelo sabe cosas. Pero es bajo a propósito, porque es justo el
# terreno donde inventa con seguridad.
CONFIANZA_SIN_FUENTE = 0.30


@dataclass
class Veredicto:
    """Una respuesta con su grado, sus razones y qué hacer a continuación."""
    valor: str
    confianza: float
    razones: list = field(default_factory=list)
    accion: str = "responder"          # responder | investigar | abstenerse
    fuentes: list = field(default_factory=list)

    def frase(self) -> str:
        """Cómo se le dice esto a un humano, sin fingir precisión.

        Los cortes son gruesos a propósito: decir "confianza 0,73" sugiere
        una precisión de dos decimales que el número no tiene.
        """
        c = self.confianza
        if c >= 0.85:
            nivel = "con alta confianza"
        elif c >= UMBRAL_INVESTIGAR:
            nivel = "con confianza media"
        elif c >= UMBRAL_ABSTENERSE:
            nivel = "con confianza BAJA"
        else:
            nivel = "sin base suficiente"
        detalle = "; ".join(self.razones[:3])
        return f"{self.valor} [{nivel} ({c:.2f}): {detalle}]"


def _dominio(url: str) -> str:
    try:
        d = (urlparse(url).netloc or "").lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def evaluar(valor: str, apoyos: list, contradicciones: list = None) -> Veredicto:
    """Compone la confianza de una afirmación a partir de señales duras.

    apoyos: [{source_url, evidencia_verificada: bool}]  (los que la sostienen)
    contradicciones: idem, los que dicen otra cosa.

    Independencia por DOMINIO, no por URL: tres páginas del mismo sitio son
    una fuente repetida, y contarlas como tres es exactamente cómo un rumor
    se vuelve un hecho.
    """
    apoyos = apoyos or []
    contradicciones = contradicciones or []
    razones: list = []

    if not apoyos:
        return Veredicto(
            valor=valor, confianza=CONFIANZA_SIN_FUENTE,
            razones=["sin ninguna fuente: es memoria del modelo"],
            accion="investigar", fuentes=[])

    verificados = [a for a in apoyos if a.get("evidencia_verificada")]
    dominios = {_dominio(a.get("source_url", "")) for a in apoyos} - {""}
    dominios_ok = {_dominio(a.get("source_url", "")) for a in verificados} - {""}

    # (1) Evidencia literal. Fracción de apoyos con cita comprobada.
    s_evidencia = len(verificados) / len(apoyos)
    if verificados:
        razones.append(f"{len(verificados)}/{len(apoyos)} citas verificadas "
                       f"literalmente en su página")
    else:
        razones.append("ninguna cita se pudo verificar en su página")

    # (2) Fuentes independientes. Satura en 3: la cuarta confirmación de lo
    # mismo no añade tanto como sugiere un promedio lineal.
    n = len(dominios_ok) or len(dominios)
    s_fuentes = min(n, 3) / 3.0
    razones.append(f"{n} dominio(s) independiente(s)")

    # (3) Acuerdo. Una sola contradicción pesa mucho: si dos fuentes buenas
    # dicen cosas distintas, lo honesto es que baje, no promediar y seguir.
    if contradicciones:
        dom_contra = {_dominio(c.get("source_url", ""))
                      for c in contradicciones} - {""}
        s_acuerdo = max(0.0, 1.0 - 0.5 * len(dom_contra))
        razones.append(f"CONTRADICHA por {len(dom_contra)} dominio(s)")
    else:
        s_acuerdo = 1.0

    conf = (PESO_EVIDENCIA * s_evidencia + PESO_FUENTES * s_fuentes
            + PESO_ACUERDO * s_acuerdo)
    # Sin una sola cita verificada no se pasa de la mitad, por muchos
    # dominios que la repitan: repetición no es verificación.
    if not verificados:
        conf = min(conf, 0.5)
    conf = round(max(0.0, min(1.0, conf)), 2)

    if conf < UMBRAL_ABSTENERSE:
        accion = "abstenerse"
    elif conf < UMBRAL_INVESTIGAR:
        accion = "investigar"
    else:
        accion = "responder"
    return Veredicto(valor=valor, confianza=conf, razones=razones,
                     accion=accion,
                     fuentes=sorted(dominios))


def calibracion(pares: list, bins: int = 5) -> dict:
    """¿La confianza SIGNIFICA algo? ECE + Brier sobre (confianza, acierto).

    pares: [(confianza_float, acerto_bool)]

    - **Brier**: error cuadrático medio. 0 es perfecto; 0,25 es lo que saca
      decir siempre 0,5.
    - **ECE**: distancia media entre la confianza declarada y el acierto real
      por tramo. Es el número que dice si un 0,8 vale 80%.
    - **sobreconfianza**: confianza media − acierto medio. Positivo = el
      sistema se cree más de lo que acierta, que es el sesgo por defecto de
      un LLM y lo que este módulo existe para no heredar.

    Sin correr esto contra un banco, los pesos de arriba son una hipótesis,
    no una medición. Se dice aquí para que nadie lo olvide al leer el número.
    """
    pares = [(float(c), bool(a)) for c, a in (pares or [])]
    if not pares:
        return {"n": 0, "ece": None, "brier": None, "sobreconfianza": None,
                "tramos": []}
    n = len(pares)
    brier = sum((c - (1.0 if a else 0.0)) ** 2 for c, a in pares) / n
    conf_media = sum(c for c, _ in pares) / n
    acierto_medio = sum(1 for _, a in pares if a) / n

    tramos, ece = [], 0.0
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        dentro = [(c, a) for c, a in pares
                  if (c >= lo and (c < hi or (i == bins - 1 and c <= hi)))]
        if not dentro:
            continue
        c_med = sum(c for c, _ in dentro) / len(dentro)
        a_med = sum(1 for _, a in dentro if a) / len(dentro)
        ece += (len(dentro) / n) * abs(c_med - a_med)
        tramos.append({"rango": f"{lo:.1f}-{hi:.1f}", "n": len(dentro),
                       "confianza_media": round(c_med, 3),
                       "acierto_real": round(a_med, 3)})
    return {"n": n, "ece": round(ece, 4), "brier": round(brier, 4),
            "sobreconfianza": round(conf_media - acierto_medio, 4),
            "tramos": tramos}
