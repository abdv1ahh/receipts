"""TradeOSS configuration. Everything comes from the environment; nothing secret lives in code."""
import os


class ConfigError(RuntimeError):
    pass


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise ConfigError("DATABASE_URL is not set")
    return url


def _flag(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() in ("1", "true", "yes")


def short_interest_enabled() -> bool:
    """Modular input. Reserved: short interest is ingested as context; weighting it into the
    convergence score is a logged version bump (decision #31), gated by this flag when it lands.

    PARKED ON PURPOSE, confirmed by the owner 2026-07-26 — not debris. `ingestion/finra.py` and the
    `short_interest` table exist and are fed; nothing reads them yet. A future cleanup pass will
    find an ingestion path with no consumer and be tempted; this is the note saying it was already
    considered and kept. See docs/dead_code.md A-01."""
    return _flag("ENABLE_SHORT_INTEREST")


def reddit_configured() -> bool:
    """Reddit sentiment (Slice H) runs only when the operator supplies their own free API app
    credentials; until then the source is 'not connected', honestly (never simulated)."""
    return bool(os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET"))


def reddit_client_id() -> str:
    return os.environ.get("REDDIT_CLIENT_ID", "")


def reddit_client_secret() -> str:
    return os.environ.get("REDDIT_CLIENT_SECRET", "")


def youtube_configured() -> bool:
    """YouTube sentiment (Slice H) runs only with the operator's own free Data API key."""
    return bool(os.environ.get("YOUTUBE_API_KEY"))


def tiingo_configured() -> bool:
    """End-of-day prices — how claim outcomes get scored. Free tier."""
    return bool(os.environ.get("TIINGO_API_KEY"))


def alpaca_configured() -> bool:
    """End-of-day prices via Alpaca — the replacement for Tiingo as the price source.

    BOTH halves are required. A key id without its secret is not a half-working configuration, it
    is an unauthenticated client that will 403 on every bar, so this reports False rather than
    letting a pass start and fail 500 times."""
    return bool(os.environ.get("ALPACA_API_KEY_ID") and os.environ.get("ALPACA_API_SECRET_KEY"))


def alpaca_credentials() -> tuple[str, str]:
    """(key id, secret key). Raises rather than returning a blank, because a blank credential
    reaches Alpaca as an anonymous request and comes back 403 — an error that reads like an
    outage instead of like a missing key."""
    key_id = os.environ.get("ALPACA_API_KEY_ID", "")
    secret = os.environ.get("ALPACA_API_SECRET_KEY", "")
    if not key_id or not secret:
        missing = " and ".join(n for n, v in
                               (("ALPACA_API_KEY_ID", key_id), ("ALPACA_API_SECRET_KEY", secret))
                               if not v)
        raise ConfigError(
            f"{missing} is not set. Free key: https://app.alpaca.markets/signup — and note that "
            "docker-compose.yml enumerates every variable it passes, so a value in .env alone "
            "does not reach the container (see docs/runbooks/ and CLAUDE.md §0i)."
        )
    return key_id, secret


def openfigi_configured() -> bool:
    """CUSIP -> ticker mapping for 13F holdings. Works keyless at a low rate limit; a free key
    raises it."""
    return bool(os.environ.get("OPENFIGI_API_KEY"))


def gemini_configured() -> bool:
    """The first link in the EXPLAIN_PROVIDER chain. Free tier, per-model daily allowance."""
    return bool(os.environ.get("GEMINI_API_KEY"))


def openai_compat_configured() -> bool:
    """The second link in the chain. Deliberately named for the PROTOCOL rather than the vendor:
    the slot has been pointed at GitHub Models and can be pointed at Groq, OpenRouter or OpenAI
    itself without a code change, because `llm._openai` speaks to whatever `OPENAI_BASE_URL`
    names. A base URL without a key is not configured — the request would 401."""
    return bool(os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_BASE_URL"))


def stripe_configured() -> bool:
    """Billing. Absent, `billing.py` reports the free launch mode rather than failing a checkout."""
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


def sentry_configured() -> bool:
    """Error tracking. `app.py` only initialises it when the DSN is present AND the SDK is
    installed, and logs a warning for the DSN-without-SDK case rather than starting up blind."""
    return bool(os.environ.get("SENTRY_DSN"))


def brand_name() -> str:
    """The public product name. A single config value so the display name can change without a
    refactor — nothing renames modules, tables or the package for branding."""
    return os.environ.get("BRAND_NAME", "Rhumb").strip() or "Rhumb"


def sec_user_agent() -> str:
    """SEC fair-access policy requires a declared User-Agent identifying the requester,
    conventionally 'Name contact@email'. We refuse to run without one."""
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if "@" not in ua:
        raise ConfigError(
            "SEC_USER_AGENT must be set to something like 'TradeOSS admin@yourdomain.com' "
            "(SEC fair access policy requires a contact address)."
        )
    return ua
