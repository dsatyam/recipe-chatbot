"""
FastAPI application: HTTP routes only.

Separation of concerns:
  - This file wires URLs to functions and renders HTML templates.
  - All chat business logic lives in `app/chat.py` (`run_chat`) so the **same** code path
    serves browsers (`templates/chat.html`) and raw API clients (`curl`, Python).

Related files:
  - `app/schemas.py` — request/response models referenced by FastAPI for `/docs`.
  - `app/config.py` — `get_settings()` and `PROJECT_ROOT` for template directory.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.chat import run_chat
from app.config import PROJECT_ROOT, Settings, get_settings
from app.schemas import ChatRequest, ChatResponse

logging.basicConfig(level=logging.INFO)

# Jinja2 loads `templates/chat.html` relative to the project root (not inside `app/`).
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))


def _behavior_path_for_footer(settings: Settings) -> str:
    """Project-relative path for UI (forward slashes). Falls back if outside repo."""
    resolved: Path = settings.resolved_behavior_file()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        try:
            return Path(settings.behavior_file).as_posix()
        except Exception:
            return str(resolved).replace("\\", "/")


def _behavior_preview_text(settings: Settings, max_len: int = 180) -> str:
    """Short plain-text blurb from the behavior file for the page footer."""
    path: Path = settings.resolved_behavior_file()
    if not path.is_file():
        return "No behavior file found — the app uses code-only base instructions."
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return "Behavior file is empty — only the fixed base prompt in app/behavior.py applies."
    lines = [ln.strip() for ln in raw.splitlines()]
    body: list[str] = []
    for ln in lines:
        if re.match(r"^#+\s*", ln) or re.match(r"^>\s*", ln) or not ln:
            continue
        if re.match(r"^[-*]\s+", ln):
            ln = re.sub(r"^[-*]\s+", "", ln)
        body.append(ln)
        if len(" ".join(body)) > max_len:
            break
    if not body:
        text = re.sub(r"#+\s*", "", raw.splitlines()[0] if raw.splitlines() else "").strip() or "Custom evaluator instructions."
    else:
        text = " ".join(body)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


app = FastAPI(
    title="Recipe chatbot",
    description="Recipe-focused agent with configurable behavior file, OpenAI or compatible APIs, and JSON session traces.",
    version="0.1.0",
)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """
    Serve the single-page chat UI.

    Template variables: `default_model`, project-relative `behavior_file_rel`, and a
    short `behavior_preview` derived from the evaluator markdown file.
    """
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "default_model": settings.openai_model,
            "behavior_file_rel": _behavior_path_for_footer(settings),
            "behavior_preview": _behavior_preview_text(settings),
        },
    )


@app.post("/api/chat", response_model=ChatResponse)
async def api_chat(
    body: ChatRequest,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> ChatResponse:
    """
    Primary JSON API. The browser UI calls this endpoint with `fetch`.

    Header vs body:
      Scripts may prefer `X-Session-Id`; browsers send both for clarity. Precedence for
      the actual id is implemented in `app/chat.py` (`body.session_id` wins).
    """
    return await run_chat(body, x_session_id)


@app.get("/health")
async def health() -> dict:
    """
    Lightweight readiness info for operators and automated checks.

    We intentionally never echo secret values — only booleans and filesystem paths.
    """
    settings = get_settings()
    behavior = settings.resolved_behavior_file()
    traces = settings.resolved_traces_file()
    key_ok = bool(settings.openai_api_key and settings.openai_api_key.strip())
    return {
        "status": "ok" if key_ok and behavior.is_file() else "degraded",
        "openai_key_configured": key_ok,
        "behavior_file_exists": behavior.is_file(),
        "behavior_path": str(behavior).replace("\\", "/"),
        "traces_path": str(traces).replace("\\", "/"),
    }
