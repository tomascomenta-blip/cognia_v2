"""
web_research.py — Investigacion de una pregunta sobre varias fuentes.

Junta las piezas: planifica las queries desde la pregunta, las corre contra
GitHub y HuggingFace, deduplica, reordena todo junto contra la pregunta
ORIGINAL (no contra la query que lo encontro) y cierra con un informe.

El scraper original terminaba volcando READMEs en memoria episodica y ya. Eso
no es una respuesta, es materia prima. Aqui la corrida termina en un informe
que se puede leer.

Sin dependencias externas: solo stdlib.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional

from ..busqueda_web import buscar
from ..lector_web import leer
from ..llm_local import generar
from .arxiv_scraper import ArxivScraper
from .juez import juzgar
from .github_scraper import GitHubScraper
from .hf_scraper import HFScraper
from .query_planner import planificar_busquedas, terminos_de_busqueda
from .relevance import cobertura, puntuar



@dataclass
class Hallazgo:
    fuente:      str          # "github" o "huggingface"
    titulo:      str
    url:         str
    resumen:     str
    popularidad: int
    relevancia:  float = 0.0
    extra:       str   = ""   # datos duros: KV cache, arquitectura, GGUF
    texto_bruto: str   = ""   # lo que se ingiere a memoria episodica

    def linea(self) -> str:
        if self.fuente == "arxiv":
            base = f"**{self.titulo}** — {self.url}"
        else:
            unidad = "estrellas" if self.fuente == "github" else "descargas"
            base = f"**{self.titulo}** ({self.popularidad} {unidad}) — {self.url}"
        if self.extra:
            base += f"\n  {self.extra}"
        if self.resumen:
            base += f"\n  {self.resumen[:200]}"
        return base


@dataclass
class Digest:
    pregunta:  str
    queries:   List[str]      = field(default_factory=list)
    hallazgos: List[Hallazgo] = field(default_factory=list)
    resumen_llm: str          = ""
    # Fuentes que matizan o contradicen a los candidatos mejor rankeados.
    # No son un veredicto: son material para que decida el humano.
    contraevidencia: List[Hallazgo] = field(default_factory=list)

    def to_markdown(self) -> str:
        lineas = [f"# Investigacion: {self.pregunta}", ""]
        lineas.append(f"Queries ejecutadas ({len(self.queries)}): "
                      + ", ".join(f"`{q}`" for q in self.queries))
        lineas.append("")

        if not self.hallazgos:
            lineas.append("Sin resultados relevantes.")
            return "\n".join(lineas)

        if self.resumen_llm:
            lineas += ["## Resumen", "", self.resumen_llm, ""]

        secciones = [
            ("huggingface", "Modelos (HuggingFace)"),
            ("arxiv",       "Evidencia (arXiv)"),
            ("github",      "Codigo (GitHub)"),
        ]
        for fuente, titulo in secciones:
            items = [h for h in self.hallazgos if h.fuente == fuente]
            if not items:
                continue
            lineas += [f"## {titulo}", ""]
            lineas += [f"{i}. {h.linea()}" for i, h in enumerate(items, 1)]
            lineas.append("")

        if self.contraevidencia:
            lineas += [
                "## Contraevidencia",
                "",
                "Fuentes que matizan o contradicen a los candidatos de arriba. "
                "NO son un veredicto: leelas y decidi vos.",
                "",
            ]
            lineas += [f"{i}. {h.linea()}" for i, h in enumerate(self.contraevidencia, 1)]
            lineas.append("")

        return "\n".join(lineas)


# Si la pregunta nombra un modelo explicitamente, HuggingFace es justo donde
# hay que mirar por mucho que las queries traigan palabras de herramientas.
_SENAL_MODELOS = {
    "model", "models", "modelo", "modelos", "llm", "gguf", "checkpoint",
    "weights", "pesos", "cuantizacion", "quantization", "vram",
}


def _busca_herramientas(textos: List[str]) -> bool:
    """
    True si lo que se busca son proyectos y no modelos.

    Reutiliza el vocabulario que ya usa el planificador para elegir facetas:
    si la pregunta habla de agentes, CLIs, servidores MCP o skills, lo que hay
    que mirar es GitHub, no un hub de pesos.

    Los modelos mandan sobre las herramientas. Medido el 2026-07-20: la
    pregunta "mejor MODELO open source para webs bonitas en GPU de 16GB"
    derivo queries con "generators" y "tools", se salto HuggingFace, y con ello
    justo el sitio donde vive la respuesta. Si se nombra un modelo, se mira.
    """
    from .query_planner import SENAL_HERRAMIENTAS

    palabras = {p.strip(".,:;()").lower()
                for t in textos for p in t.split()}

    if palabras & _SENAL_MODELOS:
        return False
    return bool(palabras & SENAL_HERRAMIENTAS)


# Cuantas paginas del top se leen enteras antes de resumir. Cada lectura
# cuesta una peticion y ~2000 chars de contexto; 3 cubre el podio sin comerse
# la ventana de 8k del modelo.
LECTURAS_TOP = 3


def _leer_top(hallazgos: List[Hallazgo], pregunta: str = "",
              n: int = LECTURAS_TOP) -> str:
    """
    Lee las paginas de los n mejores hallazgos y devuelve extractos.

    Es la diferencia entre resumir TITULOS y resumir FUENTES: hasta ahora el
    resumidor veia una linea por hallazgo (titulo + descripcion de catalogo) y
    de ahi no puede salir una respuesta con sustancia. Los hallazgos ya
    pasaron por el juez, asi que leer el top no es leer ruido.

    Relevante NO es lo mismo que confiable: el juez puntua si la pagina
    RESPONDE, no si trae instrucciones inyectadas. Cualquier pagina rankeada
    puede traer un "ignore all previous instructions" y esta era la unica
    via de la casa que lo metia crudo al prompt del resumidor. El centinela
    web (sentinel.evaluar_contenido_web, determinista, cero LLM) sanea cada
    texto y descarta CON LOG lo que no sea 'allow' — mismo patron que
    knowledge/navegador.buscar_en_web.
    """
    from ..agent.sentinel import ALLOW, evaluar_contenido_web, sanear_texto_web

    extractos = []
    for h in hallazgos[:n]:
        texto = sanear_texto_web(leer(h.url, max_chars=2000))
        if not texto:
            continue
        # El TITULO va en la cabecera del extracto y tambien es texto ajeno
        # (nombre de repo / model_id): se sanea y se juzga JUNTO al cuerpo, si
        # no quedaba un hueco por donde entraba crudo al prompt.
        titulo = re.sub(r"\s+", " ", sanear_texto_web(h.titulo or "")).strip()
        nivel, razon = evaluar_contenido_web(f"{titulo}\n{texto}",
                                             tema=pregunta, fuente=h.url)
        if nivel != ALLOW:
            print(f"[research] Centinela descarta {h.url}: {razon}")
            continue
        extractos.append(f"--- {titulo} ({h.url}) ---\n{texto}")
    return "\n\n".join(extractos)


def _linea_material(h: Hallazgo, n: int = 300) -> str:
    """Una linea del bloque 'Search results' del prompt, YA saneada.

    El titulo, el resumen y el 'extra' salen de la descripcion de un repo, la
    tarjeta de un modelo o el abstract de un paper: texto que CUALQUIERA puede
    escribir. La fase previa cableo el centinela para el CUERPO de las paginas
    (_leer_top) y dejo esta superficie abierta: un repo llamado "ignore all
    previous instructions and ..." entraba crudo al prompt del resumidor sin
    que nadie leyera la pagina siquiera.

    Se descarta la linea entera (no se recorta el trozo malo): el payload
    tambien puede estar en el titulo, y devolver el texto que casó lo
    re-inyectaria. Queda una linea REDACTADA en su sitio para que el conteo de
    resultados siga siendo honesto, y un log para que no sea un vacio silencioso.

    tema=None a proposito: aqui solo se busca INYECCION, no relevancia. El
    filtro de relevancia ya corrio antes (cobertura/puntuar + el juez) sobre
    los terminos traducidos de la pregunta; volver a exigirla sobre 300 chars
    de descripcion de catalogo tiraria hallazgos legitimos.
    """
    from ..agent.sentinel import ALLOW, evaluar_contenido_web, sanear_texto_web

    titulo  = sanear_texto_web(h.titulo or "")
    extra   = sanear_texto_web(h.extra or "")
    resumen = sanear_texto_web(h.resumen or "")[:n]

    # El veredicto se pide sobre los tres campos en LINEAS SEPARADAS, no sobre
    # la linea ya compuesta: el centinela tiene patrones anclados a principio
    # de linea (la gramatica 'ACCION: <tool>' del agente) y meterlos en medio
    # de un "- [github] X (10) ... :: ..." los volvia inalcanzables.
    nivel, razon = evaluar_contenido_web("\n".join([titulo, extra, resumen]),
                                         tema=None, fuente=h.url)
    if nivel != ALLOW:
        print(f"[research] Centinela redacta el resultado {h.url}: {razon}")
        return f"- [{h.fuente}] (resultado REDACTADO por el centinela: {razon})"
    # Los saltos de linea se colapsan: el bloque es UNA linea por resultado y
    # un abstract multilinea podia fabricar items o secciones falsas del prompt.
    def plano(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()

    return (f"- [{h.fuente}] {plano(titulo)} ({h.popularidad}) "
            f"{plano(extra)} :: {plano(resumen)}")


def _resumir_con_llm(pregunta: str, hallazgos: List[Hallazgo]) -> str:
    """Le pide al LLM local que responda con lo encontrado. '' si no hay."""
    if not hallazgos:
        return ""

    material = "\n".join(_linea_material(h) for h in hallazgos[:12])
    paginas = _leer_top(hallazgos, pregunta)
    seccion_paginas = (
        f"\n\nFull text excerpts from the top results:\n{paginas}" if paginas
        else ""
    )
    prompt = (
        f"Question: {pregunta}\n\n"
        f"Search results:\n{material}"
        f"{seccion_paginas}\n\n"
        f"Answer the question in 4-6 sentences using ONLY these results. "
        f"Prefer facts from the full text excerpts over the one-line "
        f"descriptions. Name the specific models or repos that matter and "
        f"say why. If the results do not answer the question, say so "
        f"plainly. Answer in the same language as the question."
    )
    return generar(prompt, temperature=0.4, max_tokens=500) or ""


# Angulos de contra-busqueda. Cada uno apunta a donde suelen publicarse los
# limites de algo: la seccion de limitaciones de un paper, un benchmark que lo
# mide de verdad, o el issue de alguien a quien no le funciono.
ANGULOS_CONTRA = ["limitations", "benchmark evaluation", "issues problems"]

# Cuantos candidatos se contra-buscan. Bajo a proposito: cada uno cuesta una
# peticion con 3 s de cortesia a arXiv.
CONTRA_TOP_N = 3


def buscar_contraevidencia(
    candidatos: List[str],
    max_por_candidato: int = 2,
) -> List[Hallazgo]:
    """
    Busca fuentes que MATICEN O CONTRADIGAN a cada candidato.

    Deliberadamente NO emite veredictos. Refutar es la tarea de razonamiento
    mas dificil del pipeline y es donde los modelos pequenos fallan peor:
    tienden a estar de acuerdo con lo que se les muestra. Un refutador
    respaldado por llama3.2 no seria verificacion mediocre, seria PEOR que no
    tener nada, porque pondria un sello de 'verificado' sobre lo no
    comprobado. Esto busca el material en contra y te lo pone delante; el
    juicio queda en el humano.

    Corre solo sobre arXiv: es donde se publican las limitaciones, y es la
    unica de las tres fuentes sin limite duro de peticiones.

    Funciona con candidatos que EXISTEN en la literatura — familias de
    modelos, arquitecturas, tecnicas. Medido: para 'Mamba state space model'
    devuelve 'The Computational Limits of State-Space Models and Mamba via
    the Lens of Circuit Complexity'; para un repo de 13 estrellas devuelve
    vacio. Ese vacio es la respuesta CORRECTA, no un fallo: nadie publico un
    paper sobre ese repo, y devolver algo seria inventar contraevidencia.
    """
    if not candidatos:
        return []

    ax    = ArxivScraper(max_papers=max_por_candidato)
    vistos = {}

    for nombre in candidatos[:CONTRA_TOP_N]:
        # Un solo angulo por candidato: mas seria pagar 3 s por cada uno.
        angulo = ANGULOS_CONTRA[0]
        print(f"[contra] Buscando limites de: {nombre}")
        for p in ax.search_papers(f"{nombre} {angulo}"):
            if p.url in vistos:
                continue
            vistos[p.url] = Hallazgo(
                fuente      = "arxiv",
                titulo      = p.titulo,
                url         = p.url,
                resumen     = p.abstract,
                popularidad = 0,
                extra       = f"contra: {nombre}",
                texto_bruto = p.to_learning_text(),
            )

    return list(vistos.values())


def investigar(
    pregunta:        str,
    n_queries:       int  = 4,
    max_por_fuente:  int  = 4,
    usar_github:     bool = True,
    usar_hf:         bool = True,
    usar_arxiv:      bool = True,
    usar_web:        bool = True,
    usar_llm:        bool = True,
    con_contra:      bool = True,
) -> Digest:
    """
    Investiga una pregunta sobre GitHub y HuggingFace y devuelve un informe.

    Args:
        pregunta:       pregunta en lenguaje natural
        n_queries:      cuantas queries derivar de la pregunta
        max_por_fuente: cuantos resultados traer por query y fuente
        usar_github:    consultar GitHub
        usar_hf:        consultar HuggingFace
        usar_arxiv:     consultar arXiv (lento: 3 s de cortesia por peticion)
        usar_web:       consultar Wikipedia y HackerNews (busqueda_web). Es lo
                        que da respuesta a preguntas abiertas: GitHub y HF son
                        catalogos, saben de repos y modelos, no de conceptos
        usar_llm:       usar el LLM local para planificar y resumir si esta disponible
        con_contra:     buscar evidencia EN CONTRA de los candidatos fuertes

    Returns:
        Digest con las queries, los hallazgos ordenados, la contraevidencia y,
        si hubo LLM, el resumen.
    """
    queries = planificar_busquedas(pregunta, n=n_queries, usar_llm=usar_llm)
    if not queries:
        return Digest(pregunta=pregunta)

    print(f"[research] Plan: {queries}")

    # HuggingFace es un hub de MODELOS. Preguntarle por agentes, servidores MCP
    # o skills casa por palabras sueltas y devuelve ruido casi puro. Medido el
    # 2026-07-20 sobre las 5 investigaciones de la noche:
    #   "skills de agentes"  -> lm-ner-linkedin-skills-recognition,
    #                           job-skills_unsloth-tinyllama (competencias
    #                           laborales, otro significado de "skills")
    #   "MCP sin registro"   -> pocket-tts-without-voice-cloning (caso con
    #                           "without")
    #   "agentes CLI"        -> my_awesome_opus_books_model (un tutorial)
    # Y encima esos hallazgos ocupan sitio entre los 12 que ve el resumidor.
    # Para preguntas de herramientas se salta: cuesta tiempo y ensucia.
    if usar_hf and _busca_herramientas(queries + [pregunta]):
        print("[research] Pregunta de herramientas: me salto HuggingFace "
              "(es un hub de modelos, aqui solo aporta ruido).")
        usar_hf = False

    por_url = {}

    if usar_hf:
        hf = HFScraper(max_models=max_por_fuente)
        for q in queries:
            for m in hf.search_models(q):
                if m.model_url in por_url:
                    continue
                kv = m.kv_bytes_por_token()
                extra = []
                arq = m.arquitectura()
                if arq:
                    extra.append(arq)
                ctx = m.contexto_declarado()
                if ctx:
                    extra.append(f"ctx {ctx}")
                if kv:
                    extra.append(f"KV {kv} B/tok ({m.kv_gb(131072):.2f} GB @128k)")
                if m.tiene_gguf():
                    extra.append("GGUF")

                por_url[m.model_url] = Hallazgo(
                    fuente      = "huggingface",
                    titulo      = m.model_id,
                    url         = m.model_url,
                    resumen     = m.descripcion,
                    popularidad = m.downloads,
                    extra       = " | ".join(extra),
                    texto_bruto = m.to_learning_text(),
                )

    if usar_arxiv:
        ax = ArxivScraper(max_papers=max_por_fuente)
        for q in queries:
            for p in ax.search_papers(q):
                if p.url in por_url:
                    continue
                extra = []
                if p.anio():
                    extra.append(p.anio())
                if p.categorias:
                    extra.append(p.categorias[0])
                por_url[p.url] = Hallazgo(
                    fuente      = "arxiv",
                    titulo      = p.titulo,
                    url         = p.url,
                    resumen     = p.abstract,
                    popularidad = 0,
                    extra       = " | ".join(extra),
                    texto_bruto = p.to_learning_text(),
                )

    # Wikipedia y HackerNews. NO se le pide arxiv aunque busqueda_web lo
    # tenga: el ArxivScraper de aqui da abstract, ano y categorias, que es
    # mejor, y pedir las dos duplicaria resultados.
    if usar_web:
        for q in queries:
            try:
                for r in buscar(q, max_por_fuente,
                                fuentes=("wikipedia", "hackernews")):
                    if r["url"] in por_url:
                        continue
                    por_url[r["url"]] = Hallazgo(
                        fuente      = r["fuente"],
                        titulo      = r["titulo"],
                        url         = r["url"],
                        resumen     = r["fragmento"],
                        # Ni Wikipedia ni HN dan una metrica comparable con
                        # estrellas o descargas. puntuar() usa popularidad, y
                        # un 0 honesto es mejor que un numero inventado.
                        popularidad = 0,
                        extra       = "",
                        texto_bruto = r["fragmento"],
                    )
            except Exception as e:
                # Una fuente de red que falla no puede tumbar una
                # investigacion que ya tiene resultados de GitHub y arXiv.
                print(f"[research] Error en fuentes web para '{q}': {e}")

    if usar_github:
        gh = GitHubScraper(max_repos=max_por_fuente)
        for q in queries:
            for r in gh.search_repos(q):
                if r.repo_url in por_url:
                    continue
                por_url[r.repo_url] = Hallazgo(
                    fuente      = "github",
                    titulo      = r.repo_name,
                    url         = r.repo_url,
                    resumen     = r.description,
                    popularidad = r.stars,
                    extra       = r.language,
                    texto_bruto = r.to_learning_text(),
                )

    # Reordenar TODO contra la pregunta original. Un resultado puede haber
    # entrado por una query de faceta, o por una query degradada a un solo
    # termino generico, y ser marginal para la pregunta real.
    # Los terminos van TRADUCIDOS: la pregunta puede venir en espanol y los
    # resultados siempre estan en ingles.
    terminos  = terminos_de_busqueda(pregunta)
    hallazgos = []
    for h in por_url.values():
        texto = f"{h.titulo} {h.resumen} {h.extra}"
        # Cobertura cero = no matcheo ni un termino de la pregunta. Es lo que
        # coloca repos populares y ajenos arriba; se descarta directamente.
        if terminos and cobertura(terminos, texto) == 0.0:
            continue
        h.relevancia = puntuar(terminos, texto, h.popularidad)
        hallazgos.append(h)

    hallazgos.sort(key=lambda h: h.relevancia, reverse=True)

    # El juicio de relevancia: el ranking lexico ordena por coincidencia de
    # palabras, y eso deja pasar homonimos ("Bernhard Rust", un politico, en
    # una pregunta sobre el lenguaje). El juez le pregunta al LLM si cada
    # hallazgo del top RESPONDE a la pregunta, y hunde los que no. Va antes de
    # la contraevidencia a proposito: contra-buscar candidatos que el juez
    # habria hundido es gastar las peticiones de arXiv en ruido.
    if usar_llm:
        hallazgos = juzgar(pregunta, hallazgos)

    digest = Digest(pregunta=pregunta, queries=queries, hallazgos=hallazgos)

    if con_contra:
        # Se contra-buscan los candidatos concretos (modelos y repos), no los
        # papers: un paper ya ES evidencia, y buscar 'limitaciones de un
        # paper' devuelve ruido.
        candidatos = [
            h.titulo.split("/")[-1]
            for h in hallazgos
            if h.fuente in ("huggingface", "github")
        ]
        digest.contraevidencia = buscar_contraevidencia(candidatos)

    if usar_llm:
        digest.resumen_llm = _resumir_con_llm(pregunta, hallazgos)
    return digest
