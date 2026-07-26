"""Rate limiting for the surfaces a stranger can reach, and the ones that cost money (Phase 9).

Two different problems wear the same name here, and conflating them produces a limiter that is
wrong for both:

  **Abuse of the public surface.** `/api/public/*` and `/api/ledger` answer anyone, take no
  session, and run real queries. Nothing stopped one client from calling them in a loop.

  **Cost.** The model paths spend a metered quota. Gemini's free daily allowance ran out twice in
  one session of ordinary development, so a handful of enthusiastic users — or one script — can
  silence every AI surface for everybody until midnight UTC. That is not a denial-of-service
  concern, it is a bill and a shared resource.

**This is an in-process limiter, and that is a real limitation, stated rather than buried.** It is
a dict in one worker. It resets on restart, and with more than one API replica each replica gets
its own allowance, so the effective limit multiplies by the replica count. That is honest for the
current deployment — one container — and it is the correct amount of machinery for it: the
alternative is Redis, which would be the eleventh line of `requirements.txt` and a second thing to
operate for a product that has not launched. `docs/deploy.md` records the constraint so whoever
scales past one replica knows to replace this rather than discovering it.

The login path is deliberately NOT here. It is limited in `authn` against a database table, which
survives a restart and is shared across replicas — credential stuffing is worth paying for that.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("tradeos.ratelimit")

# (requests, per_seconds). Deliberately generous: the aim is to stop a loop, not to make a
# legitimate reader feel watched. A visitor clicking every country on the marketing site's map
# fires a handful of requests in a few seconds and must never see one of these.
LIMITS: dict[str, tuple[int, int]] = {
    "public": (120, 60),      # the whole unauthenticated surface, per client, per minute
    "model": (20, 300),       # any route that may spend model quota, per client, per 5 minutes
    "upload": (30, 3600),     # image uploads, per client, per hour
    # Verification and reset. Tight, because these send mail to a third party and because a token
    # guess is cheap: 32 bytes of entropy makes brute force hopeless anyway, but there is no reason
    # to host the attempt. Per-address limiting also lives in `authn`, which this does not replace
    # — a client can rotate its IP, and an inbox cannot rotate itself.
    "auth_token": (10, 900),
}

_buckets: dict[tuple[str, str], list[float]] = {}
_lock = threading.Lock()      # uvicorn runs handlers on a threadpool; the dict is shared


def _prune(hits: list[float], window: int, now: float) -> list[float]:
    return [t for t in hits if now - t < window]


def check(bucket: str, client: str | None, now: float | None = None) -> tuple[bool, int]:
    """(allowed, retry_after_seconds). Records the hit when it is allowed.

    A sliding window of timestamps rather than a fixed counter: a fixed window lets a caller spend
    the whole allowance in the last second of one window and the whole of the next in the first
    second of the following one, which is twice the intended rate at exactly the wrong moment.
    """
    limit, window = LIMITS.get(bucket, LIMITS["public"])
    key = (bucket, client or "-")
    now = now if now is not None else time.monotonic()

    with _lock:
        hits = _prune(_buckets.get(key, []), window, now)
        if len(hits) >= limit:
            retry = max(1, int(window - (now - hits[0])))
            _buckets[key] = hits
            return False, retry
        hits.append(now)
        _buckets[key] = hits

        # Opportunistic cleanup so an unbounded stream of distinct clients cannot grow this dict
        # forever. Cheap, amortised, and it only ever drops entries that are already expired.
        if len(_buckets) > 4096:
            for k in [k for k, v in _buckets.items() if not _prune(v, LIMITS.get(k[0], LIMITS["public"])[1], now)]:
                _buckets.pop(k, None)
    return True, 0


def client_key(request) -> str:
    """Who to count against.

    `request.client.host` is the peer address. Behind the production reverse proxy that is the
    proxy, so every visitor would share one bucket — hence the X-Forwarded-For read. That header is
    forgeable by anyone talking to the app DIRECTLY, so this is only trustworthy when the app is
    reachable *only* through the proxy, which is how `deploy/Caddyfile` is written. Stated plainly
    because a limiter keyed on a spoofable value gives false comfort otherwise: the fallback below
    is what actually holds if the deployment is misconfigured.
    """
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def reset() -> None:
    """Drop all state. For tests only — never call this from a request path."""
    with _lock:
        _buckets.clear()
