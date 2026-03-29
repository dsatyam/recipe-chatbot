"""
Persist chat turns to a single JSON file for evaluation and debugging.

Who calls this module:
  - `app/chat.py` — `load_dialogue_from_trace` when the client uses `message` mode
    (server-side history), and `record_exchange` after every successful LLM reply.

File format (see README.md / PROJECT_WALKTHROUGH.md):
  - Top-level JSON **array** of session objects.
  - The session that was just updated is moved to **index 0** so the newest activity
    appears first when humans open the file.

Concurrency:
  - `_trace_lock` serializes readers/writers. For many parallel users, a database would
    scale better; this project optimizes for teaching and single-machine evals.

Atomic writes:
  - We write a temp file in the same directory, then `os.replace` so crashes mid-write
    are less likely to leave `traces.json` truncated.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# One asyncio.Lock for the whole module: all trace operations acquire it.
# Teaching note: `asyncio.Lock` is not thread-safe for *threads*, but our file work is
# delegated to `asyncio.to_thread`, and only one coroutine holds the lock at a time.
_trace_lock = asyncio.Lock()


def _utc_now_iso() -> str:
    """ISO-8601 timestamps in UTC for stable, sortable logs."""
    return datetime.now(timezone.utc).isoformat()


def _read_sessions(path: Path) -> list[dict[str, Any]]:
    """
    Load the on-disk trace array. Malformed or missing files become `[]` so the app
    keeps running (evaluators can delete a corrupted file to reset).
    """
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return data


def _write_sessions_atomic(path: Path, sessions: list[dict[str, Any]]) -> None:
    """
    Serialize `sessions` to pretty JSON and replace `path` atomically.

    Called from a worker thread (see `record_exchange`) so the event loop stays responsive.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(sessions, indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(
        dir=path.parent,
        prefix=".traces_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, path)
    finally:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _merge_session(
    sessions: list[dict[str, Any]],
    session_id: str,
    metadata: dict[str, Any],
    user_content: str,
    assistant_content: str,
) -> list[dict[str, Any]]:
    """
    Insert or update one session, append the latest user+assistant pair, prepend it.

    Returns a **new** top-level list: `[updated_session, ...other_sessions]`.
    """
    now = _utc_now_iso()
    existing: dict[str, Any] | None = None
    rest: list[dict[str, Any]] = []
    for s in sessions:
        if isinstance(s, dict) and s.get("session_id") == session_id:
            existing = s
        else:
            rest.append(s)

    if existing is None:
        existing = {
            "session_id": session_id,
            "created_at": now,
            "updated_at": now,
            "metadata": dict(metadata),
            "turns": [],
        }
    else:
        existing = dict(existing)
        existing["metadata"] = {**existing.get("metadata", {}), **metadata}
        existing["updated_at"] = now
        if "created_at" not in existing:
            existing["created_at"] = now
        existing["turns"] = list(existing.get("turns", []))

    turns: list[dict[str, Any]] = existing["turns"]
    turns.append({"role": "user", "content": user_content, "timestamp": now})
    turns.append({"role": "assistant", "content": assistant_content, "timestamp": now})
    existing["turns"] = turns

    return [existing, *rest]


def _find_turns_for_session(sessions: list[dict[str, Any]], session_id: str) -> list[dict[str, str]]:
    """
    Strip stored turns down to `{role, content}` for the LLM request builder in `app/chat.py`.

    Unknown roles or bad entries are skipped so a hand-edited trace file cannot crash the app.
    """
    for s in sessions:
        if isinstance(s, dict) and s.get("session_id") == session_id:
            out: list[dict[str, str]] = []
            for t in s.get("turns", []) or []:
                if not isinstance(t, dict):
                    continue
                role = t.get("role")
                content = t.get("content")
                if role in ("user", "assistant") and isinstance(content, str):
                    out.append({"role": role, "content": content})
            return out
    return []


async def load_dialogue_from_trace(traces_path: Path, session_id: str) -> list[dict[str, str]]:
    """
    Async wrapper: hold the lock, then read+parse in a thread.

    Keeps parity with `record_exchange` so we never read half-written JSON mid-replace.
    """
    async with _trace_lock:
        return await asyncio.to_thread(_find_turns_for_session, _read_sessions(traces_path), session_id)


async def record_exchange(
    traces_path: Path,
    session_id: str,
    metadata: dict[str, Any],
    user_content: str,
    assistant_content: str,
) -> None:
    """
    Append one user message + assistant reply for `session_id`, then save.

    `metadata` is merged from `app/chat.py` (model name, behavior hash, etc.) so traces
    self-describe how they were produced.
    """
    async with _trace_lock:

        def _run() -> None:
            path = traces_path
            sessions = _read_sessions(path)
            merged = _merge_session(sessions, session_id, metadata, user_content, assistant_content)
            _write_sessions_atomic(path, merged)

        await asyncio.to_thread(_run)
