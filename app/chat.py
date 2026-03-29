"""
Core chat orchestration: build dialogue → call LLM → write trace → return JSON.

Call graph for one successful request:
  1. `app/main.py` `api_chat` parses `ChatRequest` / headers and calls `run_chat`.
  2. `run_chat` loads settings (`app/config.py`) and system prompt (`app/behavior.py`).
  3. Dialogue either comes from the request (`messages`) or from disk + new `message`
     (`app/tracing.py` + this file).
  4. `AsyncOpenAI` (official SDK) sends Chat Completions; `base_url` from settings
     enables OpenAI-compatible servers without forking code.
  5. `app/tracing.py.record_exchange` appends the new user/assistant pair.

This module is the **single place** that ties behavior, tracing, and the model together.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException
from openai import APIError, AsyncOpenAI, RateLimitError

from app.behavior import build_system_prompt
from app.config import Settings, get_settings
from app.schemas import ChatRequest, ChatResponse
from app import tracing

logger = logging.getLogger(__name__)


def _normalize_dialogue(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    Keep only user/assistant string pairs for the OpenAI `messages` parameter.

    Extra roles (if any) are dropped so evaluators cannot accidentally pass `system`
    twice — the server always injects exactly one system message from `app/behavior.py`.
    """
    out: list[dict[str, str]] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        if role not in ("user", "assistant"):
            continue
        if not isinstance(content, str):
            continue
        out.append({"role": role, "content": content})
    return out


async def run_chat(
    body: ChatRequest,
    header_session_id: str | None,
    settings: Settings | None = None,
) -> ChatResponse:
    """
    Execute one chat turn.

    Args:
        body: Validated JSON from `app/schemas.py`.
        header_session_id: Optional `X-Session-Id` header (same meaning as `body.session_id`).
        settings: Dependency injection for tests; defaults to cached `get_settings()`.

    Session id resolution (documented in PROJECT_WALKTHROUGH.md):
        body.session_id or header or newly generated UUID — returned to the client so
        scripts can continue the same trace bucket.
    """
    settings = settings or get_settings()
    behavior_path = settings.resolved_behavior_file()
    traces_path = settings.resolved_traces_file()
    system_prompt, behavior_sha256 = build_system_prompt(behavior_path)

    session_id = body.session_id or header_session_id or str(uuid.uuid4())

    # Branch A — client-owned history (typical for evaluation harnesses).
    if body.messages:
        dialogue = _normalize_dialogue([m.model_dump() for m in body.messages])
    else:
        # Branch B — simple `message` string: replay prior turns from traces, then append.
        text = (body.message or "").strip()
        if not text:
            raise HTTPException(
                status_code=400,
                detail="Provide a non-empty `message` when not using `messages`.",
            )
        prior = await tracing.load_dialogue_from_trace(traces_path, session_id)
        dialogue = prior + [{"role": "user", "content": text}]

    if not dialogue:
        raise HTTPException(status_code=400, detail="No valid user/assistant messages to send to the model.")
    if dialogue[-1]["role"] != "user":
        raise HTTPException(
            status_code=400,
            detail="The last message must be from the user. Send `messages` ending with a user turn, or use `message` mode.",
        )

    # One client handles both OpenAI and compatible endpoints — see README "Environment variables".
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url or None,
    )

    openai_messages = [{"role": "system", "content": system_prompt}, *dialogue]

    try:
        completion = await client.chat.completions.create(
            model=settings.openai_model,
            messages=openai_messages,
        )
    except RateLimitError as e:
        logger.warning("OpenAI rate limit: %s", e)
        raise HTTPException(status_code=429, detail="Upstream rate limited; retry later.") from e
    except APIError as e:
        logger.exception("OpenAI API error")
        raise HTTPException(status_code=502, detail=str(e.message or e)) from e
    except Exception as e:
        logger.exception("Unexpected error calling LLM")
        raise HTTPException(status_code=502, detail="Failed to complete chat request.") from e

    choice = completion.choices[0].message
    reply = (choice.content or "").strip()
    if not reply:
        raise HTTPException(status_code=502, detail="Model returned an empty reply.")

    # Trace exactly one new exchange: the user line we responded to + our assistant text.
    user_content = dialogue[-1]["content"]
    metadata = {
        "model": settings.openai_model,
        "base_url": "custom" if settings.openai_base_url else "default",
        "behavior_file": str(settings.behavior_file).replace("\\", "/"),
        "behavior_sha256": behavior_sha256,
    }
    await tracing.record_exchange(
        traces_path,
        session_id,
        metadata,
        user_content,
        reply,
    )

    return ChatResponse(session_id=session_id, reply=reply, model=settings.openai_model)
