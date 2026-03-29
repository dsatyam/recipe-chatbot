"""
Build the **system** message sent to the LLM: fixed base + optional markdown layer.

Split on purpose:
  - Code in `BASE_SYSTEM_PROMPT` holds non-negotiable framing (safety, recipe domain).
  - `config/agent_behavior.md` is edited by evaluators without touching Python.

Downstream:
  - `app/chat.py` calls `build_system_prompt()` and passes the result as the `system`
    role in the OpenAI Chat Completions request.

The SHA-256 digest is stored in trace metadata (`app/tracing.py`) so logs show which
behavior text was active for a session.
"""

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# This string is always part of the model's instructions, even if the markdown file is missing.
BASE_SYSTEM_PROMPT = """You are a helpful recipe and cooking assistant.
Give practical, accurate cooking guidance. When discussing perishable foods, reheating, or doneness, mention food-safety considerations when relevant.
If a user request is unsafe or impossible, refuse briefly and suggest a safe alternative."""


def _sha256_text(text: str) -> str:
    """Stable fingerprint for trace metadata (see `app/chat.py` → `record_exchange`)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_behavior_layer(behavior_path: Path) -> tuple[str, str]:
    """
    Read evaluator markdown from disk.

    Returns:
        (extra_instructions, behavior_sha256)

    If the file is missing, we return ("", "missing") and `build_system_prompt` falls
    back to `BASE_SYSTEM_PROMPT` only — see logs for the warning.
    """
    if not behavior_path.is_file():
        logger.warning("Behavior file not found at %s; using base system prompt only.", behavior_path)
        return "", "missing"

    raw = behavior_path.read_text(encoding="utf-8").strip()
    if not raw:
        return "", _sha256_text("")
    return raw, _sha256_text(raw)


def build_system_prompt(behavior_path: Path) -> tuple[str, str]:
    """
    Full system message: fixed base + evaluator behavior file contents.

    Returns:
        (system_prompt, behavior_sha256)

    The separator `---` helps humans debug prompt dumps; the model treats it as text.
    """
    extra, digest = load_behavior_layer(behavior_path)
    if not extra:
        return BASE_SYSTEM_PROMPT, digest
    return f"{BASE_SYSTEM_PROMPT}\n\n---\n\n{extra}", digest
