"""
query_planner.py — Descompone una pregunta en varias queries de busqueda.

El scraper original recibia la query ya escrita a mano. Eso significa que
Cognia no investigaba una PREGUNTA, ejecutaba una BUSQUEDA que alguien mas
habia pensado. Este modulo cierra ese hueco: entra una pregunta en lenguaje
natural, salen varias queries que cubren distintas facetas.

Funciona sin LLM (descomposicion deterministica por terminos y facetas). Si
hay un LLM local levantado, le pide que mejore las queries y usa las suyas
cuando devuelve algo usable. Que el camino deterministico sea el de base y no
el fallback es a proposito: la investigacion no se cae sin modelo.

Sin dependencias externas: solo stdlib.
"""

from typing import List

from ..llm_local import generar
from .relevance import tokenizar

# GitHub y HuggingFace estan en ingles: buscar 'modelo pequeno contexto' no
# devuelve nada util. Se traducen los terminos de dominio mas comunes.
GLOSARIO = {
    "modelo": "model", "modelos": "models",
    "pequeno": "small", "pequeño": "small", "pequenos": "small", "pequeños": "small",
    "grande": "large", "grandes": "large",
    "contexto": "context", "ventana": "window",
    "memoria": "memory", "atencion": "attention", "atención": "attention",
    "lenguaje": "language", "inferencia": "inference",
    "cuantizacion": "quantization", "cuantización": "quantization",
    "compresion": "compression", "compresión": "compression",
    "entrenamiento": "training", "aprendizaje": "learning",
    "rendimiento": "performance", "velocidad": "speed",
    "peso": "weight", "pesos": "weights", "tamano": "size", "tamaño": "size",
    "largo": "long", "maximo": "maximum", "máximo": "maximum",
    "eficiente": "efficient", "eficiencia": "efficiency",
    "red": "network", "neuronal": "neural", "capa": "layer", "capas": "layers",
    "datos": "data", "conjunto": "dataset",
    "computador": "computer", "computadora": "computer", "maquina": "machine",
    "calidad": "quality",
    # Herramientas y agentes. Sin esto, preguntar por "agentes de coding por
    # linea de comandos" producia la query 'caracteristicas comandos
    # implementarlas': tres palabras en espanol contra APIs que solo entienden
    # ingles y que hacen AND de todo, o sea cero resultados garantizados.
    "agente": "agent", "agentes": "agents",
    "herramienta": "tool", "herramientas": "tools",
    "comando": "command", "comandos": "command",
    "linea": "cli", "terminal": "terminal", "consola": "console",
    "servidor": "server", "servidores": "server",
    "repositorio": "repository", "repositorios": "repository",
    "biblioteca": "library", "libreria": "library", "librería": "library",
    "complemento": "plugin", "extension": "extension", "extensión": "extension",
    "marco": "framework", "editor": "editor",
    "codigo": "code", "código": "code", "programacion": "programming",
    "programación": "programming", "programar": "programming",
    "caracteristica": "feature", "caracteristicas": "features",
    "característica": "feature", "características": "features",
    "funcion": "function", "función": "function",
    "gratuito": "free", "gratuitos": "free", "gratis": "free",
    "abierto": "open", "abiertos": "open", "fuente": "source",
    "registro": "signup", "clave": "key",
    "implementar": "implementation", "implementarlas": "implementation",
    "implementacion": "implementation", "implementación": "implementation",
    "generar": "generation", "generacion": "generation", "generación": "generation",
    "pagina": "page", "página": "page", "paginas": "page", "páginas": "page",
    "web": "web", "sitio": "website", "interfaz": "ui", "diseno": "design",
    "diseño": "design", "bonita": "beautiful", "bonitas": "beautiful",
    "unico": "unique", "unicos": "unique", "único": "unique", "únicos": "unique",
    "unica": "unique", "unicas": "unique", "única": "unique", "únicas": "unique",
    "mejor": "best", "mejores": "best", "comparacion": "comparison",
    "comparación": "comparison", "alternativa": "alternative",
    "alternativas": "alternative",
}

