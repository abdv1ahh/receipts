# Turning on the live AI — for free

TradeOS runs **fully without any AI** (every AI surface has a deterministic fallback). To light up the
*live* AI — the Morning Brief summary, the "why it matters" on news, the "why it's trending" on social,
the AI chart reads, and the assistant — point it at one **free** provider. Pick **one** below, set four
lines of config, restart. If a provider is ever rate-limited, TradeOS quietly falls back to templates —
it never breaks and never fabricates.

You set these in `.env` (local dev) or `.env.production` (server), then restart the stack.

---

## Option A — GitHub Models (free with your GitHub Pro) ★ recommended for you

1. Create a GitHub token: **https://github.com/settings/personal-access-tokens** → *Generate new token*
   (fine-grained). Under **Account permissions**, give it **Models: read-only**. Copy the token.
2. Put this in your env file:
   ```
   EXPLAIN_PROVIDER=openai
   OPENAI_BASE_URL=https://models.github.ai/inference
   OPENAI_API_KEY=github_pat_...      # the token you just made
   OPENAI_MODEL=openai/gpt-4o-mini    # supports vision, so chart reads work too
   ```
3. Restart: `docker compose up -d` (local) or the prod command in DEPLOY.md.

Free-tier limits are modest (a few requests/minute) — plenty for a personal deploy, and TradeOS
throttles + caches so it stays within them.

## Option B — Groq (free, very fast)

1. Sign up free at **https://console.groq.com** → *API Keys* → create one (`gsk_...`).
2. Env file:
   ```
   EXPLAIN_PROVIDER=openai
   OPENAI_BASE_URL=https://api.groq.com/openai/v1
   OPENAI_API_KEY=gsk_...
   OPENAI_MODEL=llama-3.3-70b-versatile
   ```
   (Groq's Llama models are text-only, so the **chart reads** fall back to the level analysis; the
   brief, the "why", and the assistant all work great.)

## Option C — OpenRouter (free models, incl. vision)

1. Create a key at **https://openrouter.ai/keys** (`sk-or-...`).
2. Env file:
   ```
   EXPLAIN_PROVIDER=openai
   OPENAI_BASE_URL=https://openrouter.ai/api/v1
   OPENAI_API_KEY=sk-or-...
   OPENAI_MODEL=meta-llama/llama-3.1-8b-instruct:free   # text; for chart reads use a vision model, e.g. qwen/qwen-2-vl-7b-instruct
   ```

---

## Verify it's live

Restart, then open TradeOS:
- **Morning Brief** — the opener's tag flips from `auto-generated` to **✦ AI summary**.
- **News / Social** — cards show **✦ AI analysis** instead of `auto`.
- **Journal → a trade with a chart** — the panel shows **✦ AI vision** with a real chart read (needs a
  vision-capable model — Option A or a vision model on C).

You can also confirm from the server: `docker compose logs api | grep -i llm` shows no cooldown warnings.

## Notes

- **Vision (chart reads)** needs a vision-capable model: GitHub Models `gpt-4o`/`gpt-4o-mini` (Option A)
  or a vision model on OpenRouter (Option C). Text AI works on all three.
- **Switching back** to no-AI is one line: `EXPLAIN_PROVIDER=template`. Everything keeps working.
- The old free **Gemini** path still exists (`EXPLAIN_PROVIDER=gemini` + `GEMINI_API_KEY`) if you prefer
  it — but the options above give you far more free headroom.
