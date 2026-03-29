# Step-by-step testing guide

<!-- Companion docs: [README.md](README.md) for setup/API; [PROJECT_WALKTHROUGH.md](PROJECT_WALKTHROUGH.md) for file-by-file architecture. -->

Use this checklist to verify the recipe chatbot after setup or when you change code. Commands assume a **Unix-style shell** (macOS/Linux). On Windows, use PowerShell equivalents or run commands from Git Bash.

## Before you start

1. **Project root** — Open a terminal in the folder that contains `app/`, `config/`, and `data/` (the same directory as `README.md`).

2. **Virtual environment** (if not already active):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate    # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Environment file** — Copy `.env.example` to `.env` and set at least:

   - `OPENAI_API_KEY` — real key for OpenAI, or a placeholder if your compatible server does not require one.

   Optional for non-OpenAI endpoints:

   - `OPENAI_BASE_URL`
   - `OPENAI_MODEL`

4. **Start the server** (leave this terminal open):

   ```bash
   uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

   If you use another port, replace `8000` in all URLs below.

---

## Step 1 — Health endpoint

**Goal:** Process is up and configuration is visible (without exposing secrets).

In a **second** terminal:

```bash
curl -sS http://127.0.0.1:8000/health | python3 -m json.tool
```

**Expect:**

- HTTP **200**.
- JSON includes `"status": "ok"` when `OPENAI_API_KEY` is non-empty and `config/agent_behavior.md` exists.
- `"openai_key_configured": true`, `"behavior_file_exists": true`.
- `"behavior_path"` and `"traces_path"` point to files under your project.

If `status` is `degraded`, fix `.env` or ensure the behavior file path is correct.

---

## Step 2 — OpenAPI documentation

**Goal:** API schema loads (useful for eval clients).

Open in a browser:

- [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

**Expect:** Swagger UI shows `POST /api/chat`, `GET /health`, and schemas for request/response bodies.

---

## Step 3 — Chat API: single `message` (server assigns `session_id`)

**Goal:** First turn works; response includes a `session_id` you can reuse.

```bash
curl -sS -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Suggest a simple 2-person vegetarian pasta."}' | python3 -m json.tool
```

**Expect:**

- HTTP **200**.
- Fields: `session_id`, `reply` (non-empty), `model`.
- Copy `session_id` for Step 4.

---

## Step 4 — Chat API: second `message` with same `session_id` (trace-backed history)

**Goal:** Follow-up uses prior turns loaded from `data/traces.json`.

Replace `PASTE_SESSION_ID` with the `session_id` from Step 3:
e9b98bf2-2fae-4529-a66e-37a801e8a627
```bash
curl -sS -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"PASTE_SESSION_ID","message":"Make it under 30 minutes."}' | python3 -m json.tool
```

**Expect:**

- HTTP **200**.
- `reply` should reflect the earlier pasta context (ingredients or constraints), not answer as if there were no prior message.

---

## Step 5 — Chat API: `X-Session-Id` header

**Goal:** Header overrides or supplies session id consistently with the body.

Pick a new UUID (or reuse one). Example:

```bash
SID="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
curl -sS -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: $SID" \
  -d '{"message":"What is a roux?"}' | python3 -m json.tool
```

**Expect:** Response `session_id` equals `$SID` (or matches the explicit policy: body `session_id` wins over header when both are set — try both and note behavior for your eval harness).

---

## Step 6 — Chat API: full `messages` array (client-owned history)

**Goal:** Eval scripts can send full dialogue; last turn must be `user`.

```bash
curl -sS -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "eval-messages-1",
    "messages": [
      {"role": "user", "content": "Define brunoise."},
      {"role": "assistant", "content": "A very fine dice cut, about 1–2 mm."},
      {"role": "user", "content": "What vegetables is it most used for?"}
    ]
  }' | python3 -m json.tool
```

**Expect:** HTTP **200** and an on-topic `reply`.

---

## Step 7 — Validation: empty body

**Goal:** Invalid requests return **422** with a clear error.

```bash
curl -sS -o /dev/stderr -w "\nHTTP_CODE:%{http_code}\n" \
  -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Expect:** `HTTP_CODE:422` and JSON `detail` mentioning `messages` / `message`.

---

## Step 8 — Validation: last message not from user

**Goal:** Server rejects histories that do not end with a user turn.

```bash
curl -sS -o /dev/stderr -w "\nHTTP_CODE:%{http_code}\n" \
  -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"bad-last-role","messages":[{"role":"user","content":"Hi"},{"role":"assistant","content":"Hello"}]}'
```

**Expect:** `HTTP_CODE:400` and `detail` explaining the last message must be from the user.

---

## Step 9 — Web UI

**Goal:** Browser uses the same `/api/chat` endpoint as your scripts.

1. Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/).
2. Send a short recipe question; **Expect:** your message and an assistant bubble appear.
3. Send a follow-up; **Expect:** context is preserved within the same tab session.
4. Click **New conversation**; **Expect:** transcript clears; next message starts a fresh `session_id` in `sessionStorage`.

---

## Step 10 — Trace file

**Goal:** Sessions are recorded in `data/traces.json` as a JSON array; the most recently updated session is first.

After several API or UI turns:

```bash
python3 -m json.tool data/traces.json | head -n 80
```

**Expect:**

- Top-level **array** of session objects.
- Each object has `session_id`, `created_at`, `updated_at`, `metadata`, `turns`.
- `turns` contains alternating `user` / `assistant` entries with `timestamp` and `content`.
- `metadata` includes `model`, `base_url`, `behavior_file`, `behavior_sha256`.

**Note:** `data/traces.json` is gitignored; create it by using the app at least once.

---

## Step 11 — Behavior file reload

**Goal:** Edits to evaluator instructions affect replies (reload is per request by default).

1. Edit `config/agent_behavior.md` (e.g. add “Always answer in exactly two sentences.”).
2. Send a **new** chat message via UI or `curl`.
3. **Expect:** Style change is reflected (within model limits).

No server restart required unless you change `.env` or Python code (restart after `.env` changes because settings are cached).

---

## Optional — Automated smoke (no pytest required)

From project root with `OPENAI_API_KEY` set (can be a dummy if you only run health/validation):

```bash
OPENAI_API_KEY=test .venv/bin/python -c "
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)
assert c.get('/health').status_code == 200
assert c.post('/api/chat', json={}).status_code == 422
print('smoke ok')
"
```

This does **not** call the real LLM. To test the full LLM path in automation, add dedicated tests with a mocked client or a test key.

---

## Quick reference

| Step | What you verify        |
| ---- | ---------------------- |
| 1    | `/health`              |
| 2    | `/docs`                |
| 3–5  | `POST /api/chat` modes |
| 6    | `messages` array       |
| 7–8  | Errors                 |
| 9    | Web UI                 |
| 10   | `data/traces.json`     |
| 11   | Behavior file          |

If any step fails, check the **uvicorn terminal** for stack traces and confirm you are running commands from the **project root** with the same port as the server.