# Tokens que ya son tecnicos e ingleses: pasan tal cual aunque no esten en el
# glosario. Se detectan tambien por forma (siglas, con digitos) mas abajo.
TECNICOS = {
    "mcp", "cli", "api", "sdk", "llm", "gguf", "html", "css", "js",
    "javascript", "python", "rust", "typescript", "json", "yaml", "git",
    "github", "docker", "linux", "windows", "vscode", "vim", "neovim",
    "agent", "agents", "tool", "tools", "server", "plugin", "skill", "skills",
    "prompt", "prompts", "repo", "repository", "framework", "library",
    "terminal", "console", "editor", "code", "coding", "open", "source",
    "free", "sandbox", "workflow", "pipeline", "autonomous", "assistant",
    "copilot", "claude", "openai", "anthropic", "ollama", "vram", "ram",
    "web", "ui", "ux", "frontend", "design", "beautiful", "dashboard",
}

# Vocabulario tecnico, separado en sustantivos (la COSA que se busca) y
# modificadores (como es esa cosa). La distincion importa: una query util
# necesita al menos un sustantivo, y un modificador solo no busca nada.
# 'maximum context' sin 'model' encuentra papers; 'small model' sin 'context'
# encuentra modelos. Hay que llevar de los dos.
NUCLEOS_EN = {
    "model", "models", "context", "window", "memory", "attention", "language",
    "inference", "quantization", "compression", "training", "learning",
    "network", "neural", "layer", "layers", "transformer", "embedding",
    "token", "tokens", "cache", "kv", "dataset", "benchmark", "cpu", "gpu",
    "performance", "speed", "size", "weight", "weights",
    # Herramientas y agentes: sin estos, preguntar por agentes CLI perdia el
    # sustantivo central y la query quedaba en 'model' o en nada.
    "agent", "agents", "tool", "tools", "cli", "mcp", "server", "plugin",
    "skill", "skills", "repository", "framework", "library", "terminal",
    "console", "editor", "code", "coding", "programming", "workflow",
    "pipeline", "prompt", "prompts", "feature", "features", "implementation",
    "assistant", "copilot", "sandbox", "api", "sdk", "extension",
    "page", "web", "website", "ui", "ux", "frontend", "design", "dashboard",
    "generation", "html", "css",
}

MODIFICADORES_EN = {
    "small", "large", "tiny", "long", "short", "maximum", "minimum",
    "efficient", "efficiency", "quality", "fast", "cheap", "local",
    "free", "open", "source", "unique", "best", "autonomous", "native",
    "beautiful", "comparison", "alternative",
}

DOMINIO_EN = NUCLEOS_EN | MODIFICADORES_EN

# Cuantos sustantivos y cuantos modificadores lleva el nucleo de la query.
NUCLEO_SUSTANTIVOS  = 2
NUCLEO_MODIFICADORES = 1

# Facetas con las que se recorre un tema: cada una encuentra repos distintos.
FACETAS = [
    "benchmark evaluation",
    "implementation",
    "efficient inference",
    "survey awesome",
    "quantization",
]

# Buscar herramientas no se parece a buscar papers. 'quantization' o
# 'efficient inference' no encuentran un agente de terminal; 'awesome list' y
# 'alternatives' si, porque asi es como la gente cataloga proyectos.
FACETAS_HERRAMIENTAS = [
    "awesome list",
    "cli tool",
    "open source alternative",
    "comparison",
    "self hosted",
]

# Sustantivos que delatan que la pregunta busca PROYECTOS, no literatura.
SENAL_HERRAMIENTAS = {
    "agent", "agents", "tool", "tools", "cli", "mcp", "server", "plugin",
    "skill", "skills", "repository", "framework", "library", "terminal",
    "editor", "assistant", "copilot", "extension", "sdk",
}


