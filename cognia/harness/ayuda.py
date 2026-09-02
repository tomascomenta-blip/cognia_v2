# -*- coding: utf-8 -*-
"""
cognia/harness/ayuda.py
=======================
Ayuda NAVEGABLE del REPL: portada, secciones, busqueda difusa y sugerencias.

POR QUE EXISTE (2026-08-12): hoy `/ayuda` a secas vuelca los 240 comandos del
registro en una pared de texto de 13.438 px medidos sobre la captura real. Es
lo PRIMERO que ve un usuario nuevo y es inutilizable: no hay jerarquia, no hay
entrada, no hay salida. El juicio visual de esta noche (capturas de Claude
Code, Codex CLI, Crush y Gemini CLI leidas con VLM) dice lo mismo en las cuatro:
cabecera corta, UNA regla horizontal fina en vez de marcos, un solo acento de
color, y el detalle SIEMPRE bajo demanda ("ctrl+o to expand"). Aca se aplica
eso al catalogo: la portada cabe en 25 lineas y ensena COMO pedir el resto.

Lo que NO se toca (identidad reclamada por el dueno): el gato Braille va por
defecto, el logo COGNIA en bloques y el marco "COGNIA vX.Y.Z" siguen siendo la
marca, y la UI va en espanol. Aca solo se corrigen DENSIDAD y JERARQUIA.

Este modulo NO importa `cognia/cli.py`: recibe el dict {comando: descripcion}
por parametro. Asi los tests no cargan el monolito y el modulo no se acopla al
REPL (el cableado de `/ayuda` lo hace el integrador).

API publica (todo devuelve str o listas planas; nada imprime por su cuenta):

    CATEGORIAS                      dict ordenado categoria -> patrones
    clasificar(nombre, desc="")     -> categoria (tabla explicita; "Otros" al final)
    indice(comandos, ancho=...)     -> [(categoria, [(cmd, desc_corta)]), ...]
    portada(comandos, ancho=...)    -> lo que imprime "/ayuda" a secas (<= 25 lineas)
    seccion(comandos, cat, ancho)   -> UNA categoria, a dos columnas si entra
    todo(comandos, ancho=...)       -> el catalogo completo, por categorias
    buscar(comandos, texto, limite) -> [(cmd, desc, motivo)] ordenado por calidad
    sugerir(comandos, entrada, n)   -> ["/cmd", ...] "quiza quisiste decir"
    mensaje_desconocido(...)        -> el aviso listo para el REPL (2-4 lineas)
    resolver_categoria(texto)       -> categoria | None (tolerante a acentos)
    desbordes(comandos, tope=25)    -> [(categoria, n)] que pasan el tope

REGLA DE CLASIFICACION (explicita, sin heuristica magica):
  1. Se busca el patron MAS LARGO que case. Un patron sin `*` casa por igualdad
     exacta; con `*` al final casa por prefijo. Por eso `/buscar` (ficheros),
     `/buscar-kg` (grafo) y `/buscar-web` (web) caen en categorias distintas, y
     `/contexto-semantico` (exacto, 19 chars) le gana a `/contexto*` (9).
  2. Empate de longitud -> gana la categoria que aparece antes en CATEGORIAS.
  3. Si nada casa (comando nuevo que nadie dio de alta), se miran palabras
     clave de la DESCRIPCION (_REGLAS_DESC).
  4. Si tampoco, "Otros". Nunca se pierde un comando.

TOPE DE 25 POR CATEGORIA: con 240 comandos hacen falta ~14 cajones para que
ninguno pase de 25 lineas (una pantalla). `desbordes()` es el chequeo que lo
hace cumplir en vez de la promesa en prosa; el test de regresion lo corre contra
el catalogo REAL. Si un cajon desborda, `portada()` lo marca con "!" para que el
desbordamiento se vea en pantalla y no solo en un comentario.

Windows: los glifos se eligen al importar segun lo que aguante la consola
(`COGNIA_AYUDA_ASCII=1` fuerza el fallback ASCII). Sin emojis, nunca.
rich es opcional: con `marcado=True` el texto sale con markup del tema del CLI
(`mod`, `info_dim`, `ok`), y los corchetes de las descripciones van escapados.
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import sys
import unicodedata

# ---------------------------------------------------------------------------
# Medidas
# ---------------------------------------------------------------------------
ANCHO_DEFECTO = 100          # mismo tope comodo que cognia/ux/estilo.py
ANCHO_MIN = 40
LIMITE_PORTADA = 25          # la portada CABE en una pantalla chica
TOPE_CATEGORIA = 25          # ninguna categoria deberia pasar de aca
_SANGRIA = "  "
_OTROS = "Otros"

# Los 8 esenciales de la portada, en orden de utilidad para alguien que recien
# llega. Se filtran contra el catalogo recibido (si un comando no existe, no
# aparece y entra el siguiente de la lista).
ESENCIALES = [
    "/hacer", "/pensar", "/crear", "/leer", "/buscar", "/modelo",
    "/estado", "/salir", "/memoria", "/historial",
]
_N_ESENCIALES = 8


# ---------------------------------------------------------------------------
# Glifos: Unicode seguro con fallback ASCII (la consola de Windows por defecto
# no siempre puede con U+2500). Se decide UNA vez, al importar.
# ---------------------------------------------------------------------------
def _consola_soporta(txt: str) -> bool:
    enc = getattr(sys.stdout, "encoding", None) or ""
    if not enc:
        return False
    try:
        txt.encode(enc)
        return True
    except Exception:
        return False


def _elegir_glifos() -> dict:
    forzar = os.environ.get("COGNIA_AYUDA_ASCII", "").strip().lower()
    ascii_ = forzar in ("1", "on", "true", "si", "yes")
    if not ascii_:
        # ─ regla fina, · punto medio, … elipsis, │ barra
        ascii_ = not _consola_soporta("─·…│")
    if ascii_:
        return {"regla": "-", "punto": "*", "elipsis": "...",
                "flecha": "->", "sep": "|"}
    return {"regla": "─", "punto": "·", "elipsis": "…",
            "flecha": "→", "sep": "│"}


GLIFOS = _elegir_glifos()


# ---------------------------------------------------------------------------
# Ancho visual y recorte (CJK cuenta doble; los diacriticos combinantes, cero)
# ---------------------------------------------------------------------------
def ancho_visual(txt: str) -> int:
    n = 0
    for ch in txt or "":
        if unicodedata.combining(ch):
            continue
        n += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return n


def _pad(txt: str, ancho: int) -> str:
    return txt + " " * max(0, ancho - ancho_visual(txt))


def _cortar(txt: str, ancho: int) -> str:
    """Recorta a `ancho` columnas visuales cerrando con elipsis. Corta en
    limite de palabra si eso no sacrifica mas de un tercio del espacio."""
    txt = (txt or "").strip()
    if ancho <= 0:
        return ""
    if ancho_visual(txt) <= ancho:
        return txt
    eli = GLIFOS["elipsis"]
    tope = ancho - ancho_visual(eli)
    if tope <= 0:
        return eli[:ancho]
    acc, n = [], 0
    for ch in txt:
        w = 0 if unicodedata.combining(ch) else (
            2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1)
        if n + w > tope:
            break
        acc.append(ch)
        n += w
    corte = "".join(acc)
    esp = corte.rfind(" ")
    if esp >= int(tope * 0.66):
        corte = corte[:esp]
    return corte.rstrip(" ,;:.-") + eli


# ---------------------------------------------------------------------------
# Normalizacion tolerante a acentos (la UI va en espanol: "sesion" tiene que
# encontrar "sesión" y al reves)
# ---------------------------------------------------------------------------
def normalizar(txt: str) -> str:
    """minusculas, sin acentos, sin espacios de mas."""
    txt = unicodedata.normalize("NFD", str(txt or ""))
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", txt).strip().lower()


def _clave(nombre: str) -> str:
    """Nombre de comando normalizado y siempre con '/' delante."""
    n = normalizar(nombre)
    if n and not n.startswith("/"):
        n = "/" + n
    return n


# ---------------------------------------------------------------------------
# LA TABLA. categoria -> patrones. Sin '*' = nombre exacto; con '*' = prefijo.
# Orden = orden de aparicion en la portada y en /ayuda todo.
# ---------------------------------------------------------------------------
CATEGORIAS: dict[str, tuple[str, ...]] = {
    # Fusion 2026-08-25 (remoto-paridad + modo-bots): /decirle y /cancelar
    # (hablarle a / cortar un agente EN CURSO) y /bots (agentes con identidad
    # propia) son de aca. Para que la categoria siguiera en 25 (llego a 27)
    # salieron tres que no eran "tareas": /esfuerzo es el mando del
    # RAZONAMIENTO (va con /pensar), /deshacer y /plan-modo son mandos del
    # ARNES (deshacer lo escrito, modo de permiso "solo investigar": van con
    # /modo-permiso). No se abrio categoria nueva: la portada cabe en 25
    # lineas y una mas se comia la fila de esenciales (el guardian lo mide).
    "Agente y tareas": (
        "/hacer", "/agente*", "/rlm", "/largo", "/deliberar", "/flujo",
        "/proyectos", "/lazo", "/tareas",
        "/tarea-*", "/plan*", "/skill*", "/delegar",
        "/workflow", "/decirle", "/cancelar", "/bots",
    ),
    # Los permisos salieron de "Agente y tareas" cuando el arnes sumo sus
    # comandos y esa categoria llego a 27 (tope 25). No es un apano por el
    # numero: quien busca "que puede tocar el agente" busca permisos, no
    # tareas — y aqui son tres comandos que se explican entre si.
    # Solo los dos de PERMISOS: /seguridad, /bloquear y /desbloquear ya viven
    # en "Sistema y diagnostico" y un patron en dos categorias las descuadra
    # (hay un guardian que lo comprueba).
    "Permisos del agente": (
        "/permisos", "/modo-permiso", "/plan-modo",
    ),
    # Categoria propia (2026-08-18) y no un hueco en "Agente y tareas": los
    # tres contestan la MISMA pregunta -- que sabe hacer esta instalacion y que
    # cabe en esta maquina -- y juntos se explican entre si. Ademas /capacidades
    # caia en "Agente y tareas" y la dejaba en 26 con el tope en 25.
    # /ventana entra aqui y NO en "Agente y tareas" (2026-08-30), por el mismo
    # criterio con el que se abrio la categoria: contesta "que cabe en esta
    # maquina" -- cuantos tokens de SALIDA deja la ventana despues del prompt --
    # que es la misma pregunta que /vram, no una forma de mandar una tarea. Y de
    # paso no repite la historia: "Agente y tareas" ya llego a 26 con el tope en
    # 25 tres veces (con los permisos, con /capacidades y con /tx), y el
    # guardian de desbordes lo caza en la suite.
    "Capacidades y maquina": (
        "/capacidades", "/activar", "/vram", "/ventana",
    ),
    # Categoria propia (2026-08-19), por el MISMO criterio que las dos de
    # arriba: los dos comandos contestan la misma pregunta -- que recuerda de
    # verdad una tarea larga y con que evidencia -- y se explican entre si.
    # /libro caia en "Memoria y notas", junto a /nota* y /conceptos, y eso
    # confunde dos cosas distintas: la memoria personal del dueno contra el
    # registro append-only de UNA tarea, con sus gates y su provenance. Y /tx
    # dejaba "Agente y tareas" en 26 con el tope en 25.
    "Horizonte largo (TX)": (
        "/tx", "/libro",
        "/horizonte",
    ),
    "Codigo y ficheros": (
        "/leer", "/proyecto", "/listar", "/buscar", "/escribir", "/editar",
        "/ejecutar", "/powershell", "/monitor", "/monitores", "/centinela",
        "/shells",
        "/shell-kill", "/diff", "/cat", "/mapa-codigo", "/indexar-codigo",
        "/mcp", "/backup", "/worktree",   # worktree es git, no gestion de tareas
    ),
    # 2026-08-29: /flujoteca y las dos puertas de "esta sesion -> un flujo"
    # caian en "Otros" (/flujoteca) y en "Sesion e historial" por la palabra
    # "sesion" de su descripcion (/session-to-workflow). Van AQUI, junto a
    # /biblioteca, /grabar y /receta: son la biblioteca de lo que Cognia
    # PRODUJO y como se produce. No van a "Agente y tareas" (que es donde
    # viven /flujo y /workflow, los que EJECUTAN) porque esa categoria esta
    # en 25, que es el tope duro, y un tope que se respeta a medias no es un
    # tope (test_ninguna_categoria_desborda_el_tope).
    "Crear y construir": (
        "/compilar",
        "/crear", "/construir", "/pulir", "/autoprueba", "/biblioteca",
        "/ideas", "/encolar", "/arbitro", "/tutor", "/oficina", "/imagenes",
        "/ver", "/vigilar", "/chimera", "/grabar", "/receta",
        "/flujoteca", "/session-to-workflow", "/sesion-a-workflow",
    ),
    "Pensar y razonar": (
        "/pensar", "/esfuerzo", "/razonar", "/hipotesis", "/experimento", "/evaluar-idea",
        "/analogia", "/abstraer", "/transferir", "/diversidad", "/explorar",
        "/explicar", "/debate", "/argumento", "/y-si", "/reflexion-profunda",
        "/cadena-causal", "/sintetizar", "/corregir", "/etiquetar",
        "/contradicciones",
    ),
    "Memoria y notas": (
        "/memoria*", "/buscar-memoria", "/nota*", "/conceptos", "/observar",
        "/dormir", "/olvido", "/vocabulario*", "/cognia-sabe",
        "/cognia-aprende", "/cognia-olvida", "/contexto-semantico",
    ),
    "Grafo de conocimiento": (
        "/grafo*", "/hecho", "/hechos-solidos", "/cristalizar",
        "/conocimiento-ver", "/kg-*", "/buscar-kg", "/conflictos-kg",
        "/verificar-kg", "/resolver-conflicto", "/predecir", "/inferir",
        "/narrativa", "/mapa", "/atencion", "/objetivos",
    ),
    "Aprender y repasar": (
        "/grabar-clase",
        "/aprender", "/aprendiendo", "/aprendiendo-buscar", "/revisar",
        "/repasar", "/camino*", "/quiz", "/quiz-stats", "/escalar",
        "/estilo_info", "/indice_personal", "/indice_add",
    ),
    "Metas y seguimiento": (
        "/meta*", "/recordar", "/recordatorios", "/recordar-cancelar",
        "/recomendar", "/proximos-pasos", "/sugerir", "/inicio-dia",
    ),
    "Sesion e historial": (
        "/sesiones", "/sesion-ver", "/resume",
        "/buscar-historial", "/historial", "/historial-limpiar", "/recap",
        "/compactar", "/resumir", "/resumen-sesion", "/limpiar-sesion",
        "/exportar", "/exportar-todo", "/exportar-stats", "/contexto",
        "/contexto-mapa", "/contexto-stats", "/contexto-auto",
        # /contexto-vivo (cuanto contexto queda y a que velocidad va) es
        # hermano de /contexto-mapa y /contexto-stats; los patrones son
        # EXACTOS, asi que sin esta linea caia en "Otros".
        "/contexto-vivo",
        "/ver-contexto", "/template*",
    ),
    "Web e investigacion": (
        "/web-*", "/buscar-web", "/investigar", "/aprende-repo",
    ),
    "Modelos y flota": (
        "/modelo", "/modelos", "/flota", "/cpu", "/gpu", "/velocidad",
        "/hibrido", "/prompt", "/distill", "/distill run",
    ),
    "Perfil y personalizacion": (
        "/yo", "/yo-actualizar", "/usuario", "/usuarios", "/mi-cognia",
        "/perfil-completo", "/tema", "/color", "/estilo", "/config", "/modo",
        # /mejorar: es un interruptor de COMO se comporta el prompt del usuario
        # (preguntar/auto/off), igual que /tema o /modo. Sin darlo de alta caia
        # en "Otros", un cajon de UNO donde nadie lo busca y donde el recorte
        # de ancho se comia justo los estados y el atajo F3.
        "/mejorar",
        # /avanzado (cuantos comandos se anuncian) y /encuestas (si el
        # mejorador pregunta lo que falta antes de reformular) son dos
        # interruptores de COMO se comporta la consola con lo que el dueno
        # escribe, igual que /mejorar y /modo. /encuestas caia en "Otros";
        # /avanzado es nuevo (2026-08-29) y sin darlo de alta caeria igual.
        "/avanzado", "/encuestas",
        "/modo rapido", "/features", "/limpiar",
    ),
    "Reportes y metricas": (
        "/reporte*", "/digest", "/mi-uso", "/mi-uso-detalle", "/analiticas",
        "/logros", "/patrones", "/feedback", "/feedback-sesion",
        "/calidad-respuestas", "/ver-criticas", "/fatiga", "/stats",
        "/sesion-stats", "/temas", "/costo",
    ),
    # Categoria propia (2026-08-24) para los mandos del ARNES del REPL: como
    # se pinta la respuesta (/markdown, /spinner), que ve el modelo de las
    # tools (/expandir, /offload), como entra el texto del dueno (/pegado,
    # /enlaces), la higiene del lazo (/bucle) y la config efectiva
    # (/config-resuelta). Todos contestan la misma pregunta -- como se
    # comporta la consola y con que config -- y ninguno tenia sitio: caian por
    # palabra de la descripcion en "Otros", "Modelos y flota" (/offload),
    # "Perfil" (/expandir) o "Codigo y ficheros" (/markdown, /enlaces,
    # /config-resuelta), y /bucle dejaba "Agente y tareas" en 26 con el tope
    # en 25 (revision adversarial 2026-08-24).
    # /deshacer (revertir lo que escribio el agente) y /remoto (la misma
    # consola manejada desde el movil) entraron en la fusion 2026-08-25.
    "Consola y arnes": (
        "/markdown", "/spinner", "/expandir", "/offload", "/pegado",
        "/enlaces", "/bucle", "/config-resuelta", "/deshacer", "/remoto",
        # /revision (2026-08-30) es un mando del ARNES, no del agente: la
        # compuerta que CORRE lo construido antes de entregarlo. Va con
        # /bucle y /offload, que son sus hermanos (higiene del lazo).
        "/revision",
        # 2026-09-02: /pasos (techo de pasos del bucle), /scratchpad (carpeta
        # temporal de pruebas) y /renderizar (captura aislada) son mandos del
        # ARNES por el mismo criterio que /bucle y /revision: gobiernan COMO
        # trabaja el agente, no QUE hace. Sin esta linea /pasos caia en
        # "Agente y tareas" (26 > 25) y /scratchpad en "Otros".
        "/pasos", "/scratchpad", "/renderizar",
        # /deshacer-borrado (papelera del agente, 2026-08-25) va JUNTO a
        # /deshacer, que es su hermano: uno revierte lo que el agente
        # ESCRIBIO y el otro saca de la papelera lo que BORRO. Sin esta
        # linea caia en "Agente y tareas" y la dejaba en 26 con el tope en
        # 25 (lo caza test_cli_bots::test_puerta_visible_en_el_catalogo).
        "/deshacer-borrado",
    ),
    "Sistema y diagnostico": (
        # /hermes y /rutinas viven aca (y no en una categoria propia) porque la
        # portada de /ayuda cabe en 25 lineas: una categoria nueva mas la
        # desbordaba y se comia la fila de comandos esenciales. Un tope que se
        # respeta a medias no es un tope.
        "/hermes", "/rutinas", "/autopsia", "/multiverso",
        "/doctor", "/update", "/estado", "/debug", "/seguridad", "/bloquear",
        "/desbloquear", "/mesh_*", "/modulos", "/notificar", "/notif*",
        "/salir", "/cognia-info", "/ayuda", "/comandos",
    ),
    _OTROS: (),
}

# Red de seguridad para comandos que NADIE dio de alta arriba (los que se
# agreguen manana al registro): palabras de la descripcion -> categoria.
# Se evalua en orden; primera que casa, gana.
_REGLAS_DESC: tuple[tuple[tuple[str, ...], str], ...] = (
    (("knowledge graph", " kg", "grafo", "triple"), "Grafo de conocimiento"),
    (("memoria", "nota", "recuerdo", "olvid"), "Memoria y notas"),
    (("sesion", "historial", "conversacion"), "Sesion e historial"),
    (("web", "url", "duckduckgo", "github", "navegador"), "Web e investigacion"),
    (("modelo", "gguf", "backend", "flota", "gpu", "cpu"), "Modelos y flota"),
    (("archivo", "fichero", "directorio", "repo", "codigo", "git"),
     "Codigo y ficheros"),
    (("tarea", "agente", "plan ", "plan.", "paso"), "Agente y tareas"),
    (("meta", "objetivo", "recordatorio", "progreso"), "Metas y seguimiento"),
    (("estadistica", "reporte", "metrica", "telemetria"), "Reportes y metricas"),
    (("aprend", "tarjeta", "repas", "estudi", "quiz"), "Aprender y repasar"),
    (("razona", "pensa", "hipotesis", "analisis", "idea"), "Pensar y razonar"),
    (("perfil", "usuario", "tema visual", "color"), "Perfil y personalizacion"),
)


def _compilar_patrones() -> list:
    """[(texto, es_prefijo, categoria, orden)] listo para clasificar()."""
    fuera = []
    for orden, (cat, patrones) in enumerate(CATEGORIAS.items()):
        for p in patrones:
            es_pref = p.endswith("*")
            fuera.append((_clave(p[:-1] if es_pref else p), es_pref, cat, orden))
    return fuera


_PATRONES = _compilar_patrones()


def clasificar(nombre: str, descripcion: str = "") -> str:
    """Categoria de un comando. Patron mas LARGO gana; exacto le gana al
    prefijo de igual longitud; sin patron se miran palabras de la descripcion;
    al final, siempre, "Otros"."""
    n = _clave(nombre)
    if not n:
        return _OTROS
    mejor_peso, mejor_cat = None, None
    for pat, es_pref, cat, orden in _PATRONES:
        casa = n.startswith(pat) if es_pref else (n == pat)
        if not casa:
            continue
        peso = (len(pat), 0 if es_pref else 1, -orden)
        if mejor_peso is None or peso > mejor_peso:
            mejor_peso, mejor_cat = peso, cat
    if mejor_cat is not None:
        return mejor_cat
    texto = normalizar(descripcion) + " " + n
    for palabras, cat in _REGLAS_DESC:
        if any(p in texto for p in palabras):
            return cat
    return _OTROS


# ---------------------------------------------------------------------------
# Descripciones de una linea
# ---------------------------------------------------------------------------
_RX_HUECO = re.compile(r"\s{2,}")


def resumir_desc(descripcion: str, ancho: int = 60) -> str:
    """Una linea util: se queda con la CABEZA de la descripcion (lo que va
    antes del hueco de 2+ espacios, que en este registro separa la frase de la
    plantilla de argumentos) y suelta el "Uso: ..." largo."""
    d = str(descripcion or "").replace("\n", " ").strip()
    if not d:
        return ""
    cabeza = _RX_HUECO.split(d)[0].strip()
    for marca in (". Uso:", " Uso:", "; uso:"):
        pos = cabeza.find(marca)
        if pos > 12:
            cabeza = cabeza[:pos]
            break
    cabeza = re.sub(r"\s+", " ", cabeza).strip(" .;,")
    return _cortar(cabeza, ancho)


# ---------------------------------------------------------------------------
# Marcado rich opcional (mismo vocabulario de estilos que el tema del CLI)
# ---------------------------------------------------------------------------
def _escapar(txt: str) -> str:
    """Los corchetes de las descripciones ('[patron | flota]') son markup para
    rich: se escapan igual que hace cli.py antes de imprimir."""
    return str(txt).replace("[", "\\[")


def _est(txt: str, estilo: str, marcado: bool) -> str:
    if not marcado or not txt.strip():
        return txt
    return f"[{estilo}]{_escapar(txt)}[/{estilo}]"


def _ancho_util(ancho: int | None) -> int:
    if ancho is None:
        try:
            ancho = shutil.get_terminal_size().columns
        except Exception:
            ancho = 80
    return max(ANCHO_MIN, min(int(ancho), 200))


def _regla(ancho: int, marcado: bool) -> str:
    return _est(_SANGRIA + GLIFOS["regla"] * (ancho - len(_SANGRIA)),
                "info_dim", marcado)


def _envolver(texto: str, ancho: int, sangria: str = _SANGRIA,
              sangria_cont: str | None = None) -> list:
    """Parte `texto` en lineas que CABEN en `ancho` columnas visuales, cortando
    por espacios. Existe porque los textos largos de una sola pieza (el menu de
    categorias, la lista de sugerencias) desbordaban la consola angosta: se
    escribian de un tiron, sin mirar el ancho."""
    cont = sangria if sangria_cont is None else sangria_cont
    fuera: list[str] = []
    actual = ""
    pre = sangria
    for palabra in re.split(r"\s+", str(texto or "").strip()):
        if not palabra:
            continue
        util = max(8, ancho - ancho_visual(pre))
        if ancho_visual(palabra) > util:
            palabra = _cortar(palabra, util)
        if not actual:
            actual = palabra
        elif ancho_visual(actual) + 1 + ancho_visual(palabra) <= util:
            actual += " " + palabra
        else:
            fuera.append(pre + actual)
            pre, actual = cont, palabra
    if actual:
        fuera.append(pre + actual)
    return fuera


# ---------------------------------------------------------------------------
# Indice
# ---------------------------------------------------------------------------
def indice(comandos: dict, ancho: int | None = None) -> list:
    """[(categoria, [(cmd, desc_corta), ...]), ...] en el orden de CATEGORIAS,
    con los comandos ordenados alfabeticamente y las categorias vacias fuera."""
    ancho = _ancho_util(ancho)
    cajones: dict[str, list] = {c: [] for c in CATEGORIAS}
    for cmd, desc in (comandos or {}).items():
        cat = clasificar(cmd, desc)
        cajones.setdefault(cat, []).append((str(cmd), str(desc or "")))
    ancho_desc = max(20, ancho - 30)
    fuera = []
    for cat in cajones:
        entradas = sorted(cajones[cat], key=lambda p: normalizar(p[0]))
        if not entradas:
            continue
        fuera.append((cat, [(c, resumir_desc(d, ancho_desc)) for c, d in entradas]))
    return fuera


def desbordes(comandos: dict, tope: int = TOPE_CATEGORIA) -> list:
    """Categorias que pasan el tope de entradas, mayor primero. Es el chequeo
    que hace cumplir la promesa "ninguna categoria mas larga que una pantalla";
    el test de regresion lo corre contra el catalogo real."""
    fuera = [(cat, len(e)) for cat, e in indice(comandos) if len(e) > tope]
    return sorted(fuera, key=lambda p: -p[1])


# ---------------------------------------------------------------------------
# Categorias por nombre suelto ("/ayuda memoria" -> "Memoria y notas")
# ---------------------------------------------------------------------------
def resolver_categoria(texto: str) -> str | None:
    """Tolerante: acentos, mayusculas, nombre parcial y el numero de orden."""
    q = normalizar(texto)
    if not q:
        return None
    nombres = list(CATEGORIAS)
    if q.isdigit():
        i = int(q) - 1
        return nombres[i] if 0 <= i < len(nombres) else None
    normal = {n: normalizar(n) for n in nombres}
    for n in nombres:
        if normal[n] == q:
            return n
    for n in nombres:
        if normal[n].startswith(q):
            return n
    for n in nombres:
        if q in normal[n]:
            return n
    # ultima chance: alguna palabra de la categoria empieza por lo tecleado
    for n in nombres:
        if any(p.startswith(q) for p in normal[n].split()):
            return n
    cerca = difflib.get_close_matches(q, [normal[n] for n in nombres], n=1,
                                      cutoff=0.7)
    if cerca:
        for n in nombres:
            if normal[n] == cerca[0]:
                return n
    return None


# ---------------------------------------------------------------------------
# Render de una categoria (dos columnas si el ancho da)
# ---------------------------------------------------------------------------
def _fila(cmd: str, desc: str, ancho_cmd: int, ancho_total: int,
          marcado: bool) -> str:
    nombre = _pad(_cortar(cmd, ancho_cmd), ancho_cmd)
    hueco = ancho_total - ancho_cmd - 2
    texto = _cortar(desc, max(0, hueco))
    return _est(nombre, "mod", marcado) + "  " + _est(texto, "info_dim", marcado)


def _bloque_columnas(entradas: list, ancho: int, marcado: bool) -> list:
    """Las entradas en 1 o 2 columnas. En dos columnas el orden es POR COLUMNA
    (alfabetico hacia abajo y despues a la derecha), que es como se lee."""
    if not entradas:
        return []
    ancho_cmd = min(24, max((ancho_visual(c) for c, _ in entradas), default=8))
    util = ancho - len(_SANGRIA)
    ancho_col = (util - 3) // 2
    dos = len(entradas) > 6 and ancho_col >= ancho_cmd + 14
    if not dos:
        return [_SANGRIA + _fila(c, d, ancho_cmd, util, marcado)
                for c, d in entradas]
    filas = (len(entradas) + 1) // 2
    izq, der = entradas[:filas], entradas[filas:]
    fuera = []
    for i in range(filas):
        a = _fila(izq[i][0], izq[i][1], ancho_cmd, ancho_col, marcado)
        if i < len(der):
            b = _fila(der[i][0], der[i][1], ancho_cmd, ancho_col, marcado)
            # El relleno de la izquierda se mide sobre el texto SIN markup y
            # puede ser CERO: con max(1,...) las celdas que llenaban la columna
            # corrian la segunda columna una posicion y la tabla bailaba.
            plano = _fila(izq[i][0], izq[i][1], ancho_cmd, ancho_col, False)
            a = a + " " * max(0, ancho_col - ancho_visual(plano)) + "   " + b
        fuera.append((_SANGRIA + a).rstrip())
    return fuera


def seccion(comandos: dict, categoria: str, ancho: int | None = None,
            marcado: bool = False) -> str:
    """El listado de UNA categoria. Si la categoria no existe, devuelve el
    menu de categorias validas (nunca lanza: es presentacion)."""
    ancho = _ancho_util(ancho)
    cat = resolver_categoria(categoria)
    idx = dict(indice(comandos, ancho))
    if cat is None or cat not in idx:
        disponibles = ", ".join(c for c, _ in indice(comandos, ancho))
        pedido = _cortar(str(categoria), max(8, ancho - 26))
        lineas = _envolver("No hay una categoria \"%s\"." % pedido, ancho)
        # el menu se ENVUELVE: de un tiron eran 294 columnas en una sola linea
        lineas += _envolver("Categorias: " + disponibles, ancho,
                            sangria_cont=_SANGRIA * 2)
        return "\n".join(lineas)
    entradas = idx[cat]
    util_cab = ancho - len(_SANGRIA)
    cabecera = "%s  (%d comandos)" % (cat, len(entradas))
    if ancho_visual(cabecera) > util_cab:      # consola angosta: forma compacta
        cabecera = "%s (%d)" % (cat, len(entradas))
    cabecera = _cortar(cabecera, util_cab)
    lineas = [_SANGRIA + _est(cabecera, "ok", marcado), _regla(ancho, marcado)]
    lineas += _bloque_columnas(entradas, ancho, marcado)
    return "\n".join(lineas)


def todo(comandos: dict, ancho: int | None = None,
         marcado: bool = False) -> str:
    """El catalogo completo ("/ayuda todo"): sigue siendo largo A PROPOSITO,
    pero ya viene por categorias y a dos columnas, no como una pared."""
    ancho = _ancho_util(ancho)
    partes = [seccion(comandos, cat, ancho, marcado)
              for cat, _ in indice(comandos, ancho)]
    return "\n\n".join(partes)


# ---------------------------------------------------------------------------
# Portada: lo que imprime "/ayuda" a secas. CABE en 25 lineas.
# ---------------------------------------------------------------------------
def _bloque_categorias(idx: list, ancho: int, marcado: bool) -> list:
    """Categorias con su cuenta, en columnas. La categoria que desborda el tope
    se marca con '!' (el desbordamiento se VE, no se documenta y ya)."""
    celdas = []
    for cat, entradas in idx:
        marca = "!" if len(entradas) > TOPE_CATEGORIA else ""
        celdas.append("%s (%d)%s" % (cat, len(entradas), marca))
    if not celdas:
        return []
    ancho_celda = max(ancho_visual(c) for c in celdas) + 3
    util = ancho - len(_SANGRIA) * 2
    cols = max(1, min(3, util // max(1, ancho_celda)))
    filas = (len(celdas) + cols - 1) // cols
    fuera = []
    for f in range(filas):
        indices = [c * filas + f for c in range(cols)]
        indices = [i for i in indices if i < len(celdas)]
        trozos = []
        for pos, i in enumerate(indices):
            # la ULTIMA celda de la fila no se rellena: con marcado el relleno
            # queda DENTRO del markup y el rstrip ya no puede quitarlo, asi que
            # la linea medida se pasaba del ancho.
            plano = celdas[i] if pos == len(indices) - 1 else _pad(celdas[i],
                                                                  ancho_celda)
            trozos.append(_est(plano, "detail", marcado) if marcado else plano)
        fuera.append((_SANGRIA * 2 + "".join(trozos)).rstrip())
    return fuera


def portada(comandos: dict, ancho: int | None = None,
            marcado: bool = False) -> str:
    """Portada de la ayuda: cuantos comandos hay, los esenciales, las
    categorias con su cuenta y COMO ver el resto. Nunca lista los 240."""
    ancho = _ancho_util(ancho)
    comandos = comandos or {}
    idx = indice(comandos, ancho)
    total = len(comandos)
    titulo = "Ayuda de Cognia"
    cuenta = "%d comandos %s %d categorias" % (total, GLIFOS["sep"], len(idx))
    util = ancho - len(_SANGRIA)
    hueco = util - ancho_visual(titulo) - ancho_visual(cuenta)
    if hueco >= 1:
        cab = [_SANGRIA + _est(titulo, "ok", marcado) + " " * hueco +
               _est(cuenta, "info_dim", marcado)]
    else:
        # consola angosta: la cuenta BAJA a su linea en vez de desbordar (a 40
        # columnas la cabecera de una sola linea media 46).
        cab = [_SANGRIA + _est(_cortar(titulo, util), "ok", marcado),
               _SANGRIA + _est(_cortar(cuenta, util), "info_dim", marcado)]

    esenciales = [c for c in ESENCIALES if c in comandos][:_N_ESENCIALES]
    ancho_cmd = min(18, max((ancho_visual(c) for c in esenciales), default=8))
    filas_ese = [
        _SANGRIA * 2 + _fila(c, resumir_desc(comandos.get(c, ""),
                                             ancho - 30),
                             ancho_cmd, ancho - len(_SANGRIA) * 2, marcado)
        for c in esenciales
    ]

    pistas = [
        ("/ayuda <categoria>", "el listado de esa categoria (ej: /ayuda memoria)"),
        ("/ayuda buscar <texto>", "busca por nombre y por descripcion"),
        ("/ayuda todo", "el catalogo completo, por categorias"),
    ]
    ancho_pista = max(ancho_visual(p) for p, _ in pistas)
    filas_pista = [
        _SANGRIA * 2 + _fila(p, d, ancho_pista, ancho - len(_SANGRIA) * 2,
                             marcado)
        for p, d in pistas
    ]

    filas_cat = _bloque_categorias(idx, ancho, marcado)

    def armar(n_ese: int, n_cat: int | None = None) -> list:
        out = list(cab) + [_regla(ancho, marcado)]
        if n_ese:
            out.append(_SANGRIA + _est("Para empezar", "ok", marcado))
            out += filas_ese[:n_ese]
            out.append("")
        out.append(_SANGRIA + _est("Categorias", "ok", marcado))
        if n_cat is None or n_cat >= len(filas_cat):
            out += filas_cat
        else:
            visibles = max(0, n_cat - 1)
            out += filas_cat[:visibles]
            out.append(_SANGRIA * 2 + _est(
                "%s y %d lineas mas en /ayuda todo"
                % (GLIFOS["elipsis"], len(filas_cat) - visibles),
                "detail", marcado))
        out.append("")
        out.append(_SANGRIA + _est("Ver mas", "ok", marcado))
        out += filas_pista
        return out

    lineas = armar(len(filas_ese))
    # Garantia dura: la portada CABE. Lo primero que se recorta son los
    # esenciales; si ni sin ellos entra, se recortan las CATEGORIAS. Las pistas
    # de navegacion NUNCA se pierden (antes el corte final [:25] se las comia).
    n = len(filas_ese)
    while len(lineas) > LIMITE_PORTADA and n > 0:
        n -= 1
        lineas = armar(n)
    if len(lineas) > LIMITE_PORTADA and filas_cat:
        sobra = len(lineas) - LIMITE_PORTADA
        lineas = armar(0, max(1, len(filas_cat) - sobra))
    return "\n".join(lineas[:LIMITE_PORTADA])


# ---------------------------------------------------------------------------
# Busqueda difusa
# ---------------------------------------------------------------------------
_MOTIVOS = {
    0: "nombre exacto",
    1: "empieza por",
    2: "en el nombre",
    3: "en la descripcion",
}


def buscar(comandos: dict, texto: str, limite: int = 15) -> list:
    """[(cmd, desc, motivo)] ordenado por calidad de la coincidencia:
    nombre exacto > prefijo del nombre > subcadena del nombre > subcadena de la
    descripcion. Tolerante a acentos en los dos lados (consulta y catalogo).
    `limite` <= 0 devuelve lista vacia (antes el max(1, ...) colaba un hit)."""
    q = normalizar(texto).lstrip("/")
    limite = int(limite)
    if not q or limite <= 0:
        return []
    hits = []
    for cmd, desc in (comandos or {}).items():
        n = _clave(cmd).lstrip("/")
        d = normalizar(desc)
        if n == q:
            rango = 0
        elif n.startswith(q):
            rango = 1
        elif q in n:
            rango = 2
        elif q in d:
            rango = 3
        else:
            continue
        hits.append((rango, n, str(cmd), str(desc or "")))
    hits.sort(key=lambda h: (h[0], len(h[1]), h[1]))
    return [(c, d, _MOTIVOS[r]) for r, _, c, d in hits[:max(1, int(limite))]]


def sugerir(comandos: dict, entrada_desconocida: str, limite: int = 3) -> list:
    """"Quiza quisiste decir": nombres parecidos a lo que el usuario tecleo.
    difflib primero (errores de tipeo) y, si no da nada, prefijo/subcadena
    (el usuario que escribe medio comando: '/memo' -> '/memoria')."""
    q = _clave(entrada_desconocida)
    limite = int(limite)
    if not q or not comandos or limite <= 0:
        return []
    porNorm = {}
    for cmd in comandos:
        porNorm.setdefault(_clave(cmd), str(cmd))
    nombres = list(porNorm)
    fuera: list[str] = []
    for n in difflib.get_close_matches(q, nombres, n=limite * 3, cutoff=0.6):
        real = porNorm[n]
        if real not in fuera:
            fuera.append(real)
        if len(fuera) >= limite:
            return fuera
    cuerpo = q.lstrip("/")
    for n in sorted(nombres, key=len):
        if len(fuera) >= limite:
            break
        real = porNorm[n]
        if real in fuera:
            continue
        if n.startswith(q) or (len(cuerpo) >= 3 and cuerpo in n):
            fuera.append(real)
    return fuera[:limite]


def mensaje_desconocido(comandos: dict, entrada: str, limite: int = 3,
                        ancho: int | None = None) -> str:
    """Lo que reemplaza al "Comando desconocido" pelado de hoy: dice que no
    existe, propone lo parecido y recuerda como buscar. Respeta el ancho (las
    sugerencias se envuelven; el comando tecleado se recorta)."""
    ancho = _ancho_util(ancho)
    entrada = str(entrada or "").strip()
    cerca = sugerir(comandos, entrada, limite)
    corto = _cortar(entrada, max(8, ancho - 24)) or "?"
    partes = [_SANGRIA + "No existe el comando %s." % corto]
    if cerca:
        partes += _envolver("Quiza quisiste decir: " + ", ".join(cerca), ancho,
                            sangria_cont=_SANGRIA * 2)
    consulta = _cortar(entrada.lstrip("/"), max(8, ancho - 32)) or "<texto>"
    partes.append(_SANGRIA + "%s /ayuda buscar %s  %s  /ayuda" % (
        GLIFOS["punto"], consulta, GLIFOS["sep"]))
    return "\n".join(partes)
