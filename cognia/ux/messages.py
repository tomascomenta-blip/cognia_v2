"""
cognia/ux/messages.py
======================
Centralized user-facing strings for Cognia.

All text that appears in the UI or CLI must come from here.
Internal log messages (logger.*) are NOT user-facing and stay in-place.
"""
from __future__ import annotations


class UXMessages:
    # Desktop app -- lifecycle
    STARTING       = "Starting up..."
    READY          = "Ready. Type a message and press Send."
    STOPPING       = "Cognia is shutting down."
    BACKEND_FAILED = "Cognia could not start. Please restart the application."

    # Desktop app -- inference
    THINKING       = "Thinking..."
    ERROR_GENERIC  = "Something went wrong. Please try again."
    ERROR_TIMEOUT  = "The request took too long. Please try again."
    ERROR_ROUTE    = "Could not determine the best mode for this prompt."
    STREAM_CANCEL  = "Response cancelled."

    # Desktop app -- status panel
    STATUS_LOADING = "Loading system information..."
    STATUS_TITLE   = "System"
    STATUS_ERROR   = "Could not load status."

    # API error responses (do NOT include internal exception text)
    API_UNAVAILABLE     = "Service temporarily unavailable. Please try again in a moment."
    API_INVALID_REQUEST = "Invalid request. Please check your input and try again."

    # CLI
    CLI_DOCTOR_MISSING = (
        "Diagnostics script not found. "
        "Make sure scripts/cognia_doctor.py exists."
    )

    # Shard engine -- user-visible startup (shown only when log level <= INFO)
    SHARD_LOADING  = "Loading model..."
    SHARD_READY    = "Model ready."
    SHARD_FALLBACK = "Running in lightweight mode."