def _facetas_para(terminos: List[str]) -> List[str]:
    """Elige el juego de facetas segun lo que se este buscando."""
    if any(t in SENAL_HERRAMIENTAS for t in terminos):
        return FACETAS_HERRAMIENTAS
    return FACETAS

# Cuantos terminos usar como nucleo. Mas de 3 y las APIs, que hacen AND de
# todo, empiezan a devolver 0 resultados.
NUCLEO_MAX = 3


# Palabras funcionales espanolas. Lista cerrada: son las que sobreviven a la
# tokenizacion y ensucian la query sin aportar nada.
_FUNCIONALES_ES = {
    "de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas", "que",
    "para", "con", "en", "por", "cual", "cuales", "como", "sin", "sobre",
    "entre", "mas", "muy", "este", "esta", "esto", "estos", "ese", "esa",
    "esos", "esas", "su", "sus", "al", "lo", "si", "no", "hay", "tiene",
    "tienen", "puede", "pueden", "hacer", "ser", "estar", "son", "era", "fue",
    "cuando", "donde", "porque", "pero", "tambien", "todo", "toda", "todos",
    "todas", "otro", "otra",
}

# Sufijos que en ingles no existen o son rarisimos.
#
# NO esta "sion" a proposito, y se midio: descartaba version, extension,
# compression, dimension, session, expression, decision, conversion, precision
# y vision — vocabulario central del dominio. No hace falta: en espanol
# correcto "-sion" y "-cion" SIEMPRE llevan tilde ("version", "compresion"), y
# de eso ya se encarga la regla de acentos. Sin tilde, la palabra es inglesa.
# "cion" si esta porque el ingles usa "-tion", nunca "-cion".
#
# "ando"/"endo" pillan de rebote "commando" y "crescendo"; se aceptan porque
# los gerundios espanoles ("generando", "usando") son mucho mas probables en
# una pregunta que esas dos.
_SUFIJOS_ES = (
    "cion", "miento", "dad", "tad", "eza", "anza", "aje", "mente", "ncia",
    "ando", "endo", "arlo", "arla", "arlos", "arlas", "arse", "idad",
)

_ACENTOS_ES = "áéíóúüñ"


def _parece_espanol(t: str) -> bool:
    """
    True solo con senales FUERTES de que el token es espanol.

    Se usa como lista NEGRA. Antes habia una lista blanca ("descarto lo que no
    reconozco") y medía al reves de lo que hacia falta: descartaba lo
    ESPECIFICO y conservaba lo GENERICO, porque los terminos tecnicos concretos
    son largos y no estaban en el diccionario, mientras que la regla de "4
    letras o menos" dejaba pasar las palabras cortas y comunes.

    Medido el 2026-07-20, antes del cambio:
        "rust ownership"            -> query 'rust'         (perdio ownership)
        "python asyncio event loop" -> query 'python loop'  (perdio asyncio)
        "rust ownership borrow checker data races" -> 'rust data'

    Con la lista negra, un termino tecnico ingles que no conocemos PASA, que es
    lo correcto: el vocabulario tecnico no cabe en ningun diccionario. Solo se
    descarta lo que se reconoce como espanol y no se sabe traducir, porque
    colarlo garantiza cero resultados (las APIs hacen AND de todos los
    terminos).
    """
    t = t.lower()
    if any(c in t for c in _ACENTOS_ES):
        return True
    if t in _FUNCIONALES_ES:
        return True
    return t.endswith(_SUFIJOS_ES)


def _es_tecnico(t: str) -> bool:
    """
    True si el token vale como termino de busqueda en ingles tal cual.

    Lo conocido pasa por lista; lo desconocido pasa salvo que parezca espanol.
    """
    if t in TECNICOS or t in DOMINIO_EN or any(c.isdigit() for c in t):
        return True
    return not _parece_espanol(t)


