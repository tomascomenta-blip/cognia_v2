"""
cognia/webhooks/webhook_manager.py
===================================
Fire-and-forget webhook notifications for Cognia Desktop events.

Table: webhooks
  id           INTEGER PRIMARY KEY AUTOINCREMENT
  url          TEXT NOT NULL
  events       TEXT NOT NULL  -- JSON array of event strings
  secret       TEXT NOT NULL DEFAULT ''
  active       INTEGER NOT NULL DEFAULT 1
  created_at   INTEGER NOT NULL
  last_fired_at INTEGER
  fire_count   INTEGER NOT NULL DEFAULT 0

Table: webhook_deliveries
  id           INTEGER PRIMARY KEY AUTOINCREMENT
  webhook_id   INTEGER NOT NULL
  event_type   TEXT NOT NULL
  status       TEXT NOT NULL  -- 'ok' | 'fail'
  fired_at     INTEGER NOT NULL
  response_code INTEGER      -- NULL on network error
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from storage.db_pool import get_pool

SUPPORTED_EVENTS = [
    "goal.completed",    # when a goal reaches 100%
    "goal.created",      # when a new goal is created
    "error_rate.high",   # when error_rate > 0.1
    "search.completed",  # when a web search returns a result
    "message.received",  # on every user message
]

_COGNIA_VERSION = "3.0"
_DELIVERY_LOG_MAX = 200  # rows kept per webhook before pruning


class WebhookManager:
    """
    Manages webhook subscriptions and dispatches HTTP POST events.
    All sends are fire-and-forget daemon threads — never blocks callers.
    Uses storage/db_pool — never calls sqlite3.connect() directly.
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(Path(__file__).parent.parent.parent / "cognia_desktop_chat.db")
        self._db = db_path
        self._init_db()

    # ── Schema ────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with get_pool(self._db).get() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS webhooks (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    url           TEXT    NOT NULL,
                    events        TEXT    NOT NULL,
                    secret        TEXT    NOT NULL DEFAULT '',
                    active        INTEGER NOT NULL DEFAULT 1,
                    created_at    INTEGER NOT NULL,
                    last_fired_at INTEGER,
                    fire_count    INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    webhook_id    INTEGER NOT NULL,
                    event_type    TEXT    NOT NULL,
                    status        TEXT    NOT NULL,
                    fired_at      INTEGER NOT NULL,
                    response_code INTEGER
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_wh_deliveries ON webhook_deliveries(webhook_id, id DESC)"
            )

    # ── Public API ────────────────────────────────────────────────────

    def register(self, url: str, events: list, secret: str = "") -> dict:
        """
        Register a new webhook.

        Args:
            url: HTTP/HTTPS endpoint to POST to.
            events: list of event strings; must be a subset of SUPPORTED_EVENTS.
            secret: optional HMAC-SHA256 signing secret.

        Returns:
            webhook dict with id.

        Raises:
            ValueError: if URL is invalid or any event is not in SUPPORTED_EVENTS.
        """
        # Validate URL
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"Invalid webhook URL: {url!r}")

        # Validate events
        if not events:
            raise ValueError("events list must not be empty")
        invalid = set(events) - set(SUPPORTED_EVENTS)
        if invalid:
            raise ValueError(f"Unsupported events: {sorted(invalid)}. Allowed: {SUPPORTED_EVENTS}")

        events_json = json.dumps(sorted(set(events)))
        now = int(time.time())
        with get_pool(self._db).get() as conn:
            cur = conn.execute(
                "INSERT INTO webhooks (url, events, secret, active, created_at) VALUES (?, ?, ?, 1, ?)",
                (url, events_json, secret or "", now),
            )
            webhook_id = cur.lastrowid

        return self._get_webhook(webhook_id)

    def unregister(self, webhook_id: int) -> bool:
        """Soft-delete: mark webhook inactive. Returns True if found."""
        with get_pool(self._db).get() as conn:
            cur = conn.execute(
                "UPDATE webhooks SET active = 0 WHERE id = ?", (webhook_id,)
            )
        return cur.rowcount > 0

    def list_webhooks(self) -> list:
        """Return all active webhooks."""
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT id, url, events, secret, active, created_at, last_fired_at, fire_count "
                "FROM webhooks WHERE active = 1 ORDER BY id"
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def fire(self, event_type: str, data: dict) -> None:
        """
        Dispatch event to all active webhooks subscribed to event_type.
        Launches a daemon thread per webhook — never blocks the caller.
        """
        if event_type not in SUPPORTED_EVENTS:
            return  # silently ignore unknown events

        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT id, url, events, secret FROM webhooks WHERE active = 1"
            ).fetchall()

        payload = {
            "event": event_type,
            "data": data,
            "ts": time.time(),
            "cognia_version": _COGNIA_VERSION,
        }

        for wh_id, url, events_json, secret in rows:
            try:
                subscribed = json.loads(events_json)
            except Exception:
                continue
            if event_type not in subscribed:
                continue

            t = threading.Thread(
                target=self._send_webhook,
                args=(url, payload, secret, wh_id, event_type),
                daemon=True,
            )
            t.start()

    def _send_webhook(
        self,
        url: str,
        payload: dict,
        secret: str,
        webhook_id: int,
        event_type: str,
    ) -> bool:
        """
        POST payload as JSON to url with optional HMAC-SHA256 signature.
        1 retry on failure. Updates delivery log and fire stats.
        Returns True on 2xx, False otherwise.
        """
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "Cognia-Webhook/3.0"}

        if secret:
            sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
            headers["X-Cognia-Signature"] = f"sha256={sig}"

        status = "fail"
        response_code = None

        for attempt in range(2):
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    response_code = resp.status
                    if 200 <= response_code < 300:
                        status = "ok"
                        break
            except urllib.error.HTTPError as e:
                response_code = e.code
            except Exception:
                response_code = None
            if attempt == 0:
                time.sleep(0.5)  # brief pause before retry

        fired_at = int(time.time())

        # Update stats and log — swallow all DB errors to stay fire-and-forget
        try:
            with get_pool(self._db).get() as conn:
                if status == "ok":
                    conn.execute(
                        "UPDATE webhooks SET last_fired_at = ?, fire_count = fire_count + 1 WHERE id = ?",
                        (fired_at, webhook_id),
                    )
                conn.execute(
                    "INSERT INTO webhook_deliveries (webhook_id, event_type, status, fired_at, response_code) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (webhook_id, event_type, status, fired_at, response_code),
                )
                # Prune old delivery rows
                conn.execute(
                    "DELETE FROM webhook_deliveries WHERE webhook_id = ? AND id NOT IN ("
                    "  SELECT id FROM webhook_deliveries WHERE webhook_id = ? ORDER BY id DESC LIMIT ?"
                    ")",
                    (webhook_id, webhook_id, _DELIVERY_LOG_MAX),
                )
        except Exception:
            pass

        return status == "ok"

    def get_delivery_log(self, webhook_id: int, limit: int = 20) -> list:
        """Return the last `limit` delivery records for a webhook."""
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT id, webhook_id, event_type, status, fired_at, response_code "
                "FROM webhook_deliveries WHERE webhook_id = ? ORDER BY id DESC LIMIT ?",
                (webhook_id, limit),
            ).fetchall()
        return [
            {
                "id": r[0],
                "webhook_id": r[1],
                "event_type": r[2],
                "status": r[3],
                "fired_at": r[4],
                "response_code": r[5],
            }
            for r in rows
        ]

    # ── Internals ─────────────────────────────────────────────────────

    def _get_webhook(self, webhook_id: int) -> Optional[dict]:
        with get_pool(self._db).get() as conn:
            row = conn.execute(
                "SELECT id, url, events, secret, active, created_at, last_fired_at, fire_count "
                "FROM webhooks WHERE id = ?",
                (webhook_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    @staticmethod
    def _row_to_dict(row) -> dict:
        events = []
        try:
            events = json.loads(row[2])
        except Exception:
            pass
        return {
            "id": row[0],
            "url": row[1],
            "events": events,
            "secret": row[3],
            "active": bool(row[4]),
            "created_at": row[5],
            "last_fired_at": row[6],
            "fire_count": row[7],
        }
