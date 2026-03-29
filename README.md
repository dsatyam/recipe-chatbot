# Recipe chatbot (evaluation agent)

<!-- File tour: see [PROJECT_WALKTHROUGH.md](PROJECT_WALKTHROUGH.md) for every file explained section-by-section. -->

A small **FastAPI** service: recipe-focused chat, **evaluator-editable behavior** (`config/agent_behavior.md`), **OpenAI** or **OpenAI-compatible** backends, **JSON traces** per session, and a minimal web UI that calls the same **`POST /api/chat`** as any API client.

## Security (before GitHub)

- Do **not** commit `.env` or `data/traces.json`. Traces may contain user text.
- Use `.env.example` as a template only.

## Setup

```bash
cd recipe-chatbot
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env: set OPENAI_API_KEY and optionally OPENAI_BASE_URL / OPENAI_MODEL
```

Run from the **project root** (so `config/` and `data/` resolve correctly):

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- Web UI: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- OpenAPI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Health: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes* | API key for OpenAI, or a placeholder if your compatible server ignores it. |
| `OPENAI_BASE_URL` | No | If set, requests go here (e.g. local Ollama/vLLM OpenAI bridge). |
| `OPENAI_MODEL` | No | Default `gpt-4o-mini`. |
| `BEHAVIOR_FILE` | No | Default `config/agent_behavior.md`. |
| `TRACES_FILE` | No | Default `data/traces.json`. |

\*Required for the app to be fully healthy; `/health` reports `degraded` if missing.

## Behavior file

Edit [`config/agent_behavior.md`](config/agent_behavior.md). The app always prepends a **fixed base** recipe-assistant frame in code, then appends the full contents of that file.

## HTTP API

### `POST /api/chat`

**Headers (optional):** `X-Session-Id: <uuid>` — same meaning as JSON `session_id`.

**Body (JSON):**

- **`messages`** (optional): OpenAI-style array, e.g. `[{"role":"user","content":"Hi"},{"role":"assistant","content":"Hello"}]`. If this array is **non-empty**, it defines the full dialogue for this request (best for eval scripts). Must end with a **user** message.
- **`message`** (optional): Single new user message. Used when `messages` is absent or empty. Prior turns for that `session_id` are loaded from `data/traces.json`.
- **`session_id`** (optional): Opaque id (UUID recommended). If omitted, the server creates one and returns it.

**Response:** `{ "session_id", "reply", "model" }`.

### Example: `message` + session (multi-turn via traces)

```bash
SID=$(uuidgen | tr '[:upper:]' '[:lower:]')
curl -sS -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SID\",\"message\":\"Suggest a simple pasta for two.\"}" | jq .

curl -sS -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SID\",\"message\":\"Make it vegetarian.\"}" | jq .
```

### Example: full `messages` (client-owned history)

```bash
curl -sS -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "eval-run-1",
    "messages": [
      {"role": "user", "content": "What is mirepoix?"},
      {"role": "assistant", "content": "Onion, carrot, celery cooked in fat, used as a base."},
      {"role": "user", "content": "Give a ratio by weight."}
    ]
  }' | jq .
```

### Python (`httpx`)

```python
import httpx

base = "http://127.0.0.1:8000"
sid = "my-session"
r = httpx.post(f"{base}/api/chat", json={"session_id": sid, "message": "Quick lentil soup?"})
r.raise_for_status()
print(r.json()["reply"])
```

## Traces

[`data/traces.json`](data/traces.json) is a **JSON array**. Each element is one **session** (identified by `session_id`), with `turns` as alternating user/assistant entries and timestamps. The **most recently updated** session is stored **first** in the array. The file is gitignored by default.

## Codebase tour

For a **section-by-section** explanation of each file (and how they call each other), see [PROJECT_WALKTHROUGH.md](PROJECT_WALKTHROUGH.md). For manual test steps, see [TESTING.md](TESTING.md).

## License

See [LICENSE](LICENSE).