def _traducir(terminos: List[str]) -> List[str]:
    """
    Pasa al ingles lo que se pueda y DESCARTA lo que no se reconozca.

    Antes se dejaba pasar el resto sin tocar, y eso metia espanol crudo en las
    queries. Medido el 2026-07-19: "agentes de coding por linea de comandos"
    producia 'caracteristicas comandos implementarlas'. GitHub y HuggingFace
    hacen AND de todos los terminos, asi que una sola palabra en espanol basta
    para garantizar cero resultados: colar el termino es PEOR que perderlo.

    Es lista blanca a proposito. Si el vocabulario no cubre el dominio, la
    query sale corta pero en ingles; antes salia larga y en espanol, que no
    encuentra nada y ademas lo disimula.
    """
    salida = []
    for t in terminos:
        traducido = GLOSARIO.get(t)
        if traducido is None:
            if not _es_tecnico(t):
                continue          # no se sabe decirlo en ingles: fuera
            traducido = t
        if traducido not in salida:
            salida.append(traducido)
    return salida


def _nucleo(terminos: List[str]) -> List[str]:
    """
    Los terminos mas informativos, en el orden en que venian.

    'Informativo' NO es 'largo': con la pregunta real del dueño, ordenar por
    longitud se quedaba con 'maximum context posible' — colaba un relleno en
    espanol sin traducir y tiraba 'model', que es el sustantivo central.

    Ordenar solo por orden de aparicion tampoco basta: se quedaba con
    'model small maximum' y perdia 'context'. Lo que hace falta es llevar de
    los dos tipos — sustantivos (que se busca) y modificadores (como es) —
    tomando los primeros de cada uno, que en ambos idiomas suelen ser los
    centrales de la pregunta.
    """
    sustantivos   = [t for t in terminos if t in NUCLEOS_EN][:NUCLEO_SUSTANTIVOS]
    modificadores = [t for t in terminos if t in MODIFICADORES_EN][:NUCLEO_MODIFICADORES]
    elegidos = set(sustantivos + modificadores)

    # Los que no estan en ninguna de las dos listas. Son los que MAS informan:
    # un termino tecnico concreto (ownership, asyncio, borrow) no cabe en un
    # vocabulario cerrado, mientras que los que si estan suelen ser genericos
    # (model, code, tool). Antes se descartaban en cuanto hubiera UN solo
    # termino conocido: de ['rust', 'ownership', 'memory'] salia 'memory',
    # tirando los dos que hacian la pregunta especifica.
    desconocidos = [t for t in terminos if t not in DOMINIO_EN]

    if not elegidos:
        # Sin vocabulario conocido, los mas largos: en este dominio la palabra
        # larga es la especifica.
        elegidos = set(sorted(terminos, key=len, reverse=True)[:NUCLEO_MAX])
    else:
        # Completar hasta NUCLEO_MAX con los especificos, sin desplazar a los
        # conocidos que ya entraron.
        for t in desconocidos:
            if len(elegidos) >= NUCLEO_MAX:
                break
            elegidos.add(t)

    return [t for t in terminos if t in elegidos]


def terminos_de_busqueda(pregunta: str) -> List[str]:
    """
    Terminos de la pregunta traducidos al ingles, para PUNTUAR resultados.

    Existe porque puntuar una pregunta en espanol contra resultados en ingles
    da cobertura cero en todo, y entonces el desempate por popularidad pasa a
    ser el unico criterio. Medido: con la pregunta del dueño en espanol, el
    resultado mejor puntuado de GitHub era 'china-dictatorship' (3106
    estrellas), que no tiene nada que ver.
    """
    return _traducir(tokenizar(pregunta))


