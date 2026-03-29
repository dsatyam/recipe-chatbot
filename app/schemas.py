"""
Pydantic models for the public HTTP API.

Used by:
  - `app/main.py` — types the `POST /api/chat` body and response; enables OpenAPI at `/docs`.
  - `app/chat.py` — `run_chat` accepts `ChatRequest` and returns `ChatResponse`.

These models are the **contract** between browsers, evaluation scripts, and the server.
If you add fields, update README.md and PROJECT_WALKTHROUGH.md so learners stay in sync.
"""

from pydantic import BaseModel, Field, model_validator


class ChatMessage(BaseModel):
    """One turn in OpenAI-style chat history (user or assistant text)."""

    role: str = Field(..., description='Must be "user" or "assistant".')
    content: str


class ChatRequest(BaseModel):
    """
    JSON body for `POST /api/chat`.

    Two modes (see `app/chat.py`):
      1) `messages` non-empty → client sends the full dialogue for this request.
      2) Otherwise `message` → server loads prior turns from `data/traces.json` for
         `session_id`, then appends this user line (simple browser / script flow).
    """

    session_id: str | None = Field(
        default=None,
        description="Stable id for this conversation; server generates one if omitted.",
    )
    message: str | None = Field(
        default=None,
        description="Single new user message when not sending full `messages`.",
    )
    messages: list[ChatMessage] | None = Field(
        default=None,
        description="Full OpenAI-style history; when non-empty, overrides trace-backed `message` mode.",
    )

    @model_validator(mode="after")
    def require_messages_or_message(self) -> "ChatRequest":
        """
        FastAPI turns a raised ValueError here into HTTP 422 with a structured `detail`.

        We require *some* user content so the model always has a user turn to answer.
        """
        msgs = self.messages or []
        if msgs:
            return self
        if self.message is not None and self.message.strip():
            return self
        raise ValueError("Provide non-empty `messages` or a non-empty `message`.")


class ChatResponse(BaseModel):
    """Stable JSON shape returned to clients (and documented in OpenAPI)."""

    session_id: str
    reply: str
    model: str
