"""
cognia/export/history_exporter.py
==================================
Exports chat history from cognia_desktop_chat.db in JSON, Markdown, and CSV.
Uses db_pool to avoid direct sqlite3.connect() calls.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# DB path mirrors the one in cognia_desktop_api.py
_ROOT = Path(__file__).parent.parent.parent
_CHAT_DB = str(_ROOT / "cognia_desktop_chat.db")


def _unix_to_iso(ts) -> str:
    """Convert a Unix timestamp integer to an ISO 8601 string (UTC)."""
    if ts is None:
        return ""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (ValueError, OSError):
        return str(ts)


class HistoryExporter:
    """Exports chat history in multiple formats (JSON, Markdown, CSV)."""

    def __init__(self, db_path: str = _CHAT_DB):
        self._db_path = db_path

    def get_messages(
        self,
        user_id: str = None,
        limit: int = 1000,
        since: str = None,
    ) -> list[dict]:
        """
        Retrieve messages from chat_history via db_pool.

        Parameters
        ----------
        user_id : str, optional
            Not stored in the table; kept for API symmetry / future auth.
        limit : int
            Maximum number of rows to return (most recent last).
        since : str, optional
            ISO datetime string; only rows with ts >= that Unix epoch are returned.
        """
        from storage.db_pool import get_pool

        since_ts: Optional[int] = None
        if since:
            try:
                dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                since_ts = int(dt.timestamp())
            except (ValueError, AttributeError):
                since_ts = None

        with get_pool(self._db_path).get() as conn:
            if since_ts is not None:
                rows = conn.execute(
                    "SELECT role, content, ts FROM chat_history"
                    " WHERE ts >= ? ORDER BY id LIMIT ?",
                    (since_ts, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT role, content, ts FROM chat_history"
                    " ORDER BY id LIMIT ?",
                    (limit,),
                ).fetchall()

        return [
            {"role": r, "content": c, "timestamp": _unix_to_iso(ts)}
            for r, c, ts in rows
        ]

    # ── Format converters ─────────────────────────────────────────────

    def to_json(self, messages: list[dict], pretty: bool = True) -> str:
        """Return a JSON string with export metadata and the message list."""
        payload = {
            "exported_at": datetime.now(tz=timezone.utc).isoformat(),
            "total_messages": len(messages),
            "messages": messages,
        }
        indent = 2 if pretty else None
        return json.dumps(payload, ensure_ascii=False, indent=indent)

    def to_markdown(self, messages: list[dict]) -> str:
        """Return a Markdown-formatted chat log."""
        lines: list[str] = [
            "# Cognia Chat History",
            "",
            f"Exported: {datetime.now(tz=timezone.utc).isoformat()}",
            f"Total: {len(messages)} messages",
            "",
        ]
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            ts = msg.get("timestamp", "")
            label = "User" if role == "user" else "Cognia"
            lines.append("---")
            lines.append(f"**{label}** ({ts})")
            lines.append(content)
            lines.append("")
        return "\n".join(lines)

    def to_csv(self, messages: list[dict]) -> str:
        """Return a CSV string with columns: timestamp, role, content."""
        buf = io.StringIO()
        writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
        writer.writerow(["timestamp", "role", "content"])
        for msg in messages:
            writer.writerow([
                msg.get("timestamp", ""),
                msg.get("role", ""),
                msg.get("content", ""),
            ])
        return buf.getvalue()
