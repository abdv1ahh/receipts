# Runbook — giving the model chain a working fallback

**Written 2026-09-11.** Measured today, not recalled:

| Link | Status |
|---|---|
| `gemini` | ✅ **HTTP 200**, 50 models listed. Working — and it is the **only** link that works |
| `openai` | 🔴 **HTTP 410** `github_models_retirement_brownout` |

`EXPLAIN_PROVIDER=gemini,openai`. The second link points at GitHub Models, which is in permanent
retirement brownout and has answered 410 since 2026-07-30. So there is no fallback: **if Gemini trips
its free daily quota, every AI prose surface in the product silently drops to its deterministic
template** — and `docs/state.md` records Gemini answering normally and then 429-ing within the same
minute. This is a live single point of failure.

**Nothing in the code needs changing.** `llm._openai` already speaks to whatever `OPENAI_BASE_URL`
names. This is three environment variables.

---

## 1. What `llm.py` already supports

From the module docstring:

> `openai` — **ANY OpenAI-compatible `/chat/completions` endpoint** (Groq, OpenRouter, …).
> `OPENAI_BASE_URL` + `OPENAI_API_KEY` + `OPENAI_MODEL` / `OPENAI_MODEL_FAST`.

So the question is not "which providers are supported" — any OpenAI-compatible one is. The question
is **which are already exercised by the test suite**, because those are the ones proven to work with
this exact client. `tests/test_llm.py` pins two base URLs:

| Provider | Base URL in the tests | Line |
|---|---|---|
| **Groq** | `https://api.groq.com/openai/v1` | `test_llm.py:127` |
| **OpenRouter** | `https://openrouter.ai/api/v1` | `test_llm.py:169, 201` |

OpenRouter is also the **built-in default** when `OPENAI_BASE_URL` is unset (`llm.py:_openai`).

Two constraints the client enforces, worth knowing before choosing:

- **HTTPS only.** A plaintext `OPENAI_BASE_URL` raises `ValueError`, asserted by
  `test_plaintext_base_url_is_refused`.
- **`/chat/completions` is appended for you.** Set the base *without* it — `…/openai/v1`, not
  `…/openai/v1/chat/completions`.

---

## 2. The options, best first

> **Model IDs change and free tiers get retired — that is exactly how the current slot died.** Each
> option below carries a command to list what your key can actually see. Run it and use a name from
> that list rather than trusting the one printed here.

### Option 1 — Groq ⭐ recommended

Fastest inference of the three, genuinely free, no card. Already named as the fix in `docs/state.md`.

| | |
|---|---|
| **Sign up** | <https://console.groq.com/keys> |
| **`OPENAI_BASE_URL`** | `https://api.groq.com/openai/v1` |
| **`OPENAI_MODEL`** | `llama-3.3-70b-versatile` |
| *optional* `OPENAI_MODEL_FAST` | `llama-3.1-8b-instant` |
| **Limits** | Free tier is rate-limited per-model on requests/minute, requests/day and tokens/minute. Generous for this product's volume — prose generation is bursty and low-volume. Current numbers: <https://console.groq.com/docs/rate-limits> |
| **Card required** | No |

List what your key can see:

```bash
curl -s https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer $GROQ_KEY" | python3 -m json.tool | grep '"id"'
```

### Option 2 — OpenRouter

Broadest model choice, and the client's built-in default base. Aggregates many providers behind one
key, several with a `:free` tier.

| | |
|---|---|
| **Sign up** | <https://openrouter.ai/keys> |
| **`OPENAI_BASE_URL`** | `https://openrouter.ai/api/v1` |
| **`OPENAI_MODEL`** | a `:free` model id, e.g. `meta-llama/llama-3.3-70b-instruct:free` |
| **Limits** | `:free` models are rate-limited per day and can be busy at peak; a small credit balance raises the ceiling. Free-model list: <https://openrouter.ai/models?max_price=0> |
| **Card required** | No, for `:free` models |

List free models:

```bash
curl -s https://openrouter.ai/api/v1/models | python3 -c "
import json,sys
for m in json.load(sys.stdin)['data']:
    if m['id'].endswith(':free'): print(m['id'])"
```

