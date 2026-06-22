# Windows Copilot API — agent guide

## What this is

An unofficial Python library + OpenAI-compatible server that bridges Microsoft
Copilot consumer chat into a callable API. Two modes:

- **Python library** (`copilot/`): `CopilotClient.chat()` / `.stream()`
- **OpenAI server** (`server/`): FastAPI, `python app.py` → `localhost:8000/v1`

No API key needed — uses your signed-in Microsoft Copilot account.

## Setup (must-know)

```bash
pip install -r requirements.txt
playwright install chromium        # required, easy to forget
python -m copilot login            # interactive sign-in, saves to session/
python app.py                      # start server
```

- `session/` is git-ignored and contains secrets (cookies + tokens)
- Docker: sign-in on host **first**, then `docker compose up` (container can't do browser login)

## Architecture

```
copilot/          core library
  driver.py       pure-HTTP curl_cffi driver (impersonates Chrome, WebSocket protocol)
  client.py       high-level CopilotClient API
  browser.py      Playwright fallback for sign-in + headless token refresh
  auth.py         caches cookies+MSAL token in session/token.json, auto-refreshes
  challenges.py   hashcash + arithmetic PoW solvers (chat socket challenge)
server/           FastAPI OpenAI-compatible server
  api.py          routes + _upstream_lock (serializes upstream calls)
  config.py       MODEL_NAME="copilot", RATE_LIMIT_RPM=12, RATE_LIMIT_BURST=4
  ratelimit.py    token bucket (env: RATE_LIMIT_RPM, RATE_LIMIT_BURST)
  schemas.py      Pydantic request models (+ extra_body conversation_id)
  prompt.py       flattens OpenAI messages[] → single Copilot prompt string
  openai_format.py builds OpenAI wire shapes
app.py            entry point: `python app.py`
```

## Critical constraints

- **Single-user, serialized**: `_upstream_lock` in `server/api.py:54` — exactly one
  upstream Copilot chat at a time. Parallel HTTP requests queue behind it.
- **Self-imposed rate limit**: token bucket, default 12 RPM / 4 burst. Returns 429
  when exceeded. Disable with `RATE_LIMIT_RPM=0`.
- **`session/token.json` auto-refreshes** headlessly via Playwright. The `load_auth()`
  function in `copilot/auth.py` handles this — it reads cookies from the persistent
  browser profile in `session/profile/`.

## Common operations

| Task | Command |
|------|---------|
| Start server | `python app.py` (default 127.0.0.1:8000, env: `HOST`/`PORT`) |
| Direct chat | `python -m copilot ask "Hello!"` |
| Single test | `python -m unittest tests.test_server` |
| Stress test | `python tests/stress.py` (while server runs) |
| Rate probe | `python tests/ratelimit.py --rpm 20 --minutes 3` |
| GPQA bench | `python tests/gpqa_bench.py path/to/gpqa.csv --limit 10` |
| Sign in | `python -m copilot login` |
| Run with uvicorn | `uvicorn server.api:app --host 0.0.0.0 --port 8080` |

## Chat protocol (for debugging Copilot's API)

1. `POST /c/api/conversations` → `{"id": "..."}` (cookies auth only, no Bearer)
2. `wss://copilot.microsoft.com/c/api/chat?api-version=2` (+ `&accessToken=...` when signed in)
3. Send: `{"event":"send","conversationId":"...","content":[{"type":"text","text":"..."}],"mode":"chat"}`
4. Receive: `"challenge"` (solve PoW) → `"appendText"`* → `"done"`

Access token scope must be `ChatAI.ReadWrite` — wrong-audience tokens 401 the WebSocket.

## Gotchas

- **Server/VPS failure**: Copilot may stall on Cloudflare verification (empty challenge).
  Fix: open `copilot.microsoft.com` in a real browser once to set `cf_clearance` cookie.
- **Region block**: anonymous Copilot is geo-restricted (e.g. India). Use signed-in path
  or set `proxy=...` on `CopilotClient` (also works via env on `BrowserCopilot`).
- **No lint/typecheck config**: no formatter, no pytest — just `unittest` and raw scripts.
  Add nothing that expects them.
- **`curl_cffi` WebSocket**: custom `_recv_frame` with `select()` — the library's own
  `recv()` loops on `CURLE_AGAIN` forever, so we drive the loop ourselves with a deadline.
