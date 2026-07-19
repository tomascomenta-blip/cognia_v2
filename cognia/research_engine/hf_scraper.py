"""
hf_scraper.py — Scraper de HuggingFace para investigacion de Cognia.

Hermano de github_scraper.py: misma forma, otra fuente. GitHub tiene el codigo,
HuggingFace tiene los modelos, y para preguntas sobre modelos GitHub solo
devuelve tutoriales de despliegue y forks.

Ademas del model card baja el config.json, que es donde estan los numeros de
arquitectura de verdad (capas, cabezas KV, dimension). Con esos numeros calcula
los bytes de KV cache por token, que es lo que decide cuanto contexto entra en
una maquina concreta.

Sin dependencias externas: solo stdlib (urllib, json, time).

Variables de entorno:
    HF_TOKEN — token de HuggingFace (opcional). Sin token la API publica
               funciona igual, pero con limites mas bajos y sin repos gated.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional

from .relevance import degradar_query, filtrar_y_ordenar

HF_API             = "https://huggingface.co/api"
HF_HOST            = "https://huggingface.co"
DEFAULT_MAX_MODELS = 5
CARD_MAX_CHARS     = 2500
REQUEST_TIMEOUT    = 15
_REQUEST_DELAY     = 0.3

# Cuantos candidatos pedir a la API antes de filtrar por relevancia. Se pide de
# mas porque el filtro descarta ruido y si no nos quedariamos cortos.
_FACTOR_SOBREMUESTREO = 4


@dataclass
class ModelContent:
    model_id:     str
    model_url:    str
    author:       str
    descripcion:  str
    card:         str
    downloads:    int
    likes:        int
    pipeline_tag: str
    tags:         List[str]      = field(default_factory=list)
    config:       dict           = field(default_factory=dict)
    archivos:     List[str]      = field(default_factory=list)

    # ── Datos derivados del config.json ─────────────────────────────────

    def tiene_gguf(self) -> bool:
        return any(f.lower().endswith(".gguf") for f in self.archivos)

    def kv_bytes_por_token(self, bytes_por_valor: int = 2) -> Optional[int]:
        """
        Bytes de KV cache por token de contexto, en fp16 por defecto.

            capas x cabezas_kv x dim_cabeza x 2 (K y V) x bytes_por_valor

        Es la cifra que decide cuanto contexto entra en memoria. Devuelve None
        si el config no trae los campos (pasa con arquitecturas SSM/hibridas,
        donde ademas esta formula no aplica igual).
        """
        cfg = self.config
        if not cfg:
            return None

        capas = cfg.get("num_hidden_layers") or cfg.get("n_layer")
        if not capas:
            return None

        cabezas_attn = cfg.get("num_attention_heads") or cfg.get("n_head")
        cabezas_kv   = cfg.get("num_key_value_heads") or cabezas_attn
        if not cabezas_kv:
            return None

        dim_cabeza = cfg.get("head_dim")
        if not dim_cabeza:
            oculto = cfg.get("hidden_size") or cfg.get("n_embd")
            if not (oculto and cabezas_attn):
                return None
            dim_cabeza = oculto // cabezas_attn

        return int(capas) * int(cabezas_kv) * int(dim_cabeza) * 2 * bytes_por_valor

    def kv_gb(self, tokens: int, bytes_por_valor: int = 2) -> Optional[float]:
        """GB de KV cache para una ventana de N tokens."""
        por_token = self.kv_bytes_por_token(bytes_por_valor)
        if por_token is None:
            return None
        return por_token * tokens / (1024 ** 3)

    def contexto_declarado(self) -> Optional[int]:
        cfg = self.config
        return cfg.get("max_position_embeddings") or cfg.get("n_positions")

    def arquitectura(self) -> str:
        """Resumen legible de la arquitectura, sacado del config."""
        cfg = self.config
        if not cfg:
            return ""

        partes = []
        arqs = cfg.get("architectures")
        if arqs:
            partes.append(arqs[0])

        cabezas_attn = cfg.get("num_attention_heads")
        cabezas_kv   = cfg.get("num_key_value_heads")
        if cabezas_attn and cabezas_kv:
            if cabezas_kv == cabezas_attn:
                partes.append("MHA")
            elif cabezas_kv == 1:
                partes.append("MQA")
            else:
                partes.append(f"GQA {cabezas_attn}:{cabezas_kv}")

        if cfg.get("sliding_window"):
            partes.append(f"ventana deslizante {cfg['sliding_window']}")
        if cfg.get("num_experts") or cfg.get("num_local_experts"):
            n = cfg.get("num_experts") or cfg.get("num_local_experts")
            activos = cfg.get("num_experts_per_tok")
            partes.append(f"MoE {n} expertos" + (f", {activos} activos" if activos else ""))

        capas = cfg.get("num_hidden_layers")
        if capas:
            partes.append(f"{capas} capas")

        return ", ".join(partes)

    # ── Interfaz que espera el pipeline de aprendizaje ──────────────────

    def to_learning_text(self) -> str:
        partes = [f"Modelo HuggingFace: {self.model_id}"]
        if self.descripcion:
            partes.append(f"Descripcion: {self.descripcion}")
        if self.pipeline_tag:
            partes.append(f"Tarea: {self.pipeline_tag}")

        arq = self.arquitectura()
        if arq:
            partes.append(f"Arquitectura: {arq}")

        ctx = self.contexto_declarado()
        if ctx:
            partes.append(f"Contexto declarado: {ctx} tokens")

        kv = self.kv_bytes_por_token()
        if kv:
            gb_128k = self.kv_gb(131072)
            partes.append(
                f"KV cache: {kv} bytes por token en fp16 "
                f"({gb_128k:.2f} GB a 128k tokens)"
            )

        if self.tiene_gguf():
            partes.append("Tiene GGUF: si (usable en llama.cpp)")

        etiquetas = [t for t in self.tags if not t.startswith(("base_model:", "region:"))]
        if etiquetas:
            partes.append(f"Etiquetas: {', '.join(etiquetas[:12])}")
        if self.card:
            partes.append(f"Model card:\n{self.card}")

        return "\n\n".join(partes)

    def label(self) -> str:
        """Etiqueta compacta para episodic.store()."""
        base = self.model_id.split("/")[-1]
        if self.pipeline_tag:
            return f"{base} ({self.pipeline_tag})"
        return base


class HFScraper:
    """Scraper de HuggingFace sin dependencias externas."""

    def __init__(self, token: str = None, max_models: int = DEFAULT_MAX_MODELS):
        self.token      = token or os.environ.get("HF_TOKEN", "")
        self.max_models = max(1, min(max_models, 20))

    # ── HTTP helpers ────────────────────────────────────────────────────

    def _headers(self) -> dict:
        h = {"User-Agent": "CogniaResearch/1.0"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _get(self, url: str, como_texto: bool = False):
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                crudo = resp.read().decode("utf-8", errors="replace")
                return crudo if como_texto else json.loads(crudo)
        except urllib.error.HTTPError as e:
            if e.code not in (401, 403, 404):
                print(f"[hf] HTTP {e.code} en {url}")
            return None
        except Exception as exc:
            print(f"[hf] Error de conexion: {exc}")
            return None

    # ── API calls ───────────────────────────────────────────────────────

    def _buscar_crudo(self, query: str, filtro: str = "") -> List[dict]:
        """Una sola llamada a la API de busqueda. Devuelve los items crudos."""
        params = {
            "search":    query,
            "sort":      "downloads",
            "direction": "-1",
            "limit":     str(self.max_models * _FACTOR_SOBREMUESTREO),
            "full":      "true",
        }
        if filtro:
            params["filter"] = filtro
        data = self._get(f"{HF_API}/models?{urllib.parse.urlencode(params)}")
        return data if isinstance(data, list) else []

    def search_models(self, query: str, filtro: str = "") -> List[ModelContent]:
        """
        Busca modelos por query, filtra por relevancia y devuelve los mejores.

        Dos diferencias con el scraper de GitHub:
          - NO se confia en el orden de la API: se pide de mas y se reordena
            con relevance.py.
          - El parametro 'search' de HuggingFace es basicamente coincidencia de
            subcadena sobre el ID del modelo, no busqueda de texto completo.
            Medido: 'long context' devuelve 5 resultados, 'window context
            memory' devuelve 0. Por eso una query de 3+ terminos SIEMPRE hay
            que degradarla, no es un caso raro como en GitHub.
        """
        print(f"[hf] Buscando: '{query}' (max {self.max_models} modelos)...")
        data       = self._buscar_crudo(query, filtro)
        query_real = query

        if not data:
            for reducida in degradar_query(query):
                print(f"[hf] 0 resultados. Reintentando con: '{reducida}'")
                time.sleep(_REQUEST_DELAY)
                data = self._buscar_crudo(reducida, filtro)
                if data:
                    query_real = reducida
                    break

        if not data:
            print(f"[hf] Sin resultados para '{query}' ni sus reducciones.")
            return []

        def texto_de(item):
            return " ".join([
                item.get("id", ""),
                item.get("pipeline_tag") or "",
                " ".join(item.get("tags", []) or []),
            ])

        relevantes = filtrar_y_ordenar(
            data, query_real,
            texto_de       = texto_de,
            popularidad_de = lambda i: i.get("downloads", 0) or 0,
        )
        print(f"[hf] {len(data)} candidatos, {len(relevantes)} relevantes. "
              f"Procesando {min(self.max_models, len(relevantes))}...")

        resultados = []
        for item in relevantes[: self.max_models]:
            time.sleep(_REQUEST_DELAY)
            model_id = item.get("id", "")
            contenido = ModelContent(
                model_id     = model_id,
                model_url    = f"{HF_HOST}/{model_id}",
                author       = item.get("author") or "",
                descripcion  = self._descripcion_de(item),
                card         = self._fetch_card(model_id),
                downloads    = item.get("downloads", 0) or 0,
                likes        = item.get("likes", 0) or 0,
                pipeline_tag = item.get("pipeline_tag") or "",
                tags         = item.get("tags", []) or [],
                config       = self._fetch_config(model_id) or {},
                archivos     = [s.get("rfilename", "") for s in item.get("siblings", []) or []],
            )
            resultados.append(contenido)

            kv = contenido.kv_bytes_por_token()
            extra = f", KV {kv} B/token" if kv else ""
            print(f"[hf] OK  {model_id}  ({contenido.downloads} descargas{extra})")

        return resultados

    def _descripcion_de(self, item: dict) -> str:
        """HF no expone descripcion corta; se arma con las etiquetas utiles."""
        utiles = [
            t for t in (item.get("tags") or [])
            if not t.startswith(("base_model:", "region:", "license:", "arxiv:"))
        ]
        return ", ".join(utiles[:10])

    def _fetch_card(self, model_id: str) -> str:
        url  = f"{HF_HOST}/{model_id}/resolve/main/README.md"
        texto = self._get(url, como_texto=True)
        if not texto:
            return ""

        # Los model cards empiezan con frontmatter YAML entre ---; se salta.
        limpio = texto.strip()
        if limpio.startswith("---"):
            cierre = limpio.find("\n---", 3)
            if cierre != -1:
                limpio = limpio[cierre + 4:].strip()

        recortado = limpio[:CARD_MAX_CHARS]
        if len(limpio) > CARD_MAX_CHARS and "\n" in recortado:
            recortado = recortado[: recortado.rfind("\n")].strip()
        return recortado

    def _fetch_config(self, model_id: str) -> Optional[dict]:
        url  = f"{HF_HOST}/{model_id}/resolve/main/config.json"
        data = self._get(url)
        return data if isinstance(data, dict) else None
