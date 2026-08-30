# -*- coding: utf-8 -*-
"""
cognia/harness/contexto_mejora.py
=================================
El CONTEXTO que se le pasa al mejorador de prompts. Modulo PURO.

POR QUE EXISTE (2026-08-28)
---------------------------
`mejorar_prompt.mejorar()` acepta un parametro `contexto` desde que se
escribio... y NINGUN caller de produccion se lo pasaba: el unico sitio que lo
ejercita es un test. O sea, el reformulador veia UNICAMENTE la linea tecleada.
Con eso puede arreglar la redaccion, pero no puede saber que el dueno ya tiene
un programa que hace casi eso, que hay una receta que lo resuelve en cuatro
pasos, o que hace dos turnos dijo "en espanol y sin dependencias".

Este modulo reune ese contexto. No llama al modelo: es recoleccion y recorte,
y corre ENTRE el Enter del usuario y el envio, asi que cada proveedor tiene
presupuesto de tiempo y el conjunto tiene presupuesto de caracteres.

LA REGLA QUE MANDA SOBRE TODAS
------------------------------
"Maxima especificidad util, no maxima cantidad de texto." Un contexto largo
es peor que uno corto por dos motivos MEDIBLES, no esteticos:
  1. `mejorar()` corta el contexto por caracteres. Lo que sobra no se recorta
     por relevancia sino por posicion: la ultima seccion desaparece entera.
  2. Cuanto mas texto no pedido entra, mas facil es que el reformulador lo
     confunda con requisitos -- que es EXACTAMENTE la falla que el modulo
     tiene prohibida ("no inventar requisitos que el usuario no dijo").
Por eso cada seccion tiene que GANARSE el sitio: se incluye si supera un
umbral de relevancia contra el texto del usuario, no por estar disponible.

CONTRATO
--------
- PURO: no importa cognia.cli, no imprime, no persiste, nunca lanza.
- Cada proveedor que falla suma un aviso legible y devuelve vacio. Un
  proveedor caido NO puede verse igual que un proveedor sin resultados:
  `secciones` distingue "no hay" de "no se pudo".
- NINGUNA SECCION DESAPARECE SIN RASTRO. Para cada nombre que se pide hay
  siempre una respuesta a "que paso con esta seccion", y `estado_de()` la
  devuelve en una palabra. Las cinco vias son excluyentes y estan todas
  pobladas: `secciones` (llego texto), `vacias` (contesto y no habia nada),
  `recortadas` (no se pidio, o se pidio y no cupo), `fallidas`+`avisos`
  (exploto). Hasta 2026-08-29 esto era falso: un `if valor:` tiraba en
  silencio a todo proveedor que devolviera "" -- medido, 5 de los 8
  (conversacion, artefactos, recetas, skills, rag) se esfumaban sin entrar
  en ninguna lista. El propio modulo lo tiene prohibido: "un contexto
  incompleto en silencio es indistinguible de un contexto vacio".
- Todo es inyectable (`proveedores=`) para poder testear sin disco ni DB.
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Contexto", "reunir", "tipo_de_tarea", "faltantes_por_tipo",
           "PRESUPUESTO_CHARS", "SECCIONES"]

# Presupuesto TOTAL del bloque de contexto, en caracteres.
#
# El numero sale de una cuenta, no de un gusto. `mejorar()` recorta el
# contexto a MAX_CHARS_CONTEXTO y el bloque tiene que caber entero ahi o la
# ultima seccion se pierde en silencio. Medido sobre sesiones reales de esta
# maquina, un bloque con las cinco secciones que suelen activarse ocupa
# 900-1.600 chars. 1.800 deja margen para la sexta sin que el prompt del
# reformulador (que ya lleva su system de ~2.000 chars) se vaya de tamano.
PRESUPUESTO_CHARS = 1800

# Orden de PRIORIDAD. Es tambien el orden en que se recorta: la ultima
# seccion es la primera en caer cuando no cabe. Va primero lo que desambigua
# el pedido (donde estoy, que dijimos) y despues lo que lo enriquece.
SECCIONES = ("entorno", "conversacion", "restricciones", "artefactos",
             "recetas", "skills", "memorias", "rag")

# Presupuesto de TIEMPO por proveedor. Esto corre entre el Enter y el envio:
# un proveedor lento no puede congelar el turno. Se mide despues de llamar
# (no se puede interrumpir una funcion sincrona sin hilos), asi que lo que
# hace el tope es DEJAR DE PEDIR mas secciones cuando ya se gasto el total.
PRESUPUESTO_MS_TOTAL = 1200


@dataclass
class Contexto:
    bloque: str = ""
    secciones: dict = field(default_factory=dict)
    faltantes: list = field(default_factory=list)
    tipo_tarea: str = "otro"
    avisos: list = field(default_factory=list)
    ms: int = 0
    chars: int = 0
    recortadas: list = field(default_factory=list)
    # Secciones que se pidieron, contestaron y no tenian nada que decir. Es
    # "no hay", no "no se pudo": sin error y sin aviso. Existe porque sin
    # ella esas secciones no aparecian en NINGUNA lista y quedaban
    # indistinguibles de las que nunca se pidieron.
    vacias: list = field(default_factory=list)
    # Secciones cuyo proveedor lanzo. El texto del fallo va en `avisos`;
    # aqui va el nombre pelado, para poder preguntarlo sin parsear prosa.
    fallidas: list = field(default_factory=list)

    def a_dict(self) -> dict:
        return {"bloque": self.bloque, "secciones": dict(self.secciones),
                "faltantes": list(self.faltantes), "tipo_tarea": self.tipo_tarea,
                "avisos": list(self.avisos), "ms": self.ms, "chars": self.chars,
                "recortadas": list(self.recortadas), "vacias": list(self.vacias),
                "fallidas": list(self.fallidas)}

    def estado_de(self, nombre: str) -> str:
        """Que paso con esta seccion, en una palabra. SIEMPRE contesta.

        Este metodo es el contrato de "ninguna seccion desaparece": para
        cualquiera de los 8 nombres devuelve uno de estos seis estados, y
        solo el ultimo significa "ni se intento".

          incluida   -> tiene texto y ese texto esta en el bloque
          sin_sitio  -> tiene texto pero no cabia en el presupuesto de chars
          sin_datos  -> se pidio, contesto, y no habia nada que decir
          no_pedida  -> no se llego a pedir (presupuesto de tiempo, o cara
                        en frio y todavia calentando)
          fallo      -> el proveedor lanzo; el detalle esta en `avisos`
          fuera_de_lista -> no estaba entre las secciones pedidas
        """
        if nombre in self.fallidas:
            return "fallo"
        if nombre in self.secciones:
            return "sin_sitio" if nombre in self.recortadas else "incluida"
        if nombre in self.vacias:
            return "sin_datos"
        if nombre in self.recortadas:
            return "no_pedida"
        return "fuera_de_lista"


# ---------------------------------------------------------------------------
# Tipo de tarea. Deterministico y por palabras: NO se llama al modelo para
# esto. Clasificar con el modelo costaria otra ida y vuelta justo en el
# momento mas sensible del turno, y con peor latencia que acierto.
# ---------------------------------------------------------------------------

# ORDEN = quien gana los EMPATES, y va de MAS a MENOS especifico.
#
# No es cosmetico. "analiza el csv de ventas" daba 'investigacion': 'analiza'
# (investigacion) y 'csv' (datos) pesan 1,0 cada una, empataban, y el empate
# lo rompia el orden -- que estaba puesto por frecuencia, no por especificidad.
# Una categoria que exige un objeto concreto (un fichero, un dataset, una
# ruta) es una apuesta mas segura ante un empate que una categoria amplia
# como 'codigo', que casa con media conversacion de este repo.
_SENALES_TIPO = (
("datos", (
        "dataset", "csv", "excel", "tabla", "grafico", "estadistica", "media",
        "correlacion", "modelo", "entrenar", "prediccion", "datos")),
("accion", (
        "borra", "mueve", "copia", "renombra", "organiza", "ordena", "limpia",
        "abre", "cierra", "ejecuta", "corre", "lanza", "arranca",
        "deten", "detene", "detener")),
("escritura", (
        "escribe", "redacta", "correo", "email", "carta", "articulo", "post",
        "ensayo", "resumen", "resume", "traduce", "corrige", "guion",
        "informe", "documento", "texto", "titulo", "descripcion")),
("investigacion", (
        "investiga", "busca", "compara", "analiza", "averigua", "explica",
        "por que", "como funciona", "diferencia", "ventajas", "estado del arte",
        "fuentes", "documentacion")),
("codigo", (
        "codigo", "funcion", "clase", "script", "bug", "error", "test",
        "refactor", "compilar", "api", "endpoint", "sql", "query", "libreria",
        "modulo", "python", "javascript", "html", "css", "react", "repo",
        "commit", "programa", "app", "aplicacion", "web", "pagina", "juego",
        "instalar", "dependencia", "servidor", "base de datos")),
)


def _norm(texto: str) -> str:
    """Minusculas sin tildes, para que 'analiza' case con 'analizá'."""
    t = (texto or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
                 ("ü", "u"), ("ñ", "n")):
        t = t.replace(a, b)
    return t


_RE_SENAL = {}


def _casa(palabra: str, texto: str) -> bool:
    """La senal aparece como PALABRA, no como trozo de otra.

    Con `in` a secas, "para" casaba dentro de "comPARA react y vue" y dentro
    de "escribe un correo PARA pedir un aumento": las dos frases salian
    clasificadas como 'accion'. El limite de palabra lo arregla de raiz, y de
    paso deja de contar "test" dentro de "contexto" o "web" dentro de
    "webhook". El regex se cachea porque esto corre en el camino caliente.
    """
    if not palabra:
        return False
    rx = _RE_SENAL.get(palabra)
    if rx is None:
        # El limite se exige SOLO del lado que empieza (o acaba) en
        # alfanumerico. Pedirlo por los cuatro costados mataba las senales que
        # son extension o comodin: ".csv" no casaba en "ventas.csv" (lo
        # bloqueaba la 's' de antes) ni "*." en "*.tmp", asi que a quien ya
        # habia dicho su fichero se le preguntaba igual "Donde estan los
        # datos?" -- justo la encuesta invasiva que el modulo tiene prohibida.
        izq = r"(?<![a-z0-9])" if palabra[:1].isalnum() else ""
        der = r"(?![a-z0-9])" if palabra[-1:].isalnum() else ""
        rx = re.compile(izq + re.escape(palabra) + der)
        _RE_SENAL[palabra] = rx
    return bool(rx.search(texto))


def _peso_senal(palabra: str) -> float:
    """Cuanto vale una senal. Las que aparecen en VARIAS categorias valen
    menos, porque no distinguen.

    Sin esto, "analiza el csv de ventas" salia 'investigacion': 'analiza'
    (que esta en investigacion) y 'csv' (que solo esta en datos) valian
    igual, empataban a 1, y el empate lo rompia el ORDEN de la tabla. Una
    palabra que solo pertenece a una categoria es evidencia mucho mas fuerte
    que un verbo generico que sirve para todo.
    """
    veces = sum(1 for _n, palabras in _SENALES_TIPO if palabra in palabras)
    base = 1.0 if veces <= 1 else 0.5
    # Una senal de dos palabras ("base de datos", "estado del arte") casa por
    # accidente mucho menos que una de cinco letras: vale mas.
    return base * (1.4 if " " in palabra else 1.0)


def tipo_de_tarea(texto: str) -> str:
    """'codigo'|'escritura'|'investigacion'|'datos'|'accion'|'otro'.

    Gana el tipo con mas PESO de senales (no con mas senales a secas: ver
    _peso_senal). Si empatan gana el que aparece antes en _SENALES_TIPO.
    """
    t = _norm(texto)
    mejor, mejor_p = "otro", 0.0
    for nombre, palabras in _SENALES_TIPO:
        p = sum(_peso_senal(w) for w in palabras if _casa(w, t))
        if p > mejor_p:
            mejor, mejor_p = nombre, p
    return mejor


# Decisiones que suelen FALTAR por tipo de tarea, con la senal que indica que
# el usuario ya la tomo. Es la semilla deterministica de la encuesta: sirve
# cuando no hay backend para generar preguntas, y le da al generador una
# lista de partida en vez de dejarlo inventar de cero.
#
# Cada entrada: (id, pregunta, tipo_respuesta, opciones, palabras_que_lo_cubren)
_FALTANTES = {
    "codigo": [
        ("proposito", "Para que va a servir?", "abierta", (),
         ("para ", "porque", "necesito", "quiero que", "sirve")),
        ("stack", "Con que tecnologia?", "unica",
         ("HTML/CSS/JS sin frameworks", "React", "Python", "Me da igual, elegi vos"),
         ("html", "css", "javascript", "js", "react", "vue", "python", "node",
          "django", "flask", "sin framework", "vanilla")),
        ("alcance", "Que tiene que hacer, como minimo?", "abierta", (),
         ("tiene que", "debe ", "que haga", "funcionalidad", "requisito")),
        ("destino", "Donde va a correr?", "unica",
         ("En mi maquina", "En un servidor", "En el navegador", "Todavia no lo se"),
         ("local", "servidor", "navegador", "docker", "nube", "movil")),
    ],
    "escritura": [
        ("audiencia", "Para quien es?", "abierta", (),
         ("para ", "dirigido", "lectores", "publico", "cliente", "jefe")),
        ("tono", "Que tono?", "unica",
         ("Formal", "Neutro", "Cercano", "Tecnico"),
         ("formal", "informal", "serio", "cercano", "tecnico", "divulgativo",
          "tono")),
        ("largo", "Que largo?", "unica",
         ("Un parrafo", "Media pagina", "Una pagina", "Todo lo que haga falta"),
         ("palabras", "parrafo", "pagina", "corto", "largo", "breve")),
    ],
    "investigacion": [
        ("profundidad", "Cuanta profundidad?", "unica",
         ("Respuesta corta", "Explicacion con ejemplos", "Analisis a fondo con fuentes"),
         ("resumen", "corto", "a fondo", "detalle", "profundo", "fuentes")),
        ("uso", "Para que lo vas a usar?", "abierta", (),
         ("para ", "necesito", "decidir", "presentar", "aprender")),
    ],
    "datos": [
        ("fuente", "Donde estan los datos?", "abierta", (),
         (".csv", ".xlsx", "carpeta", "ruta", "base de datos", "fichero",
          "archivo")),
        ("pregunta", "Que pregunta le queres hacer a los datos?", "abierta", (),
         ("cuanto", "cual", "por que", "relacion", "tendencia", "predecir")),
    ],
    "accion": [
        ("alcance_accion", "Sobre que ficheros exactamente?", "abierta", (),
         ("carpeta", "directorio", "ruta", "todos los", "*.", "fichero",
          "archivo")),
    ],
    # 'otro' NO puede quedar vacio. Era [] hasta 2026-08-29 y ese vacio APAGABA
    # la encuesta entera: tipo_de_tarea() devuelve 'otro' para todo lo que no
    # case con su tabla de palabras, faltantes queda [] y la puerta 3 de
    # encuesta.vale_la_pena cierra con "no hay decisiones sin tomar
    # detectables". Medido sobre 21 pedidos cortos tipicos del dueno:
    # 'ayudame con el proyecto', 'construime un bot', 'programame una
    # calculadora', 'disename un logo' y 'quiero ponerme en forma' salian todos
    # tipo='otro' -> 0 faltantes -> 0 preguntas. Y 'quiero ponerme en forma' es
    # el EJEMPLO 1 del propio system del reformulador: el sistema lo resolvia
    # metiendole preguntas al prompt entregado en vez de preguntarlas.
    #
    # Los tres huecos son GENERICOS a proposito: no saben de que trata el
    # pedido (por eso cayo en 'otro'), asi que preguntan lo unico que aplica a
    # cualquier tarea -- para que es, en que forma se quiere el resultado y
    # hasta donde llega. Son la SEMILLA offline; con backend el modelo los usa
    # como pista y suele hacer preguntas mejores.
    "otro": [
        ("proposito", "Para que va a servir?", "abierta", (),
         ("para ", "porque", "necesito", "quiero que", "sirve", "me sirve")),
        ("formato_salida", "Como queres el resultado?", "unica",
         ("Un texto corrido", "Una lista de pasos", "Una tabla",
          "Un fichero o codigo", "Me da igual, elegi vos"),
         ("lista", "tabla", "pasos", "resumen", "correo", "informe",
          "documento", "fichero", "archivo", "script", "codigo", "grafico")),
        ("alcance", "Que tiene que incluir, como minimo?", "abierta", (),
         ("tiene que", "debe ", "que haga", "incluya", "incluye", "minimo",
          "requisito", "al menos")),
    ],
}


def faltantes_por_tipo(texto: str, tipo: str = "", *, contexto: str = "") -> list:
    """Las decisiones del tipo de tarea que el texto (y el contexto) NO cubren.

    Se mira tambien el contexto a proposito: si hace tres turnos el usuario
    dijo "en Python", preguntarle otra vez por el stack es exactamente la
    clase de encuesta invasiva que la mision prohibe.

    QUE PONER EN `contexto`: solo lo que el USUARIO dijo -- sus ultimos turnos.
    NO el bloque entero de reunir(). Una senal de cobertura ("python",
    "fichero", "servidor") que aparece en el listado de ficheros del proyecto
    no es una decision del usuario, y contarla como tal borra el hueco y apaga
    la encuesta. reunir() ya pasa solo la seccion 'conversacion'; ver el
    comentario en su cola.
    """
    tipo = tipo or tipo_de_tarea(texto)
    heno = _norm(texto + " " + (contexto or ""))
    out = []
    for clave, pregunta, forma, opciones, senales in _FALTANTES.get(tipo, ()):
        if any(_casa(s.strip(), heno) for s in senales):
            continue
        out.append({"id": clave, "pregunta": pregunta, "tipo": forma,
                    "opciones": list(opciones)})
    return out


# ---------------------------------------------------------------------------
# Proveedores. Cada uno: (texto_usuario, estado) -> str (vacio = no hay nada).
# Ninguno lanza hacia afuera: reunir() los envuelve.
# ---------------------------------------------------------------------------

def _prov_entorno(texto: str, st: dict) -> str:
    cwd = st.get("cwd") or os.getcwd()
    p = Path(cwd)
    pistas = []
    # Que TIPO de proyecto es, por marcadores de fichero. Barato y fiable:
    # nada de adivinar por el nombre de la carpeta.
    marcas = (("pyproject.toml", "proyecto Python"),
              ("package.json", "proyecto Node/JS"),
              ("Cargo.toml", "proyecto Rust"),
              ("go.mod", "proyecto Go"),
              ("pom.xml", "proyecto Java/Maven"),
              ("index.html", "sitio web estatico"))
    try:
        for fichero, etiqueta in marcas:
            if (p / fichero).exists():
                pistas.append(etiqueta)
    except Exception:
        pass
    linea = f"trabajando en {p.name or cwd}"
    if pistas:
        linea += " (" + ", ".join(pistas[:2]) + ")"
    return linea


def _prov_conversacion(texto: str, st: dict) -> str:
    """Los ultimos turnos, MUY recortados. Solo lo que desambigua."""
    hist = st.get("historial") or []
    if not hist:
        return ""
    utiles = []
    for turno in list(hist)[-6:]:
        rol = str(turno.get("role") or "")
        cont = str(turno.get("content") or "").strip()
        if not cont or rol not in ("user", "assistant"):
            continue
        cont = re.sub(r"\s+", " ", cont)
        # Del asistente solo la primera frase: lo que importa del turno
        # anterior es DE QUE se hablaba, no la respuesta entera.
        limite = 160 if rol == "user" else 110
        utiles.append(("tu" if rol == "user" else "yo") + ": " + cont[:limite])
    if not utiles:
        return ""
    return "\n".join(utiles[-4:])


def _prov_restricciones(texto: str, st: dict) -> str:
    """Preferencias declaradas del usuario (idioma, verbosidad, lo que sea que
    el perfil haya aprendido). Son las restricciones que el reformulador NO
    puede inventarse pero SI puede respetar."""
    from cognia.config import DB_PATH
    from storage.db_pool import db_connect_pooled
    interesantes = ("idioma", "language", "verbosidad", "nombre", "estilo",
                    "preferencia", "restriccion")
    partes = []
    with db_connect_pooled(str(DB_PATH)) as conn:
        for clave, valor in conn.execute(
                "SELECT key, value FROM user_profile ORDER BY updated_at DESC "
                "LIMIT 30").fetchall():
            k = str(clave or "").lower()
            if any(i in k for i in interesantes) and valor:
                partes.append(f"{clave}={str(valor)[:60]}")
    return "; ".join(partes[:6])


def _prov_artefactos(texto: str, st: dict) -> str:
    """Artefactos que YA existen y se parecen a lo que se pide.

    minimo=2 y no 1: con una sola palabra en comun entraria cualquier cosa, y
    meter artefactos irrelevantes es justo lo que la mision prohibe.
    """
    from cognia.memory import catalogo as _cat
    cat = st.get("catalogo")
    if cat is None:
        cat = _cat.construir(familias=("programa", "documento"))
        st["catalogo"] = cat
    filas = _cat.buscar(cat, texto, tope=3, minimo=2,
                        familias=("programa", "documento"))
    if not filas:
        return ""
    return "\n".join(f"- {f.titulo}: {f.resumen[:90]}" for f in filas)


def _prov_recetas(texto: str, st: dict) -> str:
    """Flujos aprendidos que resuelven algo parecido. Es la seccion con mas
    valor practico: si ya hay una receta, el prompt bueno es 'usa la receta
    X', no una especificacion de cero."""
    from cognia.memory import catalogo as _cat
    cat = st.get("catalogo_flujos")
    if cat is None:
        cat = _cat.construir(familias=("flujo",))
        st["catalogo_flujos"] = cat
    filas = _cat.buscar(cat, texto, tope=2, minimo=2)
    if not filas:
        return ""
    return "\n".join(f"- receta '{f.id}': {f.resumen[:90]}" for f in filas)