### Option 3 — Cerebras

Very fast, free tier, no card. **Not in the test fixtures** — OpenAI-compatible and expected to work,
but unlike the two above it has not been exercised against this client. Choose it only if both
others are unavailable, and verify with the command in §5.

| | |
|---|---|
| **Sign up** | <https://cloud.cerebras.ai> |
| **`OPENAI_BASE_URL`** | `https://api.cerebras.ai/v1` |
| **`OPENAI_MODEL`** | `llama-3.3-70b` |
| **Limits** | Free tier capped on requests/day and tokens/day. See the dashboard after signup |
| **Card required** | No |

---

## 3. The exact three lines to paste into `.env`

`.env` **already has all three keys** — they currently point at the dead GitHub Models endpoint.
**Replace the existing lines, do not append**, or the later value silently wins.

Taking Groq (Option 1):

```
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_API_KEY=<paste the key from console.groq.com/keys>
OPENAI_MODEL=llama-3.3-70b-versatile
```

Leave `EXPLAIN_PROVIDER=gemini,openai` exactly as it is — the chain is already correct; only its
second link was broken.

---

## 4. ⚠️ A value in `.env` alone does not reach the container

`docker-compose.yml` **enumerates every variable explicitly** rather than using `env_file:`:

```yaml
      OPENAI_BASE_URL: ${OPENAI_BASE_URL:-}
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      OPENAI_MODEL: ${OPENAI_MODEL:-}
      OPENAI_MODEL_FAST: ${OPENAI_MODEL_FAST:-}
```

The good news: **all four are already listed for both `api` and `worker`** (lines 31–34 and 66–69),
so no compose edit is needed for this change. But the containers read their environment **at start**,
so after editing `.env` you must recreate them:

```bash
docker compose up -d api worker
```

Without that, `.env` holds the new key, `config.openai_compat_configured()` reads the **host's**
environment and cheerfully reports "connected", and the running process still has the dead one. That
is `CLAUDE.md` §0i, and it has cost this project time before.

> If you add a *new* variable later (say `OPENAI_MODEL_FAST` when it isn't listed), it must be added
> to **both** the `api` and `worker` blocks. `docker-compose.prod.yml` uses `env_file:` and needs no
> such edit — only the base file enumerates.

---

## 5. Verify it — the exact command

```bash
docker compose exec -T api python -m tradeos.cli check-source llm_openai
```

**Use `check-source`, not a page in the browser.** Per `CLAUDE.md` §0x, `llm.complete` falls through
to the next provider on failure, so any probe using the configured chain answers for **Gemini** and
reports OK for a dead OpenAI key. That is precisely how this slot served 410s for five weeks while
every surface looked fine. `check-source llm_openai` forces **one** provider.

Check the other link too — it should still be green:

```bash
docker compose exec -T api python -m tradeos.cli check-source llm_gemini
```

Then confirm a real surface returns model prose rather than its template. The suite runs on
`template` by design, so **tests passing proves nothing here**:

```bash
curl -s localhost:8000/api/news | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('used_template:', d.get('used_template'))"
```

`used_template: false` is the answer you want.

**Prove the fallback actually falls back.** A fallback that has never been exercised is a guess.
Temporarily put the broken link first and confirm prose still appears:

```bash
EXPLAIN_PROVIDER=openai docker compose exec -T api python -m tradeos.cli check-source llm_openai
```

---

## 6. What good looks like

| Command | Expected |
|---|---|
| `check-source llm_openai` | ✅ connected, a real completion returned |
| `check-source llm_gemini` | ✅ connected |
| `/integrations` page | both model links green |
| `cli preflight` | no complaint about `EXPLAIN_PROVIDER` |

Once both links are live, Gemini tripping its daily quota stops being an outage and becomes a
failover — which is what the chain was built for and has never once been able to do.

---

## 7. Note on scope

**No key was invented, guessed, or written anywhere.** `.env` is unchanged — the owner pastes the key
themselves. Nothing in this runbook has been applied; it is a set of instructions, and the `openai`
slot is still returning 410 as of 2026-09-11.
