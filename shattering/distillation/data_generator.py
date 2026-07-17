"""
shattering/distillation/data_generator.py
==========================================
Training data generator for the SRDN distillation pipeline.

Gold episode query:
  Episodes that survived the consolidation REINFORCE phase (feedback_weight >= 1.0,
  access_count >= 3). These represent high-confidence, repeatedly-accessed memories
  that the model should be able to reproduce from context.

Reasoning chain generation:
  For each gold episode, call the Ollama teacher to produce a step-by-step
  reasoning chain. Ollama returns text only — no logits or hidden states.
  The chain is stored as a (prompt, chain) pair for sequence_level_loss training.

Training weight:
  min(feedback_weight / 1.0, 2.0) — feedback-weighted importance, capped at 2x.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REINFORCE_MIN_FW       = 1.0
_REINFORCE_MIN_ACCESS   = 3
_DEFAULT_LIMIT          = 5000
_OLLAMA_DEFAULT_URL     = "http://localhost:11434/api/generate"
_OLLAMA_DEFAULT_MODEL   = "llama3"
_OLLAMA_TIMEOUT_S       = 60
_MAX_WEIGHT             = 2.0


def query_gold_episodes(
    db_path: str,
    min_fw: float = _REINFORCE_MIN_FW,
    min_access: int = _REINFORCE_MIN_ACCESS,
    limit: int = _DEFAULT_LIMIT,
) -> List[Dict[str, Any]]:
    """
    Query the episodic memory database for gold training episodes.

    Returns a list of dicts with keys:
      observation, vector_json, feedback_weight, label, training_weight
    """
    try:
        from storage.db_pool import db_connect_pooled
        conn = db_connect_pooled(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT
                observation,
                vector        AS vector_json,
                COALESCE(feedback_weight, 1.0) AS feedback_weight,
                COALESCE(label, '')            AS label
            FROM episodic_memory
            WHERE forgotten = 0
              AND COALESCE(feedback_weight, 1.0) >= ?
              AND COALESCE(access_count, 0) >= ?
            ORDER BY feedback_weight DESC, confidence DESC
            LIMIT ?
        """, (min_fw, min_access, limit))
        rows = cur.fetchall()
        conn.close()

        episodes = []
        for row in rows:
            fw = float(row["feedback_weight"])
            episodes.append({
                "observation":     row["observation"],
                "vector_json":     row["vector_json"],
                "feedback_weight": fw,
                "label":           row["label"],
                "training_weight": min(fw / _REINFORCE_MIN_FW, _MAX_WEIGHT),
            })
        logger.info("[Distillation] Queried %d gold episodes (min_fw=%.1f)", len(episodes), min_fw)
        return episodes

    except Exception as exc:
        logger.warning("[Distillation] query_gold_episodes failed: %s", exc)
        return []


def generate_reasoning_chains(
    episodes: List[Dict[str, Any]],
    ollama_url: str = _OLLAMA_DEFAULT_URL,
    model: str = _OLLAMA_DEFAULT_MODEL,
) -> List[Dict[str, Any]]:
    """
    Call the Ollama teacher to generate a reasoning chain for each episode.

    For each episode, sends:
      "Generate a step-by-step reasoning chain for: {observation}"

    Returns only episodes where Ollama responded successfully.
    Each returned dict adds a "reasoning_chain" key to the original episode dict.
    """
    results = []
    for i, ep in enumerate(episodes):
        prompt = f"Generate a step-by-step reasoning chain for: {ep['observation']}"
        try:
            chain = _ollama_generate(prompt, ollama_url, model)
            ep_out = dict(ep)
            ep_out["reasoning_chain"] = chain
            results.append(ep_out)
        except Exception as exc:
            logger.debug("[Distillation] Ollama chain generation failed (ep %d): %s", i, exc)

    logger.info(
        "[Distillation] Generated %d/%d reasoning chains via Ollama",
        len(results), len(episodes),
    )
    return results


def build_training_dataset(
    db_path: str,
    output_path: Optional[str] = None,
    ollama_url: str = _OLLAMA_DEFAULT_URL,
    model: str = _OLLAMA_DEFAULT_MODEL,
    min_fw: float = _REINFORCE_MIN_FW,
    min_access: int = _REINFORCE_MIN_ACCESS,
    limit: int = _DEFAULT_LIMIT,
) -> List[Dict[str, Any]]:
    """
    Full pipeline: query gold episodes -> generate reasoning chains -> return dataset.

    If output_path is provided, writes the dataset as newline-delimited JSON.

    Returns:
        List of training examples, each with:
          observation, reasoning_chain, training_weight, label
    """
    episodes = query_gold_episodes(db_path, min_fw=min_fw, min_access=min_access, limit=limit)
    if not episodes:
        logger.warning("[Distillation] No gold episodes found in %s", db_path)
        return []

    dataset = generate_reasoning_chains(episodes, ollama_url=ollama_url, model=model)

    if output_path and dataset:
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                for ex in dataset:
                    f.write(json.dumps(ex, ensure_ascii=False) + "\n")
            logger.info("[Distillation] Dataset written to %s (%d examples)", output_path, len(dataset))
        except Exception as exc:
            logger.warning("[Distillation] Failed to write dataset: %s", exc)

    return dataset


# ── Ollama helper ────────────────────────────────────────────────────────

def _ollama_generate(prompt: str, url: str, model: str) -> str:
    """Call Ollama /api/generate and return the concatenated response text."""
    payload = json.dumps({
        "model":  model,
        "prompt": prompt,
        "stream": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data    = payload,
        headers = {"Content-Type": "application/json"},
        method  = "POST",
    )

    with urllib.request.urlopen(req, timeout=_OLLAMA_TIMEOUT_S) as resp:
        data = json.loads(resp.read())

    return data.get("response", "").strip()