def _prov_skills(texto: str, st: dict) -> str:
    from cognia.agent import skills as _sk
    todas = _sk.load_skills() or {}
    if not todas:
        return ""
    # semantic_fallback=False A PROPOSITO: el fallback carga
    # sentence-transformers y MEDIDO aqui cuesta 8,01 s. Esto corre entre el
    # Enter del usuario y el envio al modelo; ocho segundos de espera por una
    # linea de contexto opcional es un mal negocio evidente. El solapamiento
    # lexico tarda milisegundos y es el que acierta en los pedidos normales.
    spec = _sk.find_skill(texto, todas, semantic_fallback=False)
    if spec is None:
        return ""
    nombre = getattr(spec, "name", "")
    desc = str(getattr(spec, "description", ""))[:90]
    return f"- skill '{nombre}': {desc}" if nombre else ""


def _prov_memorias(texto: str, st: dict) -> str:
    from cognia.config import DB_PATH
    from cognia.memory.semantic_search import SemanticMemorySearch
    buscador = SemanticMemorySearch(str(DB_PATH))
    hits = buscador.search(texto, limit=2) or []
    partes = []
    for h in hits:
        d = h if isinstance(h, dict) else getattr(h, "__dict__", {})
        cont = str(d.get("content") or d.get("observation") or "").strip()
        if cont and not cont.startswith("["):
            partes.append("- " + re.sub(r"\s+", " ", cont)[:110])
    return "\n".join(partes)


