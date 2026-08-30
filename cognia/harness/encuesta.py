# -*- coding: utf-8 -*-
"""
cognia/harness/encuesta.py
==========================
Encuestas CONTEXTUALES para el mejorador de prompts. Modulo PURO.

QUE PROBLEMA RESUELVE
---------------------
El dueno teclea "hazme una pagina web". El reformulador puede escribir eso
mas bonito, pero no puede saber para que es, con que tecnologia, ni que tiene
que hacer. Hasta ahora habia dos salidas malas: inventarse esas decisiones
(prohibido: es LA falla del mejorador) o devolver una reformulacion vaga.
La tercera salida es preguntar -- pero preguntar bien.

LAS CUATRO REGLAS QUE HACEN QUE UNA ENCUESTA NO MOLESTE
-------------------------------------------------------
1. NO PREGUNTAR LO QUE YA ESTA DICHO. Si dos turnos atras el usuario dijo
   "en Python", el stack no se pregunta. Esto se comprueba DOS veces: la
   semilla deterministica ya filtra por senales de cobertura
   (contexto_mejora.faltantes_por_tipo) y ademas se le dice al generador
   explicitamente, con el contexto delante.
2. POCAS. Tope duro de MAX_PREGUNTAS. Una encuesta de ocho preguntas no se
   contesta: se cancela. Y una cancelada no aporta nada.
3. SIEMPRE SE PUEDE NO CONTESTAR. Saltar una, contestar a medias, salir sin
   contestar y apagar las encuestas para siempre son cuatro salidas
   distintas, y las cuatro son legitimas. Ninguna bloquea el turno.
4. SOLO CUANDO APORTA. Si el pedido ya es especifico, no hay encuesta. El
   generador puede devolver cero preguntas y eso es una respuesta correcta,
   no un fallo.

CONTRATO (el mismo que mejorar_prompt.py, por diseno)
-----------------------------------------------------
- PURO: no importa cognia.cli, no imprime, no pregunta, no persiste. Quien
  lo cablea decide como se muestran las preguntas y como se recogen las
  respuestas; aqui solo se PREPARAN y se INCORPORAN.
- Degradacion silenciosa hacia "sin encuesta": si no hay backend, si el
  modelo devuelve basura o si tarda, se cae a la semilla deterministica y,
  si tampoco hay, a cero preguntas. Nunca se rompe el turno por una encuesta.
- generar_fn inyectable para testear sin backend.

QUE LLAMAR DESDE EL CLI (para no reconstruir las reglas en cuatro sitios)
------------------------------------------------------------------------
    enc = encuesta_para(texto, contexto=..., faltantes=...,
                        estado=<config 'encuestas'>, hay_tty=<selector.hay_tty()>)
        -> una Encuesta SIEMPRE (nunca None, nunca lanza). Aplica las cuatro
           puertas en orden y no llama al backend si alguna cierra.
    es_degradacion(enc.motivo)  -> si hay que gritarlo por _aviso_degradado
                                   (los motivos que son una DECISION no).
    como_preguntar(pregunta)    -> con que funcion de cognia/ux/selector.py se
                                   muestra, con que opciones y con que titulo.
    incorporar(texto, respuestas) -> el pedido enriquecido, listo para enviar.

Y despues, para reformular ese texto ya enriquecido sin que el reformulador
vuelva a meter preguntas dentro (que es el bug que esto vino a arreglar):
    mejorar_prompt.mejorar(enriquecido, encuesta_previa=True,
                           version=mejorar_prompt.version_para(estado,
                                                               encuesta_previa=True,
                                                               estilo=estilo))
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

__all__ = ["Pregunta", "Encuesta", "preparar", "incorporar", "vale_la_pena",
           "encuesta_para", "como_preguntar", "es_degradacion",
           "OTRA_OPCION", "SELECTOR_POR_TIPO",
           "MAX_PREGUNTAS", "TIPOS", "ESTADOS"]

# Estados del interruptor, con los mismos nombres que /mejorar para que el
# dueno no tenga que aprender dos vocabularios.
ESTADOS = ("off", "auto")

TIPOS = ("abierta", "unica", "multiple")

# Tope duro. Tres es el numero que sale de la propia mision ("no invasivas"):
# con cuatro ya se lee como formulario. El generador puede devolver menos.
MAX_PREGUNTAS = 3

# Tope de opciones por pregunta cerrada. Mas de cinco no se leen de un
# vistazo en un selector de terminal y empujan a elegir la primera.
MAX_OPCIONES = 5

TEMPERATURA = 0.3          # algo mas que el reformulador: aqui SI hay que
                           # generar variedad segun el caso

# 320 y no 500. Tres preguntas con sus opciones en JSON ocupan ~200 tokens
# medidos; 500 era margen de sobra pagado en SEGUNDOS. En esta maquina el
# cerebro genera a 20-30 tok/s, asi que cada 100 tokens de margen son 3-5 s
# de espera del usuario entre el Enter y la primera pregunta.
N_PREDICT = 320

# El mismo timeout que el reformulador (25 s) y por el mismo motivo: esto
# corre entre el Enter y el envio. Un backend colgado no puede congelar el
# turno -- y aqui, ademas, la caida es blanda: se cae a la semilla
# deterministica y el usuario sigue teniendo sus preguntas.
TIMEOUT_DEFECTO = 25.0

# Por debajo de esto no se pregunta nada: un pedido largo ya trae sus
# decisiones tomadas, y la encuesta seria ruido. Medido a ojo sobre los
# pedidos del dueno: los que necesitan encuesta son los de una linea.
MAX_CHARS_PARA_PREGUNTAR = 320


_SYSTEM = """Eres el asistente que detecta QUE INFORMACION FALTA para poder \
ejecutar bien un pedido.

