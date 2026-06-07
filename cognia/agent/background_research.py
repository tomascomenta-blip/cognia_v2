"""
cognia/agent/background_research.py
==================================
Low-memory background research that turns ideas into verified tools, even when
the CLI isn't open.

How it stays light:
  - The daemon itself holds NO model and NO Cognia instance. It only touches the
    DB (a tool-idea queue) and, when it actually synthesizes, spins the LLM for a
    single short burst.
  - background_tick() is RAM-guarded: it skips the heavy synthesis step unless at
    least `min_free_mb` of memory is free, so it never fights the user's machine.
  - It does exactly ONE unit of work per call, then returns. The daemon sleeps
    long between calls.

Two signal sources for "what tool to build":
  - queue_tool_idea(): a fully-specified idea (name + purpose + a concrete test).
    These are auto-synthesizable and verifiable.
  - record_wanted_tool(): a lightweight signal logged when the agent tries to use
    a tool that doesn't exist yet -- a wish-list, refined into full specs later.
"""

from __future__ import annotations

import time

from storage.db_pool import db_connect_pooled
from cognia.config import DB_PATH
from cognia.agent.tool_synthesis import ToolSpec, synthesize_and_register


def _ensure_tables(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tool_ideas (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT UNIQUE NOT NULL,
            purpose        TEXT NOT NULL,
            test_input     TEXT NOT NULL,
            expect_contains TEXT NOT NULL,
            status         TEXT DEFAULT 'pending',
            note           TEXT,
            created_at     TEXT,
            updated_at     TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wanted_tools (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            hint       TEXT,
            hits       INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)
    # Pooled connections release WITHOUT committing on close(), so persist the
    # schema explicitly -- otherwise the open write transaction locks the DB.
    conn.commit()


def _now() -> str:
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


# ── tool-idea queue (full specs, auto-synthesizable) ───────────────────

def queue_tool_idea(name: str, purpose: str, test_input: str,
                    expect_contains: str, db_path: str = DB_PATH) -> bool:
    """Queue a fully-specified tool idea. No-op if one with this name exists."""
    conn = db_connect_pooled(db_path)
    try:
        _ensure_tables(conn)
        exists = conn.execute(
            "SELECT 1 FROM tool_ideas WHERE name = ?", (name,)
        ).fetchone()
        if exists:
            return False
        conn.execute(
            "INSERT INTO tool_ideas (name, purpose, test_input, expect_contains, "
            "status, created_at, updated_at) VALUES (?,?,?,?, 'pending', ?, ?)",
            (name, purpose, test_input, expect_contains, _now(), _now()),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def pending_tool_ideas(limit: int = 5, db_path: str = DB_PATH) -> list:
    conn = db_connect_pooled(db_path)
    try:
        _ensure_tables(conn)
        rows = conn.execute(
            "SELECT id, name, purpose, test_input, expect_contains FROM tool_ideas "
            "WHERE status = 'pending' ORDER BY id LIMIT ?", (limit,),
        ).fetchall()
        return [{"id": r[0], "name": r[1], "purpose": r[2],
                 "test_input": r[3], "expect_contains": r[4]} for r in rows]
    finally:
        conn.close()


def _mark_idea(idea_id: int, status: str, note: str, db_path: str) -> None:
    conn = db_connect_pooled(db_path)
    try:
        conn.execute(
            "UPDATE tool_ideas SET status = ?, note = ?, updated_at = ? WHERE id = ?",
            (status, note[:300], _now(), idea_id),
        )
        conn.commit()
    finally:
        conn.close()


# ── wanted-tool signal (the agent asked for a missing tool) ────────────

def record_wanted_tool(name: str, hint: str = "", db_path: str = DB_PATH) -> None:
    """Log that some tool name was requested but doesn't exist. Best-effort."""
    if not name:
        return
    try:
        conn = db_connect_pooled(db_path)
        try:
            _ensure_tables(conn)
            row = conn.execute(
                "SELECT id, hits FROM wanted_tools WHERE name = ?", (name,)
            ).fetchone()
            if row:
                conn.execute("UPDATE wanted_tools SET hits = ? WHERE id = ?",
                             (row[1] + 1, row[0]))
            else:
                conn.execute(
                    "INSERT INTO wanted_tools (name, hint, created_at) VALUES (?,?,?)",
                    (name, hint[:200], _now()),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


# ── memory guard ───────────────────────────────────────────────────────

def free_memory_mb() -> float:
    """Available RAM in MB. Returns +inf if it can't be measured (don't block)."""
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 * 1024)
    except Exception:
        return float("inf")


# ── the background unit of work ────────────────────────────────────────

def background_tick(orch=None, min_free_mb: float = 700.0,
                    db_path: str = DB_PATH) -> dict:
    """
    Do ONE unit of background research: synthesize the next pending tool idea,
    verified, into a real tool -- but only if memory allows.

    Returns a status dict {action, ...}. Never raises.
    """
    try:
        pend = pending_tool_ideas(limit=1, db_path=db_path)
        if not pend:
            return {"action": "idle", "reason": "sin ideas pendientes"}

        free = free_memory_mb()
        if free < min_free_mb:
            return {"action": "skipped", "reason": f"poca memoria ({free:.0f}MB < {min_free_mb:.0f}MB)"}

        if orch is None:
            try:
                from shattering.orchestrator import ShatteringOrchestrator
                orch = ShatteringOrchestrator(mode="local")
            except Exception as e:
                return {"action": "skipped", "reason": f"sin orquestador: {e}"}

        idea = pend[0]
        spec = ToolSpec(
            name=idea["name"], doc=idea["purpose"][:60], purpose=idea["purpose"],
            test_input=idea["test_input"], expect_contains=idea["expect_contains"],
        )
        res = synthesize_and_register(spec, orch=orch, max_attempts=3)
        _mark_idea(idea["id"], "done" if res["ok"] else "failed",
                   res.get("reason", ""), db_path)
        return {"action": "synthesized", "name": idea["name"],
                "ok": res["ok"], "reason": res.get("reason", "")}
    except Exception as e:
        return {"action": "error", "reason": str(e)}


def run_forever(interval_sec: float = 1800.0, min_free_mb: float = 700.0,
                db_path: str = DB_PATH) -> None:
    """Daemon loop: one tick, then sleep. Used by the detached runner script."""
    while True:
        status = background_tick(min_free_mb=min_free_mb, db_path=db_path)
        print(f"[cognia-research] {_now()} {status}", flush=True)
        time.sleep(interval_sec)