def _prov_rag(texto: str, st: dict) -> str:
    """Trozos indexados del proyecto que el mapa de contexto considera
    relevantes. Se pide POCO presupuesto: aqui solo hace falta saber QUE
    ficheros son relevantes, no su contenido."""
    from cognia.context.context_map import ContextMap
    from cognia.vectors import text_to_vector
    cm = ContextMap()
    trozos = cm.query_text(texto, text_to_vector, budget_tokens=300, top_k=4) or []
    refs = []
    for t in trozos:
        d = t if isinstance(t, dict) else getattr(t, "__dict__", {})
        ref = str(d.get("source_ref") or "")
        if ref and ref not in refs:
            refs.append(ref)
    if not refs:
        return ""
    return "indexado y relevante: " + ", ".join(Path(r).name for r in refs[:4])


# Proveedores CAROS la PRIMERA vez que se usan en el proceso. Medido aqui:
# `rag` tarda 7,41 s en la primera llamada (monta el indice del mapa de
# contexto) y 0,00 s en la segunda y la tercera. No es un coste por llamada:
# es un arranque.
#
# Que se hace con eso: en la primera mejora del REPL NO se pide, y se lanza un
# calentamiento en segundo plano; de la segunda en adelante ya esta caliente y
# entra gratis. Asi el dueno no paga siete segundos de espera justo cuando
# acaba de dar al Enter, y tampoco pierde la seccion para siempre.
#
# La alternativa que se descarto: bajar el presupuesto y confiar en que el
# tope lo salte. No sirve — el tope se comprueba ANTES de llamar, y cuando le
# toca a `rag` solo se llevan gastados 0,2 s, asi que lo llamaria igual y los
# siete segundos ya estarian pagados cuando el tope se entera.
CAROS_EN_FRIO = frozenset({"rag"})

