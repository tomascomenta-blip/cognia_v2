import urllib.request, urllib.parse, json, time


class WebSearch:
    """
    Wrapper de DuckDuckGo Instant Answer API.
    Sin API key. Timeout 5s. Resultados cacheados 10min en memoria.
    """

    _DDGO_URL = "https://api.duckduckgo.com/"
    _TIMEOUT = 5
    # Tope de entradas vivas en el cache. Sin tope, el dict crecia sin limite
    # en procesos largos (la desktop API mantiene UNA instancia global).
    _CACHE_MAX = 128

    def __init__(self):
        self._cache: dict = {}  # {query_lower: (result, timestamp)}
        self._cache_ttl = 600  # 10 min

    def search(self, query: str, max_results: int = 5) -> dict:
        """
        Retorna:
        {
          "query": str,
          "abstract": str,        # respuesta directa si existe
          "abstract_source": str, # fuente (Wikipedia, etc.)
          "related_topics": list[str],  # hasta max_results topicos relacionados
          "answer": str,          # respuesta instantanea (ej: "2+2 = 4")
          "cached": bool,
          "error": str | None
        }
        """
        query_lower = query.lower().strip()

        # Check cache
        if query_lower in self._cache:
            result, ts = self._cache[query_lower]
            if time.time() - ts < self._cache_ttl:
                result = dict(result)
                result["cached"] = True
                return result

        try:
            params = urllib.parse.urlencode({
                "q": query,
                "format": "json",
                "no_html": "1",
                "skip_disambig": "1"
            })
            url = f"{self._DDGO_URL}?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "Cognia/3.0"})
            with urllib.request.urlopen(req, timeout=self._TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            result = self._parse_response(data, max_results)
            # La Instant Answer API NO es un buscador: ante una consulta tecnica
            # devuelve abstract vacio, 0 RelatedTopics y 0 Results, y hasta hoy
            # eso salia como exito con error=None -> /buscar-web imprimia
            # "(Sin resultados)" y el tool_router devolvia {} sin avisar de nada.
            # (Medido 2026-07-24: 0/3 consultas tecnicas utiles. El repo YA lo
            # habia documentado en cognia_v3/core/investigador.py y la leccion
            # nunca habia llegado hasta aca.)
            # Cuando eso pasa, se cae al buscador DE VERDAD del repo
            # (cognia.busqueda_web: Wikipedia + HackerNews + arXiv).
            if not self._util(result):
                real = self._buscar_de_verdad(query, max_results)
                if real is not None:
                    result = real
            self._prune_cache()
            self._cache[query_lower] = (result, time.time())
            return result

        except Exception as e:
            return {
                "query": query, "abstract": "", "abstract_source": "",
                "related_topics": [], "answer": "", "cached": False,
                "error": str(e)[:200]
            }

    @staticmethod
    def _util(result: dict) -> bool:
        """True si la respuesta trae ALGO que el llamador pueda usar."""
        return bool((result.get("abstract") or "").strip()
                    or result.get("related_topics")
                    or (result.get("answer") or "").strip())

    def _buscar_de_verdad(self, query: str, max_results: int):
        """El buscador real del repo (Wikipedia + HackerNews + arXiv), servido
        con el MISMO contrato de salida para no tocar a quien ya nos llama.

        Devuelve None si tampoco hay nada, para que el caller conserve el
        resultado vacio original (pero ahora con `error` explicando el porque,
        en vez de un exito silencioso).
        """
        try:
            from cognia.busqueda_web import buscar
            hits = buscar(query, max_resultados=max_results) or []
        except Exception as e:
            return {"query": query, "abstract": "", "abstract_source": "",
                    "related_topics": [], "answer": "", "cached": False,
                    "error": f"instant answer vacio y el buscador real fallo: {e}"[:200]}
        if not hits:
            return {"query": query, "abstract": "", "abstract_source": "",
                    "related_topics": [], "answer": "", "cached": False,
                    "error": "sin resultados (instant answer vacio y el buscador real tampoco encontro)"}
        primero = hits[0]
        return {
            "query": query,
            "abstract": (primero.get("fragmento") or "").strip(),
            "abstract_source": primero.get("fuente") or primero.get("url") or "",
            "related_topics": [f"{h.get('titulo', '')}: {h.get('url', '')}".strip(": ")
                               for h in hits[:max_results]],
            "answer": "",
            "cached": False,
            "error": None,
        }

    def _parse_response(self, data: dict, max_results: int) -> dict:
        abstract = data.get("AbstractText", "") or data.get("Abstract", "")
        abstract_source = data.get("AbstractSource", "")
        answer = data.get("Answer", "")

        related = []
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                related.append(topic["Text"][:150])

        return {
            "query": data.get("Heading", ""),
            "abstract": abstract[:500] if abstract else "",
            "abstract_source": abstract_source,
            "related_topics": related,
            "answer": answer[:200] if answer else "",
            "cached": False,
            "error": None
        }

    def _prune_cache(self) -> None:
        """Mantiene el cache acotado antes de insertar una entrada nueva.

        1) Expira las entradas vencidas (>_cache_ttl); antes quedaban en el
           dict para siempre porque el TTL solo se miraba al LEER esa clave.
        2) Si aun asi hay >= _CACHE_MAX vivas, vacia todo con clear_cache()
           (las vivas se rehidratan solas al proximo search; mas simple y
           honesto que un LRU para un cache de 10 minutos).
        """
        if len(self._cache) < self._CACHE_MAX:
            return
        now = time.time()
        vencidas = [k for k, (_, ts) in self._cache.items()
                    if now - ts >= self._cache_ttl]
        for k in vencidas:
            del self._cache[k]
        if len(self._cache) >= self._CACHE_MAX:
            self.clear_cache()

    def clear_cache(self) -> None:
        self._cache.clear()
