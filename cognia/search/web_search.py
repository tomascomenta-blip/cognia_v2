import urllib.request, urllib.parse, json, time


class WebSearch:
    """
    Wrapper de DuckDuckGo Instant Answer API.
    Sin API key. Timeout 5s. Resultados cacheados 10min en memoria.
    """

    _DDGO_URL = "https://api.duckduckgo.com/"
    _TIMEOUT = 5

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
            self._cache[query_lower] = (result, time.time())
            return result

        except Exception as e:
            return {
                "query": query, "abstract": "", "abstract_source": "",
                "related_topics": [], "answer": "", "cached": False,
                "error": str(e)[:200]
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

    def clear_cache(self) -> None:
        self._cache.clear()