# Coste medido POR PROCESO. Una vez que un proveedor caro demuestra ser
# barato, deja de saltarse.
#
# ESTOS DOS GLOBALES LOS ESCRIBEN DOS HILOS: el del turno (que anota lo que
# tardo cada proveedor) y el de calentamiento (que anota lo que tardo la
# segunda llamada del arranque). Y `_COSTE_MS` no es un cache cualquiera: es
# la UNICA puerta que decide si `rag` se pide o se recorta, asi que leerlo
# suelto hace que el resultado del turno dependa de quien gane la carrera.
#
# Reproducido antes del arreglo (revision de ciclo de vida, 2026-08-29):
#   1a llamada: recortadas=['rag'], arranca el hilo de calentamiento
#   +50 ms:     el hilo escribe _COSTE_MS['rag'] = 0
#   2a llamada: 'rag' no esta ni en secciones ni en recortadas -> DESAPARECIO
# El segundo bug (el `if valor:` que tiraba los vacios) es el que convertia
# la carrera en una desaparicion; el lock es lo que hace que la lectura sea
# coherente. Con los dos arreglados el turno ya no depende de quien gane:
# gane quien gane, `rag` consta -- 'no_pedida' si el hilo aun no termino,
# 'sin_datos' o 'incluida' si ya esta caliente.
_COSTE_LOCK = threading.Lock()
_COSTE_MS = {}
_CALENTANDO = set()


