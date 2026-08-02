# -*- coding: utf-8 -*-
"""Motor del modo tutor: Cognia enseña CUALQUIER tema.

Idea (inspirada en DeepTutor, HKUDS/DeepTutor, reconstruido con nuestra
propia repo_a_prompt): un tutor personalizado de por vida. Aquí el modelo
tutor es Cognia y el material NO sale de su memoria paramétrica —
se INVESTIGA en la web y se ancla, que es lo que permite enseñar un tema
que el modelo no vio en el entrenamiento.

Tres decisiones que lo separan de "preguntarle al modelo":

1. MATERIAL ANCLADO Y SANEADO. El texto entra por
   cognia/knowledge/navegador.py, o sea Chromium + el centinela
   (sentinel.evaluar_contenido_web): una página envenenada o fuera de tema
   se descarta y se sigue con la siguiente. Un tutor que se traga una
   inyección de prompt le enseña al alumno lo que quiera el atacante.
2. NADA SE INVENTA EN SILENCIO. La lección declara sus fuentes y su modo
   (con o sin web, con o sin LLM). Si no hubo material, se dice; no se
   fabrica una lección con aire de autoridad.
3. LO APRENDIDO SE PERSISTE donde Cognia ya sabe repasar: tarjetas en
   cognia/learning/spaced_repetition.py (SM-2). El tutor no es un chat que
   se olvida al cerrar la pestaña.

Sin LLM vivo hay modo degradado: la lección se arma con el material real
recortado y se declara "SIN LLM" — útil, honesto, jamás vacío.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict

MAX_MATERIAL = 9000        # chars de material que entran al prompt
MAX_POR_FUENTE = 3500      # ninguna fuente monopoliza el contexto
N_FUENTES = 3

_SYS_LECCION = (
    "Eres un tutor experto y claro. Te doy MATERIAL de referencia citado "
    "de la web. Escribe una leccion breve sobre el tema pedido usando SOLO "
    "ese material: si algo no esta en el material, NO lo afirmes.\n"
    "Responde SOLO con un JSON valido, sin texto alrededor, con esta forma:\n"
    '{"resumen": "2-4 frases que expliquen el tema",\n'
    ' "puntos": [{"titulo": "concepto", "explicacion": "2-3 frases"}],\n'
    ' "preguntas": [{"pregunta": "...", "respuesta_esperada": "..."}]}\n'
    "Entre 4 y 6 puntos y entre 3 y 5 preguntas. Espanol claro, sin "
    "relleno, sin repetir el enunciado."
)

_SYS_DUDA = (
    "Eres un tutor socratico. Responde la duda del alumno usando SOLO el "
    "MATERIAL y la LECCION que te doy. Si la respuesta no esta ahi, dilo "
    "explicitamente ('eso no esta en el material que estudiamos') y sugiere "
    "que se investigue. Sé breve (maximo 6 frases), concreto y en espanol."
)

_SYS_EVALUAR = (
    "Eres un tutor que corrige. Te doy una PREGUNTA, la RESPUESTA ESPERADA "
    "y la RESPUESTA DEL ALUMNO. Devuelve SOLO un JSON valido:\n"
    '{"calidad": 0-5, "correcto": true|false, "retro": "1-3 frases de '
    'retroalimentacion concreta, di que falto o que estuvo bien"}\n'
    "calidad 5 = perfecta; 3 = aceptable con lagunas; 0 = en blanco o "
    "equivocada. Sé justo pero exigente, y habla al alumno de tu."
)


@dataclass
class Leccion:
    tema: str
    resumen: str
    puntos: list = field(default_factory=list)
    preguntas: list = field(default_factory=list)
    fuentes: list = field(default_factory=list)
    descartadas: list = field(default_factory=list)
    modo: str = "llm+web"
    aviso: str = ""
    tarjetas: list = field(default_factory=list)

    def dict(self) -> dict:
        return asdict(self)


def _json_del_modelo(texto: str) -> dict:
    """Primer objeto JSON del texto del modelo. Los razonadores envuelven el
    JSON en prosa o en ```json; recortarlo aqui evita un parser por caller."""
    if not texto:
        return {}
    t = re.sub(r"^```(?:json)?|```$", "", texto.strip(),
               flags=re.MULTILINE).strip()
    ini = t.find("{")
    if ini < 0:
        return {}
    profundidad, en_cadena, escape = 0, False, False
    for i in range(ini, len(t)):
        c = t[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
        elif c == '"':
            en_cadena = not en_cadena
        elif not en_cadena:
            if c == "{":
                profundidad += 1
            elif c == "}":
                profundidad -= 1
                if profundidad == 0:
                    try:
                        return json.loads(t[ini:i + 1])
                    except json.JSONDecodeError:
                        return {}
    return {}


def _material_de(tema: str, buscar_fn) -> tuple:
    """(texto_material, fuentes, descartadas, aviso). Nunca lanza: sin red
    devuelve material vacio con el aviso, y el caller degrada."""
    try:
        r = buscar_fn(tema, max_resultados=N_FUENTES)
    except Exception as exc:
        return "", [], [], f"sin material web ({exc})"
    trozos, fuentes = [], []
    for v in r.get("resultados", []):
        trozos.append(f"### FUENTE: {v['titulo']} ({v['url']})\n"
                      f"{v['texto'][:MAX_POR_FUENTE]}")
        fuentes.append({"titulo": v["titulo"], "url": v["url"],
                        "via": v.get("via", "?")})
    descartadas = [{"url": d.get("url", ""), "razon": d.get("razon", "")}
                   for d in r.get("descartados", [])]
    return ("\n\n".join(trozos)[:MAX_MATERIAL], fuentes, descartadas,
            r.get("aviso", ""))


def _leccion_sin_llm(tema, material, fuentes, descartadas, aviso) -> Leccion:
    """Degradado honesto: el material REAL recortado, marcado como tal."""
    puntos = []
    for f, trozo in zip(fuentes, material.split("### FUENTE:")[1:]):
        cuerpo = trozo.split("\n", 1)[1].strip() if "\n" in trozo else ""
        if cuerpo:
            puntos.append({"titulo": f["titulo"][:80],
                           "explicacion": cuerpo[:600]})
    return Leccion(
        tema=tema,
        resumen=(f"Material recopilado sobre '{tema}' de "
                 f"{len(fuentes)} fuente(s). Sin modelo local disponible no "
                 f"hay explicacion sintetizada: abajo van los extractos "
                 f"reales, sin resumir."),
        puntos=puntos or [{"titulo": "Sin material",
                           "explicacion": "No se obtuvo material utilizable."}],
        preguntas=[],
        fuentes=fuentes, descartadas=descartadas,
        modo="sin-llm",
        aviso="; ".join(x for x in [aviso, "modo SIN LLM: material sin "
                                    "sintetizar"] if x))


def estudiar_tema(tema: str, infer_fn=None, buscar_fn=None,
                  guardar_tarjetas: bool = True) -> Leccion:
    """Investiga `tema`, arma la leccion y persiste tarjetas de repaso.

    infer_fn(system, user) -> str  (la MISMA via interna de Cognia; None =
    modo degradado). buscar_fn(consulta, max_resultados) -> dict del
    navegador (None = navegador real con Chromium + centinela)."""
    tema = (tema or "").strip()
    if not tema:
        raise ValueError("el tema no puede estar vacio")
    if buscar_fn is None:
        from cognia.knowledge.navegador import buscar_en_web as buscar_fn

    material, fuentes, descartadas, aviso = _material_de(tema, buscar_fn)

    if infer_fn is None or not material:
        lec = _leccion_sin_llm(tema, material, fuentes, descartadas, aviso)
    else:
        user = (f"TEMA: {tema}\n\nMATERIAL:\n{material}\n\n"
                f"Escribe la leccion en JSON.")
        try:
            crudo = infer_fn(_SYS_LECCION, user) or ""
        except Exception as exc:
            crudo = ""
            aviso = "; ".join(x for x in [aviso, f"el modelo fallo ({exc})"] if x)
        datos = _json_del_modelo(crudo)
        if not datos.get("resumen"):
            lec = _leccion_sin_llm(tema, material, fuentes, descartadas, aviso)
            lec.modo = "degradado"
            lec.aviso = "; ".join(x for x in [
                lec.aviso, "el modelo no devolvio una leccion utilizable"] if x)
        else:
            lec = Leccion(
                tema=tema,
                resumen=str(datos.get("resumen", ""))[:1200],
                puntos=[p for p in datos.get("puntos", [])
                        if isinstance(p, dict) and p.get("titulo")][:8],
                preguntas=[q for q in datos.get("preguntas", [])
                           if isinstance(q, dict) and q.get("pregunta")][:6],
                fuentes=fuentes, descartadas=descartadas,
                modo="llm+web" if fuentes else "llm",
                aviso=aviso)

    if guardar_tarjetas and lec.puntos:
        lec.tarjetas = _guardar_tarjetas(lec)
    return lec


def _guardar_tarjetas(lec: Leccion) -> list:
    """Una tarjeta SM-2 por punto clave, en el motor de repaso que ya existe.
    Fallar guardando NO puede tumbar la leccion (el alumno ya la tiene)."""
    ids = []
    try:
        from cognia.learning.spaced_repetition import SpacedRepetitionEngine
        sr = SpacedRepetitionEngine()
        for p in lec.puntos:
            try:
                ids.append(sr.add_card(front=str(p.get("titulo", ""))[:200],
                                       back=str(p.get("explicacion", ""))[:800],
                                       topic=lec.tema[:80]))
            except Exception:
                pass
    except Exception:
        lec.aviso = "; ".join(x for x in [
            lec.aviso, "no se pudieron guardar tarjetas de repaso"] if x)
    return ids


def responder_duda(duda: str, leccion: Leccion, infer_fn=None) -> dict:
    """Responde una duda ANCLADA en la leccion. Sin LLM devuelve los puntos
    mas relevantes por solape de palabras: util y sin inventar nada."""
    duda = (duda or "").strip()
    if not duda:
        raise ValueError("la duda no puede estar vacia")
    contexto = json.dumps(
        {"resumen": leccion.resumen, "puntos": leccion.puntos},
        ensure_ascii=False)[:MAX_MATERIAL]

    if infer_fn is not None:
        try:
            txt = infer_fn(_SYS_DUDA,
                           f"LECCION:\n{contexto}\n\nDUDA DEL ALUMNO: {duda}")
            if txt and txt.strip():
                return {"respuesta": txt.strip()[:2000], "modo": "llm",
                        "fuentes": leccion.fuentes}
        except Exception:
            pass
    palabras = {w for w in re.findall(r"[a-záéíóúñ0-9]{4,}", duda.lower())}
    rank = sorted(
        leccion.puntos,
        key=lambda p: -len(palabras & set(re.findall(
            r"[a-záéíóúñ0-9]{4,}",
            (str(p.get("titulo", "")) + " " +
             str(p.get("explicacion", ""))).lower()))))
    top = rank[:2]
    if not top:
        return {"respuesta": "Todavia no hay material estudiado para "
                             "responder eso. Estudia el tema primero.",
                "modo": "sin-llm", "fuentes": leccion.fuentes}
    cuerpo = "\n\n".join(f"**{p.get('titulo')}**: {p.get('explicacion')}"
                         for p in top)
    return {"respuesta": ("Sin modelo disponible no puedo razonar la "
                          "respuesta; esto es lo mas relacionado de la "
                          f"leccion:\n\n{cuerpo}"),
            "modo": "sin-llm", "fuentes": leccion.fuentes}


def evaluar_respuesta(pregunta: str, esperada: str, respuesta: str,
                      infer_fn=None, card_id: int = None) -> dict:
    """Corrige una respuesta y (si hay tarjeta) alimenta el repaso SM-2."""
    respuesta = (respuesta or "").strip()
    if not respuesta:
        out = {"calidad": 0, "correcto": False,
               "retro": "No respondiste nada. Intenta con lo que recuerdes: "
                        "equivocarse es parte del metodo.", "modo": "reglas"}
    elif infer_fn is not None:
        crudo = ""
        try:
            crudo = infer_fn(_SYS_EVALUAR,
                             f"PREGUNTA: {pregunta}\n"
                             f"RESPUESTA ESPERADA: {esperada}\n"
                             f"RESPUESTA DEL ALUMNO: {respuesta}") or ""
        except Exception:
            pass
        d = _json_del_modelo(crudo)
        if "calidad" in d:
            try:
                cal = max(0, min(5, int(d["calidad"])))
            except (TypeError, ValueError):
                cal = 3
            out = {"calidad": cal,
                   "correcto": bool(d.get("correcto", cal >= 3)),
                   "retro": str(d.get("retro", ""))[:600] or
                            "Respuesta registrada.",
                   "modo": "llm"}
        else:
            out = _evaluar_por_solape(esperada, respuesta)
    else:
        out = _evaluar_por_solape(esperada, respuesta)

    if card_id is not None:
        try:
            from cognia.learning.spaced_repetition import SpacedRepetitionEngine
            SpacedRepetitionEngine().review_card(card_id, out["calidad"])
            out["repaso_actualizado"] = True
        except Exception:
            out["repaso_actualizado"] = False
    return out


def _evaluar_por_solape(esperada: str, respuesta: str) -> dict:
    """Fallback determinista: solape de palabras de contenido. Declara que
    es una medida pobre en vez de fingir criterio."""
    def pal(t):
        return {w for w in re.findall(r"[a-záéíóúñ0-9]{4,}", (t or "").lower())}
    esp, res = pal(esperada), pal(respuesta)
    cob = len(esp & res) / len(esp) if esp else 0.0
    cal = 5 if cob >= 0.7 else 4 if cob >= 0.5 else 3 if cob >= 0.3 else \
        2 if cob >= 0.15 else 1
    return {"calidad": cal, "correcto": cob >= 0.3,
            "retro": (f"Sin modelo para corregir: comparacion por palabras "
                      f"({int(cob * 100)}% de la respuesta esperada). "
                      f"Es una medida pobre, tomala como orientativa."),
            "modo": "solape"}
