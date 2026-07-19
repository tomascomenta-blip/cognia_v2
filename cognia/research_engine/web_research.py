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

import json
import urllib.request as _req
from dataclasses import dataclass, field
from typing import List, Optional

from .github_scraper import GitHubScraper
from .hf_scraper import HFScraper
from .query_planner import planificar_busquedas, terminos_de_busqueda
from .relevance import cobertura, puntuar

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2"
TIMEOUT_SEC  = 60


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

        de_hf = [h for h in self.hallazgos if h.fuente == "huggingface"]
        de_gh = [h for h in self.hallazgos if h.fuente == "github"]

        if de_hf:
            lineas += ["## Modelos (HuggingFace)", ""]
            lineas += [f"{i}. {h.linea()}" for i, h in enumerate(de_hf, 1)]
            lineas.append("")
        if de_gh:
            lineas += ["## Codigo (GitHub)", ""]
            lineas += [f"{i}. {h.linea()}" for i, h in enumerate(de_gh, 1)]
            lineas.append("")

        return "\n".join(lineas)


def _resumir_con_ollama(pregunta: str, hallazgos: List[Hallazgo]) -> str:
    """Le pide a Ollama que responda la pregunta con lo encontrado. '' si no esta."""
    if not hallazgos:
        return ""

    material = "\n".join(
        f"- [{h.fuente}] {h.titulo} ({h.popularidad}) {h.extra} :: {h.resumen[:300]}"
        for h in hallazgos[:12]
    )
    prompt = (
        f"Question: {pregunta}\n\n"
        f"Search results:\n{material}\n\n"
        f"Answer the question in 4-6 sentences using ONLY these results. "
        f"Name the specific models or repos that matter and say why. "
        f"If the results do not answer the question, say so plainly. "
        f"Answer in the same language as the question."
    )
    try:
        payload = json.dumps({
            "model":  OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.4, "num_predict": 500},
        }).encode("utf-8")
        req = _req.Request(OLLAMA_URL, data=payload,
                           headers={"Content-Type": "application/json"})
        with _req.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            return json.loads(resp.read()).get("response", "").strip()
    except Exception as exc:
        print(f"[research] Ollama no disponible para el resumen ({exc}).")
        return ""


def investigar(
    pregunta:        str,
    n_queries:       int  = 4,
    max_por_fuente:  int  = 4,
    usar_github:     bool = True,
    usar_hf:         bool = True,
    usar_llm:        bool = True,
) -> Digest:
    """
    Investiga una pregunta sobre GitHub y HuggingFace y devuelve un informe.

    Args:
        pregunta:       pregunta en lenguaje natural
        n_queries:      cuantas queries derivar de la pregunta
        max_por_fuente: cuantos resultados traer por query y fuente
        usar_github:    consultar GitHub
        usar_hf:        consultar HuggingFace
        usar_llm:       usar Ollama para planificar y resumir si esta levantado

    Returns:
        Digest con las queries, los hallazgos ordenados y, si hubo LLM, el resumen.
    """
    queries = planificar_busquedas(pregunta, n=n_queries, usar_llm=usar_llm)
    if not queries:
        return Digest(pregunta=pregunta)

    print(f"[research] Plan: {queries}")

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

    digest = Digest(pregunta=pregunta, queries=queries, hallazgos=hallazgos)
    if usar_llm:
        digest.resumen_llm = _resumir_con_ollama(pregunta, hallazgos)
    return digest
