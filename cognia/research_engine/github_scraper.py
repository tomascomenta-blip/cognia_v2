"""
github_scraper.py — Scraper de GitHub para investigacion masiva de Cognia.

Busca repos por query via GitHub API, descarga READMEs y devuelve
fragmentos listos para ingerir por el pipeline de aprendizaje.

Sin dependencias externas: solo stdlib (urllib, json, base64, time).

Variables de entorno:
    GITHUB_TOKEN  — token personal (opcional). Sin token: 60 req/hora.
                    Con token: 5000 req/hora.
"""

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional

GITHUB_API        = "https://api.github.com"
DEFAULT_MAX_REPOS = 5
README_MAX_CHARS  = 2500
REQUEST_TIMEOUT   = 10
# Pausa entre requests para no quemar rate limit
_REQUEST_DELAY    = 0.4


@dataclass
class RepoContent:
    repo_name:   str
    repo_url:    str
    description: str
    readme:      str
    stars:       int
    language:    str
    topics:      List[str] = field(default_factory=list)

    def to_learning_text(self) -> str:
        parts = [f"Repositorio GitHub: {self.repo_name}"]
        if self.description:
            parts.append(f"Descripcion: {self.description}")
        if self.language:
            parts.append(f"Lenguaje principal: {self.language}")
        if self.topics:
            parts.append(f"Temas: {', '.join(self.topics)}")
        if self.readme:
            parts.append(f"README:\n{self.readme}")
        return "\n\n".join(parts)

    def label(self) -> str:
        """Etiqueta compacta para episodic.store()."""
        base = self.repo_name.split("/")[-1] if "/" in self.repo_name else self.repo_name
        if self.topics:
            return f"{base} ({self.topics[0]})"
        if self.language:
            return f"{base} ({self.language})"
        return base


class GitHubScraper:
    """Scraper de GitHub sin PyTorch ni dependencias externas."""

    def __init__(self, token: str = None, max_repos: int = DEFAULT_MAX_REPOS):
        self.token     = token or os.environ.get("GITHUB_TOKEN", "")
        self.max_repos = max(1, min(max_repos, 20))
        self._rate_remaining = None

    # ── HTTP helpers ────────────────────────────────────────────────────

    def _headers(self) -> dict:
        h = {
            "Accept":     "application/vnd.github+json",
            "User-Agent": "CogniaResearch/1.0",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _get(self, url: str) -> Optional[dict]:
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                self._rate_remaining = resp.getheader("X-RateLimit-Remaining")
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print(f"[github] Rate limit alcanzado. Intenta mas tarde o configura GITHUB_TOKEN.")
            elif e.code == 404:
                pass
            else:
                print(f"[github] HTTP {e.code} en {url}")
            return None
        except Exception as exc:
            print(f"[github] Error de conexion: {exc}")
            return None

    # ── API calls ───────────────────────────────────────────────────────

    def search_repos(self, query: str) -> List[RepoContent]:
        """Busca repos por query y devuelve contenido procesado."""
        encoded = urllib.parse.quote(query)
        url     = (
            f"{GITHUB_API}/search/repositories"
            f"?q={encoded}&sort=stars&order=desc&per_page={self.max_repos}"
        )
        print(f"[github] Buscando: '{query}' (max {self.max_repos} repos)...")
        data = self._get(url)

        if not data or "items" not in data:
            return []

        total = data.get("total_count", 0)
        print(f"[github] {total} resultados encontrados. Procesando {min(self.max_repos, len(data['items']))}...")

        results = []
        for item in data["items"][: self.max_repos]:
            time.sleep(_REQUEST_DELAY)
            readme = self._fetch_readme(item["full_name"])
            content = RepoContent(
                repo_name   = item["full_name"],
                repo_url    = item.get("html_url", ""),
                description = item.get("description") or "",
                readme      = readme,
                stars       = item.get("stargazers_count", 0),
                language    = item.get("language") or "",
                topics      = item.get("topics", []),
            )
            results.append(content)
            print(f"[github] OK  {item['full_name']}  ({content.stars} stars)")

        if self._rate_remaining is not None:
            print(f"[github] Rate limit restante: {self._rate_remaining}/hora")

        return results

    def _fetch_readme(self, full_name: str) -> str:
        url  = f"{GITHUB_API}/repos/{full_name}/readme"
        data = self._get(url)
        if not data or "content" not in data:
            return ""
        try:
            raw  = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            text = raw.strip()[:README_MAX_CHARS]
            # Truncar en el ultimo salto de linea completo para no cortar a la mitad
            if len(raw.strip()) > README_MAX_CHARS and "\n" in text:
                text = text[: text.rfind("\n")].strip()
            return text
        except Exception:
            return ""