def planificar_deterministico(pregunta: str, n: int = 5) -> List[str]:
    """
    Descompone la pregunta sin usar LLM.

    'modelo pequeno que maneje el maximo contexto posible'
        -> ['small maximum context', 'small maximum benchmark evaluation',
            'small maximum implementation', ...]
    """
    terminos = _traducir(tokenizar(pregunta))
    if not terminos:
        return []

    nucleo  = _nucleo(terminos)
    queries = [" ".join(nucleo)]

    # Para las facetas se usan menos terminos del nucleo: la faceta ya aporta
    # dos palabras y el AND de la API no perdona.
    base = " ".join(nucleo[:2])
    for faceta in _facetas_para(terminos):
        if len(queries) >= n:
            break
        queries.append(f"{base} {faceta}")

    return queries[:n]


def _pedir_al_llm(pregunta: str, n: int) -> List[str]:
    """Le pide queries al LLM local. Devuelve [] si no hay o si responde basura."""
    prompt = (
        f"Break this research question into {n} distinct English search queries "
        f"for GitHub and HuggingFace.\n\n"
        f"Question: {pregunta}\n\n"
        f"Rules:\n"
        f"- Each query must be 2 to 5 words. Longer queries return zero results.\n"
        f"- EVERY query must name the THING being asked about. If the question "
        f"asks about coding agents, every query must contain 'agent' or a "
        f"concrete agent name. Dropping the subject is the worst failure.\n"
        f"- Each query must cover a DIFFERENT facet of the question.\n"
        f"- Use the technical English terms practitioners actually use.\n"
        f"- Prefer how projects are catalogued: 'awesome <thing>', "
        f"'<thing> cli', '<thing> alternative'.\n"
        f"- Output ONLY the queries, one per line, no numbering, no extra text.\n\n"
        f"Example — Question: 'which open source CLI coding agents exist'\n"
        f"GOOD:\n"
        f"awesome ai coding agents\n"
        f"open source cli agent\n"
        f"terminal coding assistant\n"
        f"BAD (subject lost, finds unrelated things):\n"
        f"command line parsing\n"
        f"software development tools\n"
    )
    texto = generar(prompt, temperature=0.3, max_tokens=200)
    if not texto:
        print("[planner] Sin LLM local. Usando plan deterministico.")
        return []

    # Terminos de la pregunta que la query DEBE respetar. Sin esto el modelo
    # deriva: medido el 2026-07-19, de "mejor modelo open source para webs
    # bonitas en GPU de 16GB" saco 'GPU-accelerated rendering', que trajo
    # librerias de graficos por computador y ni un solo modelo.
    del_tema = {t for t in _traducir(tokenizar(pregunta))}

    queries, descartadas = [], []
    for linea in texto.splitlines():
        limpia = linea.strip().lstrip("-*0123456789. ").strip().strip('"')
        if not (2 <= len(limpia.split()) <= 6) or limpia.endswith(":"):
            continue
        # Debe compartir algo con la pregunta, o esta buscando otra cosa.
        propios = {p.lower().strip(".,") for p in limpia.split()}
        if del_tema and not (propios & del_tema):
            descartadas.append(limpia)
            continue
        queries.append(limpia)

    if descartadas:
        print(f"[planner] Descartadas {len(descartadas)} queries que perdian "
              f"el tema: {', '.join(descartadas[:3])}")
    return queries[:n]


def planificar_busquedas(pregunta: str, n: int = 5, usar_llm: bool = True) -> List[str]:
    """
    Convierte una pregunta en n queries de busqueda.

    Args:
        pregunta: la pregunta en lenguaje natural (espanol o ingles)
        n:        cuantas queries generar
        usar_llm: si intentar mejorarlas con el LLM local

    Returns:
        Lista de queries. Nunca vacia si la pregunta tiene alguna palabra util.
    """
    plan = planificar_deterministico(pregunta, n)

    if usar_llm:
        del_llm = _pedir_al_llm(pregunta, n)
        if del_llm:
            print(f"[planner] El LLM propuso {len(del_llm)} queries.")
            # Se mezclan: primero las del LLM, y se completan con las
            # deterministicas que no esten repetidas.
            vistas = {q.lower() for q in del_llm}
            plan = del_llm + [q for q in plan if q.lower() not in vistas]

    return plan[:n]