def _anotar_coste(nombre: str, ms: int) -> None:
    with _COSTE_LOCK:
        _COSTE_MS[nombre] = ms


def _costes_ahora() -> dict:
    """Copia coherente de los costes, para decidir el turno ENTERO con la
    misma foto. Sin esto, dos secciones de la MISMA llamada podian ver
    estados distintos del mundo segun donde cayera la escritura del hilo."""
    with _COSTE_LOCK:
        return dict(_COSTE_MS)


def _calentar_en_fondo(nombre: str, fn) -> None:
    """Dispara el arranque caro en un hilo suelto, una sola vez por proceso.

    daemon=True: si el usuario cierra el REPL mientras esto calienta, el
    proceso muere igual. Un hilo de fondo no puede retrasar una salida.

    El alta en `_CALENTANDO` va DENTRO del lock y es un test-and-set: dos
    turnos seguidos (o dos hilos) no pueden arrancar dos calentamientos del
    mismo proveedor, que es pagar dos veces los 7,4 s del arranque."""
    with _COSTE_LOCK:
        if nombre in _CALENTANDO:
            return
        _CALENTANDO.add(nombre)

    def _tarea():
        try:
            fn("calentamiento del indice de contexto", {})   # paga el arranque
            inicio = time.monotonic()
            fn("segunda llamada para medir en caliente", {})
        except Exception:
            # Un calentamiento que falla no tiene a quien avisar y no rompe
            # nada: la proxima llamada real registrara el fallo con su aviso.
            return
        # Se registra el coste de la SEGUNDA llamada, no de la primera. La
        # primera incluye el arranque (7,4 s medidos), y anotar ese numero
        # dejaba al proveedor descalificado para siempre: se calentaba y
        # despues nunca se usaba, que es el peor de los dos mundos.
        _anotar_coste(nombre, int((time.monotonic() - inicio) * 1000))

    threading.Thread(target=_tarea, daemon=True,
                     name=f"cognia-calienta-{nombre}").start()