Recibes el pedido del usuario y, a veces, contexto de su sesion. Devuelves \
SOLO un JSON con las preguntas minimas que hay que hacerle.

FORMATO EXACTO (nada antes, nada despues, sin explicaciones):
{"preguntas": [
  {"id": "stack", "tipo": "unica", "texto": "Con que tecnologia?",
   "opciones": ["HTML y JS sin frameworks", "React", "Python"],
   "porque": "cambia por completo el codigo a escribir"}
]}

TIPOS PERMITIDOS
- "abierta"  : el usuario escribe libremente. Sin "opciones".
- "unica"    : elige UNA. Entre 2 y 5 opciones.
- "multiple" : elige VARIAS. Entre 2 y 5 opciones.

REGLAS DURAS
1. Como MUCHO 3 preguntas. Menos es mejor. Si el pedido ya es claro,
   devuelve {"preguntas": []}.
2. NO preguntes nada que el pedido o el contexto ya respondan. Si el contexto
   dice que el usuario ya eligio una tecnologia, no preguntes por ella.
3. Pregunta solo lo que CAMBIA EL RESULTADO. "Que color prefieres" no cambia
   nada si nadie hablo de diseno; "para que va a servir" si.
4. Preguntas cortas, en espanol, en segunda persona, sin jerga tecnica
   innecesaria. Las opciones, de 2 a 5 palabras cada una.
5. En las preguntas cerradas, las opciones tienen que ser EXHAUSTIVAS y
   EXCLUYENTES entre si; si no puedes garantizarlo, usa "abierta".
