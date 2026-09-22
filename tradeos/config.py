"""TradeOSS configuration. Everything comes from the environment; nothing secret lives in code."""
import os


class ConfigError(RuntimeError):
    pass


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise ConfigError("DATABASE_URL is not set")
    return url


# The URL this instance is reachable at from OUTSIDE it, and the reason it has to exist.
#
# There was no base URL anywhere in this repository. Measured across `config.py`, `app.py` and
# `docker-compose.yml`, the only matches for BASE_URL / SITE_URL / PUBLIC_URL were
# `OPENAI_BASE_URL` and a per-request `request.base_url` used by Stripe checkout. The consequence
# was that `og:image` on `/r/{handle}` and `/s/{symbol}` pointed at a RELATIVE path, which the Open
# Graph protocol does not accept, so a shared record produced a bare text link on every platform
# and the entire distribution model had never worked once.
#
# NOT derived from `request.base_url`. That comes from the Host header, which any client can set,
# and this value is written into a cached public meta tag — so it would be a host-header injection
# into the one artefact this product asks strangers to trust. Stripe's use of `request.base_url` is
# a redirect the user immediately follows and is a different risk.
_DEV_BASE_URL = "http://localhost:8000"


def public_base_url() -> str:
    """The absolute origin, with no trailing slash. Falls back to localhost for development.

    Deliberately does NOT raise when unset, unlike `database_url`: a missing base URL must not stop
    a developer running the app, and the cost of being wrong is an unresolvable preview image
    rather than a leaked secret or a corrupted write. `preflight` fails on it instead, which is
    where a production misconfiguration belongs — see `public_base_url_configured`.
    """
    url = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if not url:
        return _DEV_BASE_URL
    if not url.startswith(("http://", "https://")):
        # Refused rather than coerced. Guessing the scheme would silently emit `http://` for a
        # site served over TLS, and a mixed-content preview image is not fetched at all.
        raise ConfigError(f"PUBLIC_BASE_URL must start with http:// or https:// (got {url!r})")
    return url


def public_base_url_configured() -> bool:
    return bool((os.environ.get("PUBLIC_BASE_URL") or "").strip())
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
def sentry_configured() -> bool:
    """Error tracking. `app.py` only initialises it when the DSN is present AND the SDK is
    installed, and logs a warning for the DSN-without-SDK case rather than starting up blind."""
    return bool(os.environ.get("SENTRY_DSN"))


def brand_name() -> str:
    """The public product name. A single config value so the display name can change without a
    refactor — nothing renames modules, tables or the package for branding."""
    return os.environ.get("BRAND_NAME", "Receipts").strip() or "Receipts"