_PROVEEDORES = {
    "entorno": _prov_entorno,
    "conversacion": _prov_conversacion,
    "restricciones": _prov_restricciones,
    "artefactos": _prov_artefactos,
    "recetas": _prov_recetas,
    "skills": _prov_skills,
    "memorias": _prov_memorias,
    "rag": _prov_rag,
}

# Como se titula cada seccion dentro del bloque. El titulo importa: le dice
# al reformulador QUE ES cada cosa, y en particular que los artefactos y las
# recetas son cosas que ya existen, no cosas que le esten pidiendo hacer.
_TITULOS = {
    "entorno": "Donde",
    "conversacion": "Ultimos turnos",
    "restricciones": "Preferencias ya declaradas por el usuario",
    "artefactos": "Ya existe algo parecido",
    "recetas": "Hay recetas que resuelven algo asi",
    "skills": "Skill aplicable",
    "memorias": "De sesiones anteriores",
    "rag": "Ficheros del proyecto",
}


def reunir(texto: str, *, historial=None, cwd: str = "",
           presupuesto_chars: int = PRESUPUESTO_CHARS,
           secciones=None, proveedores=None,
           presupuesto_ms: int = PRESUPUESTO_MS_TOTAL,
           permitir_caros: bool = False) -> Contexto:
    """Reune el contexto de la sesion para `texto`. NUNCA lanza.

    `proveedores` permite inyectar {nombre: fn} en los tests. `secciones`
    limita cuales se piden (util para el modo rapido).

    De cada seccion pedida queda constancia SIEMPRE, en una de cinco vias
    excluyentes: `secciones`, `vacias`, `recortadas`, `fallidas`/`avisos`.
    `ctx.estado_de(nombre)` las resume en una palabra.
    """
    inicio = time.monotonic()
    ctx = Contexto(tipo_tarea=tipo_de_tarea(texto))
    fuentes = dict(_PROVEEDORES)
    if proveedores:
        fuentes.update(proveedores)
    pedidas = list(secciones or SECCIONES)
    # Un nombre pedido SIN proveedor tampoco puede evaporarse: antes se caia
    # del filtro y no aparecia en ningun sitio, asi que un error de tecleo en
    # `secciones=` se veia igual que una seccion sin datos.
    for nombre in pedidas:
        if nombre not in fuentes:
            ctx.avisos.append("{}: sin proveedor registrado".format(nombre))
            ctx.fallidas.append(nombre)
    pedidas = [s for s in pedidas if s in fuentes]
    estado = {"historial": historial, "cwd": cwd}
    # Foto UNICA de los costes para todo el turno: ver el comentario de
    # `_COSTE_LOCK`. Decidir con una foto fija hace que dos secciones de la
    # misma llamada no puedan ver mundos distintos.
    costes = _costes_ahora()

    for nombre in pedidas:
        gastado = (time.monotonic() - inicio) * 1000
        if gastado > presupuesto_ms:
            # Se DICE cuales no se pidieron. Un contexto incompleto en
            # silencio es indistinguible de un contexto vacio.
            ctx.recortadas.append(nombre)
            continue
        if (nombre in CAROS_EN_FRIO and not permitir_caros
                and costes.get(nombre, 10 ** 9) > presupuesto_ms):
            ctx.recortadas.append(nombre)
            _calentar_en_fondo(nombre, fuentes[nombre])
            continue
        antes = time.monotonic()
        try:
            valor = fuentes[nombre](texto, estado) or ""
        except Exception as exc:
            # "no se pudo" != "no hay": el aviso lo separa.
            ctx.avisos.append("{}: {}: {}".format(nombre, type(exc).__name__, exc))
            ctx.fallidas.append(nombre)
            continue
        _anotar_coste(nombre, int((time.monotonic() - antes) * 1000))
        valor = str(valor).strip()
        if valor:
            ctx.secciones[nombre] = valor
        else:
            # "No hay" es una RESPUESTA, no un no-evento. Hasta 2026-08-29
            # este else no existia: el proveedor contestaba "" y la seccion
            # se caia del mundo -- ni en `secciones`, ni en `recortadas`, ni
            # en `avisos`. Medido en esta maquina, 5 de los 8 proveedores
            # reales devuelven "" en una sesion limpia (conversacion,
            # artefactos, recetas, skills, rag) y los 5 desaparecian, con lo
            # que "el subsistema no esta cableado" y "no habia nada que
            # contar" se veian EXACTAMENTE igual desde fuera.
            ctx.vacias.append(nombre)

    # Montaje con presupuesto. Se recorta por SECCION ENTERA y en orden
    # inverso de prioridad: media seccion es peor que ninguna (una lista de
    # artefactos cortada a la mitad se lee como si esos fueran todos).
    partes, usado = [], 0
    for nombre in SECCIONES:
        valor = ctx.secciones.get(nombre)
        if not valor:
            continue
        trozo = f"{_TITULOS.get(nombre, nombre)}:\n{valor}"
        if usado + len(trozo) + 2 > presupuesto_chars:
            ctx.recortadas.append(nombre)
            continue
        partes.append(trozo)
        usado += len(trozo) + 2
    ctx.bloque = "\n\n".join(partes)
    ctx.chars = len(ctx.bloque)
    # OJO: aqui va la CONVERSACION, no el bloque entero. Hasta 2026-08-29 se
    # pasaba `ctx.bloque` (hasta PRESUPUESTO_CHARS = 1800 chars con entorno,
    # artefactos, recetas, skills, memorias y rag dentro) y eso apagaba la
    # encuesta sola: las senales de cobertura son palabras como "python",
    # "fichero", "archivo", "carpeta", "ruta", "servidor" o "local", que en un
    # repo Python aparecen en el blob de la maquina CASI SEGURO aunque el
    # usuario no las haya dicho nunca. Medido: "hazme una pagina web" perdia
    # 'proposito' y 'stack' -- se quedaba con 2 de 4 huecos -- solo por el
    # contexto; con menos contexto util faltantes se vaciaba entera.
    #
    # La regla 1 de encuesta.py ("no preguntar lo que ya esta dicho") sigue en
    # pie: lo que el usuario DIJO esta en su texto y en los ultimos turnos.
    # 'entorno' y 'rag' son datos de la MAQUINA, no decisiones del usuario, y
    # tomarlos por respuestas es atribuirle una eleccion que no hizo -- el
    # mismo fallo que este subsistema tiene prohibido cometer.
    ctx.faltantes = faltantes_por_tipo(
        texto, ctx.tipo_tarea, contexto=ctx.secciones.get("conversacion", ""))
    ctx.ms = int((time.monotonic() - inicio) * 1000)
    return ctx