6. Nada de preguntas de cortesia, ni de confirmacion ("quieres que lo haga?").
"""


@dataclass
class Pregunta:
    id: str
    tipo: str
    texto: str
    opciones: list = field(default_factory=list)
    porque: str = ""

    def a_dict(self) -> dict:
        return {"id": self.id, "tipo": self.tipo, "texto": self.texto,
                "opciones": list(self.opciones), "porque": self.porque}


@dataclass
class Encuesta:
    ok: bool = False
    preguntas: list = field(default_factory=list)
    motivo: str = ""
    origen: str = ""        # "modelo" | "semilla" | ""
    modelo: str = ""
    ms: int = 0
    aviso: str = ""

    def a_dict(self) -> dict:
        return {"ok": self.ok, "preguntas": [p.a_dict() for p in self.preguntas],
                "motivo": self.motivo, "origen": self.origen,
                "modelo": self.modelo, "ms": self.ms, "aviso": self.aviso}


# Por debajo de esto un pedido SIN objeto concreto es demasiado vago para que
# "la semilla no encontro huecos" signifique "no faltan datos": significa que
# la tabla de decisiones tipicas no supo de que hablaba. 60 chars son ~10
# palabras: "hazme una pagina web" (20), "organizame el escritorio" (24),
# "quiero ponerme en forma" (23) caen dentro; un pedido de dos frases, no.
LARGO_VAGO = 60

# Que hace CONCRETO a un pedido: nombra una cosa que existe y se puede senalar
# -- un fichero con extension, una ruta, una @-mencion del REPL, una URL, una
# cifra o algo entrecomillado. Ninguna de esas aparece en "hazme una pagina
# web". Es deliberadamente conservador: ante la duda, el pedido cuenta como
# CONCRETO y la puerta 3 sigue cerrando como siempre.
_RE_OBJETO_CONCRETO = re.compile(
    r"[\w-]+\.[a-z0-9]{1,5}\b"          # ventas.csv, cli.py, index.html
    r"|[/\\][\w.-]"                     # una ruta
    r"|(?:^|\s)@\S"                     # @-mencion del REPL
    r"|\d"                              # una cifra
    r"|[" + chr(34) + chr(39) + chr(0x201c) + chr(0x2018) + r"]",  # entrecomillado
    re.I)


def _sin_objeto_concreto(texto: str) -> bool:
    """True si el pedido no nombra ninguna cosa concreta (ver el regex)."""
    return not _RE_OBJETO_CONCRETO.search(texto or "")


def vale_la_pena(texto: str, *, faltantes=None) -> tuple:
    """(bool, motivo). Decide SIN llamar al modelo si merece encuestar.

    Se separa de preparar() para que el CLI pueda descartar el caso comun
    (pedido ya especifico) sin pagar una llamada al backend."""
    t = (texto or "").strip()
    if not t:
        return False, "texto vacio"
    if len(t) > MAX_CHARS_PARA_PREGUNTAR:
        return False, "el pedido ya es largo y especifico"
    if t.startswith("/") or t.startswith("!"):
        return False, "es un comando, no un pedido"
    if faltantes is not None and not faltantes:
        # La semilla deterministica no encontro ningun hueco. Eso admite DOS
        # lecturas opuestas y hasta 2026-08-29 se trataban igual:
        #   (a) el usuario ya tomo todas las decisiones -> no preguntar (bien);
        #   (b) la tabla no sabe de que va el pedido -> no preguntar (mal: es
        #       justo el pedido que MAS necesita la encuesta).
        # Se separan por el propio texto: si es corto Y no nombra ninguna cosa
        # concreta, estamos en (b) y la puerta NO cierra -- se sigue hasta
        # preparar(), donde el modelo (o cero preguntas) decide. Si el pedido
        # nombra un fichero, una ruta o una cifra, estamos en (a) y cierra
        # como siempre.
        if len(t) < LARGO_VAGO and _sin_objeto_concreto(t):
            return True, ""
        return False, "no hay decisiones sin tomar detectables"
    return True, ""


# ---------------------------------------------------------------------------
# Saneado de la salida del modelo. Un JSON del modelo NO es de fiar: puede
# traer diez preguntas, tipos inventados, opciones vacias o una pregunta que
# el contexto ya respondia. Todo eso se corrige aqui, no se confia.
# ---------------------------------------------------------------------------

def _extraer_json(bruto: str) -> dict:
    """El objeto JSON del texto del modelo, o {}."""
    t = (bruto or "").strip()
    # Quitar razonamiento y vallas de codigo, como hace sanear_salida del
    # reformulador: los razonadores emiten <think> aunque se les apague.
    t = re.sub(r"<think>.*?</think>", " ", t, flags=re.S | re.I)
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip(), flags=re.M)
    inicio = t.find("{")
    if inicio < 0:
        return {}
    # Buscar el cierre equilibrado: un rfind('}') se come la basura de detras
    # pero tambien corta mal si el modelo escribio dos objetos.
    hondo = 0
    for i in range(inicio, len(t)):
        if t[i] == "{":
            hondo += 1
        elif t[i] == "}":
            hondo -= 1
            if hondo == 0:
                try:
                    return json.loads(t[inicio:i + 1])
                except Exception:
                    return {}
    return {}


def _slug(texto: str, i: int) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (texto or "").lower()).strip("_")
    return (s[:24] or f"p{i}")


def sanear_preguntas(crudo, *, texto: str = "", contexto: str = "") -> tuple:
    """(lista de Pregunta validas, motivo_si_vacia).

    Rechaza, en este orden: forma invalida, tipo desconocido, texto vacio,
    cerrada sin opciones suficientes, duplicada, y ya-respondida-en-el-texto.
    """
    if not isinstance(crudo, dict):
        return [], "el modelo no devolvio un objeto JSON"
    lista = crudo.get("preguntas")
    if lista is None:
        return [], "el JSON no trae la clave 'preguntas'"
    if not isinstance(lista, list):
        return [], "'preguntas' no es una lista"
    if not lista:
        return [], "el modelo dice que no falta nada"

    heno = _sin_tildes((texto + " " + contexto).lower())
    vistas, out = set(), []
    for i, item in enumerate(lista):
        if len(out) >= MAX_PREGUNTAS:
            break
        if not isinstance(item, dict):
            continue
        cuerpo = str(item.get("texto") or "").strip()
        if not cuerpo or len(cuerpo) > 160:
            continue
        tipo = str(item.get("tipo") or "abierta").strip().lower()
        if tipo not in TIPOS:
            # Un tipo inventado no tira la pregunta: se degrada a abierta,
            # que siempre es contestable. Perder la pregunta seria peor.
            tipo = "abierta"
        opciones = item.get("opciones") or []
        opciones = [str(o).strip() for o in opciones
                    if isinstance(o, (str, int, float)) and str(o).strip()]
        # Duplicados dentro de las opciones (el modelo repite), conservando orden
        opciones = list(dict.fromkeys(opciones))[:MAX_OPCIONES]
        if tipo in ("unica", "multiple") and len(opciones) < 2:
            # Una cerrada con una sola opcion no es una pregunta: es una
            # afirmacion disfrazada. Se convierte en abierta.
            tipo, opciones = "abierta", []
        if tipo == "abierta":
            opciones = []

        clave = _slug(str(item.get("id") or cuerpo), i)
        if clave in vistas:
            continue
        # Ya respondida: si la pregunta pide algo cuyas palabras clave ya
        # estan en el pedido o el contexto, sobra. Umbral 2 para no descartar
        # por una palabra suelta.
        if _ya_respondida(cuerpo, opciones, heno):
            continue
        vistas.add(clave)
        out.append(Pregunta(id=clave, tipo=tipo, texto=cuerpo,
                            opciones=opciones,
                            porque=str(item.get("porque") or "")[:120]))
    if not out:
        return [], "ninguna pregunta paso los filtros"
    return out, ""


_STOP = frozenset("""
que cual cuales como cuando donde quien para por con sin sobre entre desde
hasta el la los las un una unos unas de del al y o u e es son ser va vas
quieres queres tiene tienes debe debes hacer haces prefieres necesitas
""".split())


def _sin_tildes(t: str) -> str:
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
                 ("ü", "u"), ("ñ", "n")):
        t = t.replace(a, b)
    return t


def _palabras(t: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]{4,}", _sin_tildes((t or "").lower()))
            if w not in _STOP}


def _ya_respondida(pregunta: str, opciones: list, heno: str) -> bool:
    """True si el pedido/contexto ya contesta esta pregunta.

    Se mide con las OPCIONES ademas del enunciado: "Con que tecnologia?"
    tiene palabras genericas, pero si una de sus opciones ("React") ya
    aparece en el contexto, la pregunta esta contestada. Es la regla 1 de la
    cabecera, aplicada por si el generador la ignora."""
    for opcion in opciones:
        pal = _palabras(opcion)
        if pal and pal <= _palabras(heno):
            return True
    pal = _palabras(pregunta)
    if not pal:
        return False
    comunes = pal & _palabras(heno)
    return len(comunes) >= 2 and len(comunes) >= len(pal) * 0.6


def _de_la_semilla(faltantes) -> list:
    """Convierte la semilla deterministica de contexto_mejora en Preguntas."""
    out = []
    for f in (faltantes or [])[:MAX_PREGUNTAS]:
        tipo = str(f.get("tipo") or "abierta")
        opciones = list(f.get("opciones") or [])
        if tipo in ("unica", "multiple") and len(opciones) < 2:
            tipo, opciones = "abierta", []
        out.append(Pregunta(id=str(f.get("id") or "p"), tipo=tipo,
                            texto=str(f.get("pregunta") or f.get("texto") or ""),
                            opciones=opciones,
                            porque="decision tipica de este tipo de tarea"))
    return [p for p in out if p.texto]


def preparar(texto: str, *, contexto: str = "", faltantes=None,
             max_preguntas: int = MAX_PREGUNTAS,
             timeout_s: float = TIMEOUT_DEFECTO, url=None,
             generar_fn=None) -> Encuesta:
    """Prepara la encuesta para `texto`. NUNCA lanza.

    Si hay backend, las preguntas las genera el modelo con el contexto
    delante (que es lo que las hace CONTEXTUALES y no un formulario fijo).
    Si no lo hay, o si el modelo falla, se cae a la semilla deterministica de
    `faltantes` -- que sirve OFFLINE y es la razon de que esta funcionalidad
    no dependa de tener el cerebro encendido.
    """
    inicio = time.monotonic()
    registro = {"modelo": ""}
    original = texto if isinstance(texto, str) else ""

    def _cerrar(preguntas, motivo, origen) -> Encuesta:
        return Encuesta(ok=bool(preguntas), preguntas=preguntas or [],
                        motivo=motivo, origen=origen if preguntas else "",
                        modelo=registro.get("modelo", ""),
                        ms=int((time.monotonic() - inicio) * 1000),
                        aviso=registro.get("aviso", ""))

    ok, motivo = vale_la_pena(original, faltantes=faltantes)
    if not ok:
        return _cerrar([], motivo, "")

    semilla = _de_la_semilla(faltantes)[:max_preguntas]

    if generar_fn is None:
        from cognia.harness import mejorar_prompt as _mp
        destino = _mp._detectar_url(url)
        if not destino:
            # Sin backend NO se pierde la funcionalidad: la semilla es peor
            # que el modelo pero es infinitamente mejor que nada, y no
            # depende de que el cerebro este encendido.
            return _cerrar(semilla, _mp._motivo_backend(url) or "sin backend",
                           "semilla")
        generar_fn = _mp._construir_generar(destino, timeout_s, registro)

    partes = []
    if contexto and contexto.strip():
        partes.append("Contexto de la sesion del usuario (uselo para NO "
                      "preguntar lo que ya esta decidido):\n" + contexto.strip())
    if semilla:
        partes.append("Decisiones que suelen faltar en este tipo de tarea "
                      "(usalas como pista, no las copies si no aplican):\n"
                      + "\n".join("- " + p.texto for p in semilla))
    partes.append("Pedido del usuario:\n<<<\n" + original.strip() + "\n>>>")

    try:
        bruto = generar_fn("\n\n".join(partes), _SYSTEM)
    except (TimeoutError, OSError) as exc:
        return _cerrar(semilla, "timeout o red: {}: {}".format(
            type(exc).__name__, exc), "semilla")
    except Exception as exc:
        return _cerrar(semilla, "error: {}: {}".format(
            type(exc).__name__, exc), "semilla")

    if not isinstance(bruto, str):
        # El saneo va FUERA del try (un fallo suyo seria un bug, no una caida
        # del backend), asi que lo que entra tiene que ser texto o aqui se
        # rompe el turno -- justo lo que este modulo promete no hacer. Un
        # generar_fn ajeno puede devolver None o cualquier otra cosa.
        return _cerrar(semilla, "el backend no devolvio texto", "semilla")

    if str(registro.get("finish_reason") or "") == "length":
        # Un JSON cortado por presupuesto no es JSON. Se dice la causa real
        # en vez de "salida invalida", que se diagnostica como otra cosa.
        return _cerrar(semilla, "cortado por presupuesto de tokens "
                                "(max_tokens={})".format(N_PREDICT), "semilla")

    preguntas, motivo_saneo = sanear_preguntas(
        _extraer_json(bruto), texto=original, contexto=contexto)
    preguntas = preguntas[:max_preguntas]
    if not preguntas:
        if motivo_saneo == "el modelo dice que no falta nada":
            # Esto NO es un fallo: es la respuesta correcta a un pedido claro.
            # Y por eso no se cae a la semilla: el modelo, con el contexto
            # delante, sabe mas que una tabla de decisiones tipicas.
            return _cerrar([], motivo_saneo, "")
        return _cerrar(semilla, motivo_saneo, "semilla")
    return _cerrar(preguntas, "ok", "modelo")


# ---------------------------------------------------------------------------
# Incorporacion de las respuestas al prompt
# ---------------------------------------------------------------------------

def incorporar(texto: str, respuestas) -> str:
    """El pedido del usuario con sus respuestas anadidas, listo para enviar.

    `respuestas` es [(Pregunta, valor)] donde valor puede ser str, lista o
    None. Las tres cosas significan cosas distintas y se tratan distinto:
        None  -> la salto: NO aparece (no se le atribuye nada al usuario)
        ""    -> contesto "nada": tampoco aparece
        []    -> eligio ninguna de las opciones: SI aparece, como "ninguna
                 de: a, b, c", porque descartar es informacion util
    Si no queda ninguna respuesta util, se devuelve el texto TAL CUAL: una
    encuesta que nadie contesto no puede ensuciar el pedido.
    """
    base = (texto or "").strip()
    lineas = []
    for pregunta, valor in (respuestas or []):
        etiqueta = getattr(pregunta, "texto", str(pregunta)).rstrip("?:. ")
        if valor is None:
            continue
        if isinstance(valor, (list, tuple, set)):
            valores = [str(v).strip() for v in valor if str(v).strip()]
            if valores:
                lineas.append(f"- {etiqueta}: {', '.join(valores)}")
            else:
                opciones = getattr(pregunta, "opciones", []) or []
                if opciones:
                    lineas.append(f"- {etiqueta}: ninguna de "
                                  f"{', '.join(str(o) for o in opciones)}")
            continue
        v = str(valor).strip()
        if v:
            lineas.append(f"- {etiqueta}: {v}")
    if not lineas:
        return base
    return base + "\n\nDetalles que el usuario aclaro:\n" + "\n".join(lineas)


# ---------------------------------------------------------------------------
# API para quien cablea (cognia/cli.py). Todo lo de abajo es AZUCAR sobre lo
# de arriba: no anade estado, no lee config, no imprime y no llama al selector.
# Existe para que el cableado no tenga que reconstruir las reglas -- que puertas
# hay, en que orden, y con que funcion del selector se muestra cada pregunta --
# ni tenga que repetirlas en las cuatro vias del CLI que llaman al mejorador
# ('auto', 'preguntar', F3 y '/mejorar <texto>'), que es como se desincronizan.
# ---------------------------------------------------------------------------

# Valor centinela de la opcion "Otra cosa..." que se anade al final de toda
# pregunta cerrada. Vive aqui y no en el CLI porque es parte del contrato: un
# selector que devuelve este valor NO devolvio una respuesta del usuario, hay
# que preguntarle en texto libre.
OTRA_OPCION = "__otra__"

# Que funcion de cognia/ux/selector.py muestra cada tipo de pregunta.
SELECTOR_POR_TIPO = {
    "unica": "elegir",
    "multiple": "elegir_varias",
    "abierta": "texto_libre",
}

# Motivos de `Encuesta.motivo` que NO son degradacion: son la respuesta
# CORRECTA a un pedido que no necesita encuesta. Quien cablea no debe gritarlos
# por _aviso_degradado (si lo hace, el dueno ve un "degradado" cada vez que
# escribe algo claro y acaba apagando la funcionalidad). Todo lo demas SI es
# degradacion y tiene que verse.
MOTIVOS_NORMALES = (
    "",
    "ok",
    "el modelo dice que no falta nada",
    "no hay decisiones sin tomar detectables",
    "el pedido ya es largo y especifico",
    "es un comando, no un pedido",
    "texto vacio",
    "encuestas apagadas",
    "sin terminal interactiva",
)


def es_degradacion(motivo: str) -> bool:
    """True si `motivo` es un FALLO que hay que gritar, no una decision."""
    return str(motivo or "").strip() not in MOTIVOS_NORMALES


def como_preguntar(pregunta) -> dict:
    """Como se muestra UNA pregunta con cognia/ux/selector.py.

    Devuelve un dict listo para usar, sin adivinar:
        {"funcion": "elegir" | "elegir_varias" | "texto_libre",
         "titulo": str,                  # ya lleva el 'porque' entre parentesis
         "opciones": [(valor, etiqueta, descripcion), ...],   # [] si abierta
         "pista": str,                   # solo para texto_libre
         "valor_otra": str}              # OTRA_OPCION, o "" si no aplica

    "Otra cosa..." va SIEMPRE al final de una pregunta cerrada: unas opciones
    que el modelo creyo exhaustivas casi nunca lo son, y sin salida el usuario
    tiene que elegir algo que no queria o cancelar la encuesta entera. Si el
    selector devuelve `valor_otra`, hay que preguntar en texto libre.
    """
    texto = getattr(pregunta, "texto", "") or ""
    porque = getattr(pregunta, "porque", "") or ""
    tipo = getattr(pregunta, "tipo", "abierta")
    opciones = list(getattr(pregunta, "opciones", []) or [])
    titulo = texto + ("   ({})".format(porque) if porque else "")
    funcion = SELECTOR_POR_TIPO.get(tipo, "texto_libre")
    if funcion == "texto_libre":
        return {"funcion": funcion, "titulo": titulo, "opciones": [],
                "pista": "Enter para saltar", "valor_otra": ""}
    caja = [(o, o, "") for o in opciones]
    valor_otra = ""
    if funcion == "elegir":
        valor_otra = OTRA_OPCION
        caja.append((OTRA_OPCION, "Otra cosa...", "lo escribo yo"))
    return {"funcion": funcion, "titulo": titulo, "opciones": caja,
            "pista": "", "valor_otra": valor_otra}


def encuesta_para(texto: str, *, contexto: str = "", faltantes=None,
                  estado: str = "auto", hay_tty: bool = True,
                  max_preguntas: int = MAX_PREGUNTAS,
                  timeout_s: float = TIMEOUT_DEFECTO, url=None,
                  generar_fn=None) -> Encuesta:
    """LA funcion que debe llamar el CLI. Todas las puertas, en orden, NUNCA
    lanza, y siempre devuelve una `Encuesta` (nunca None).

    Puertas, de la mas barata a la mas cara:
      1. `estado` != "auto"  -> motivo "encuestas apagadas"
      2. `hay_tty` False     -> motivo "sin terminal interactiva"
      3. `vale_la_pena`      -> su motivo
      4. `preparar`          -> modelo, o semilla deterministica sin backend

    El modulo sigue siendo PURO: `estado` y `hay_tty` se PASAN, no se leen
    (la config vive en el CLI y el tty lo sabe cognia/ux/selector.hay_tty()).
    Uso previsto en cli.py:

        enc = encuesta.encuesta_para(
            raw, contexto=ctx.bloque, faltantes=ctx.faltantes,
            estado=_estado_encuestas(), hay_tty=_selector.hay_tty())
        if not enc.ok:
            if encuesta.es_degradacion(enc.motivo):
                _aviso_degradado("cli.encuesta", enc.motivo)
            return raw                      # se sigue con el texto crudo
        ...  # mostrar con como_preguntar(p), recoger, y:
        enriquecido = encuesta.incorporar(raw, respuestas)

    Y despues, para reformular ese texto ya enriquecido:
        mejorar_prompt.mejorar(enriquecido, version=mejorar_prompt.version_para(
            estado, encuesta_previa=True, estilo=estilo), encuesta_previa=True)
    """
    if str(estado or "").strip().lower() != "auto":
        return Encuesta(ok=False, motivo="encuestas apagadas")
    if not hay_tty:
        # No es un fallo: es que este camino no aplica (pipes, CI, e2e).
        return Encuesta(ok=False, motivo="sin terminal interactiva")
    try:
        return preparar(texto, contexto=contexto, faltantes=faltantes,
                        max_preguntas=max_preguntas, timeout_s=timeout_s,
                        url=url, generar_fn=generar_fn)
    except Exception as exc:
        # preparar() promete no lanzar; si lanza es un bug y tiene que VERSE
        # (el motivo es degradacion), pero jamas puede romper el turno.
        return Encuesta(ok=False, motivo="error preparando la encuesta: "
                                         "{}: {}".format(type(exc).__name__, exc))
