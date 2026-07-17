"""TradeOS configuration. Everything comes from the environment; nothing secret lives in code."""
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


def congress_enabled() -> bool:
    """Modular input (Decision 11). Off: no clean structured primary source (decision #29)."""
    return _flag("ENABLE_CONGRESS")


def short_interest_enabled() -> bool:
    """Modular input. Reserved: short interest is ingested as context; weighting it into the
    convergence score is a logged version bump (decision #31), gated by this flag when it lands."""
    return _flag("ENABLE_SHORT_INTEREST")


def sec_user_agent() -> str:
    """SEC fair-access policy requires a declared User-Agent identifying the requester,
    conventionally 'Name contact@email'. We refuse to run without one."""
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if "@" not in ua:
        raise ConfigError(
            "SEC_USER_AGENT must be set to something like 'TradeOS admin@yourdomain.com' "
            "(SEC fair access policy requires a contact address)."
        )
    return ua
