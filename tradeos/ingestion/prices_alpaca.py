"""End-of-day price ingestion via Alpaca Market Data v2.

WHY THIS EXISTS ALONGSIDE `prices.py`. Tiingo's free tier allows roughly 50 requests an hour and
500 unique symbols a month, and because it can only be asked for ONE symbol per request, a top-up
pass over 500 symbols cannot finish. Part 0 measured the consequence on 2026-09-09: **zero of 500
symbols had a bar at the latest NYSE session**, and the feed had stopped mid-alphabet at `PEB-PH`.
That is not a crash. It is the rate limit ending the run partway through a list that was sorted by
symbol, every single time, so price staleness in this database became **alphabetically biased** —
and the table's own calendar hid it by reporting 99% fresh.

Alpaca's free tier allows **200 requests per minute** with unlimited historical bars, and — the
part that actually matters — accepts **many symbols in one request**. 500 symbols is five requests,
not 500. The constraint disappears rather than being managed.

THE FREE TIER SERVES THE IEX FEED, NOT THE CONSOLIDATED TAPE. This is a real limitation and it is
recorded here rather than hidden. IEX is one exchange, carrying roughly 2-3% of US equity volume,
so a daily close computed from IEX prints can differ from the official consolidated close — most
visibly on thin names. That prediction has now been MEASURED rather than assumed: 1,324 day-pairs
against our own Tiingo rows on 2026-09-14 give 0.398% mean absolute difference, passing the 0.5%
migration gate. For this product's purpose that is acceptable: every outcome is an EXCESS return
measured against SPY over 7, 30 or 90 days and both legs come from the same feed.

But do not round the average up into a guarantee. The tail is real — DMLP 2.86% and JCTC 2.29%
EXCEED the 2% noise floor `receipts.scoring` applies, so on an illiquid symbol the choice of feed
can by itself move a verdict, and a Receipts verdict is sealed by trigger and never correctable.
Liquid names are nowhere near that. It would NOT be acceptable for intraday execution, and nothing
here should be repurposed for that. `docs/analysis/alpaca_vs_tiingo.md` holds the full numbers.

AUTHENTICATION IS BY HEADER, NEVER BY QUERY STRING. Alpaca uses `APCA-API-KEY-ID` and
`APCA-API-SECRET-KEY`. This is not a style preference: httpx puts the full request URL in its
exception messages, `ingest_rejects` stores that text, and a previous query-string scheme in this
codebase wrote a live API key into **1,172 `ingest_rejects` rows in plain text** for five weeks
(B-30). `reject()` redacts query strings and still must, but redaction is a net under the wire, not
the wire itself — with the credential in a header there is no credential in a URL for an exception
to carry. `follow_redirects=False` is load-bearing for the same reason: a header set on the client
is sent to whatever host a redirect lands on, and the allowlist below only checks the URL we build.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime
from urllib.parse import urlparse

import httpx
import psycopg

from .common import reject

log = logging.getLogger("tradeos.ingest.prices_alpaca")

# `adjustment=all` applies both splits and dividends, so forward returns are correct across a
# split. The source string records that, the same way the Tiingo adapter records ':adjusted'.
SOURCE = "alpaca:iex:adjusted"
ALPACA_HOST = "data.alpaca.markets"
ALPACA_BARS_URL = f"https://{ALPACA_HOST}/v2/stocks/bars"

# Symbols per request. Alpaca imposes no documented ceiling on the `symbols` list, but the request
# is a GET and the whole list goes in the query string, so the real limit is URL length. 100
# five-character symbols is well under any proxy's 8 KB line limit and turns 500 symbols into five
# requests. Raising this buys nothing: the free tier's 200 requests/minute is not the binding
# constraint at five requests.
BATCH = 100

# 200 requests/minute free tier = one per 300 ms. 350 ms leaves headroom for clock skew and for the
# fact that a paginated symbol batch issues several requests back to back.
MIN_INTERVAL = 0.35


class AlpacaClient:
    """Batched daily bars. One HTTP client, throttled, host-allowlisted, header-authenticated."""

    def __init__(self, key_id: str, secret_key: str, min_interval: float = MIN_INTERVAL):
        if not key_id or not secret_key:
            raise ValueError("ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY must both be set")
        self._client = httpx.Client(
            headers={"APCA-API-KEY-ID": key_id,
                     "APCA-API-SECRET-KEY": secret_key,
                     "Accept": "application/json"},
            timeout=60.0,
            follow_redirects=False,     # see the module docstring: a header follows a redirect
        )
        self._min_interval = min_interval
        self._last = 0.0

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def daily_batch(self, symbols: list[str], start: date, end: date) -> dict[str, list[dict]]:
        """Daily bars for MANY symbols in one call. Returns {SYMBOL: [bar, ...]}.

        Pagination: Alpaca returns `next_page_token` when the result is truncated, and the token
        covers the whole multi-symbol response rather than one symbol. Each page is merged into the
        same mapping, so a caller never has to know a page boundary happened. A symbol with no bars
        in the window is simply absent from the mapping, which the caller reads as "no data" —
        the same shape `TiingoClient.daily` returns None for.
        """
        if urlparse(ALPACA_BARS_URL).hostname != ALPACA_HOST:
            raise ValueError("Alpaca host allowlist violation")

        # Alpaca spells a class or preferred share with a DOT (GEF.B); this database stores the
        # hyphen form the SEC and Nasdaq use (GEF-B). A hyphen is not merely absent from Alpaca's
        # universe, it is a 400 `invalid symbol` that fails the WHOLE batch of 100 — so one
        # unconverted symbol costs 99 healthy ones their refresh. Convert on the way out and map
        # back on the way in, so no caller and no stored row ever sees the wire spelling.
        wire = {s.upper().replace("-", "."): s.upper() for s in symbols}

        out: dict[str, list[dict]] = {}
        params = {
            "symbols": ",".join(wire),
            "timeframe": "1Day",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "adjustment": "all",        # splits AND dividends
            # EXPLICIT, because Alpaca's default is SIP and this account cannot query recent SIP:
            # omitting it returns 403 `subscription does not permit querying recent SIP data` for
            # any window reaching today, which is every scheduled top-up. Worse when it did NOT
            # 403 — an older window quietly returned consolidated-tape bars while every row was
            # stored under SOURCE "alpaca:iex:adjusted", so the provenance string was false.
            # Asking for the feed we are entitled to makes the label true and the 403 impossible.
            "feed": "iex",
            "limit": 10000,
            "sort": "asc",
        }
        while True:
            self._throttle()
            resp = self._client.get(ALPACA_BARS_URL, params=params)
            if resp.status_code == 429:
                raise _RateLimited("alpaca 429")
            resp.raise_for_status()
            data = resp.json()
            for sym, bars in (data.get("bars") or {}).items():
                key = wire.get(sym.upper(), sym.upper())      # back to this database's spelling
                out.setdefault(key, []).extend(bars or [])
            token = data.get("next_page_token")
            if not token:
                return out
            params["page_token"] = token

    def close(self) -> None:
        self._client.close()


class _RateLimited(RuntimeError):
    """A 429 from Alpaca. Named so the pass can distinguish it from a bad symbol."""


def _valid_bar(bar: dict, today: date) -> tuple[date, float, float, float, float, float] | None:
    """Validate one Alpaca bar, returning (day, open, high, low, close, volume) or None.

    Mirrors `prices._valid_row` deliberately: the same three rejections (unparseable date, a bar
    dated in the future, a non-positive or inverted price) so the two adapters cannot disagree
    about what counts as a usable row. Alpaca's `t` is an RFC 3339 timestamp at midnight UTC for a
    daily bar, so only the date part is taken.
    """
    raw = bar.get("t")
    if not isinstance(raw, str):
        return None
    try:
        day = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None
    if day > today:
        return None
    o, h, low, c, v = bar.get("o"), bar.get("h"), bar.get("l"), bar.get("c"), bar.get("v")
    if c is None or c <= 0:
        return None
    if h is not None and low is not None and h < low:
        return None
    return day, o, h, low, c, v


def ingest_prices_alpaca(conn: psycopg.Connection, client: AlpacaClient,
                         symbols: list[str], start: date) -> dict:
    """Fetch and store daily bars for `symbols`, in batches.

    The counters match `ingest_prices` so the two are interchangeable to a caller and to anything
    reading `job_runs.detail`. `batches` is added because it is the number that explains the
    difference: 500 symbols is 5 batches here and 500 requests on Tiingo.

    A failed BATCH rejects the whole batch rather than one symbol, which is the one real cost of
    batching. It is bounded: the batch is retried once symbol-by-symbol is NOT done — instead the
    reject row names every symbol in the batch, so the next pass (ordered by staleness) picks them
    up first precisely because they are now the stalest. That is the staleness ordering doing its
    job rather than a bespoke retry path.
    """
    counters = {"symbols": len(symbols), "with_data": 0, "no_data": 0, "rows": 0, "rejected": 0,
                "rate_limited": False, "batches": 0}
    today = datetime.now(UTC).date()

    for i in range(0, len(symbols), BATCH):
        batch = [s.upper() for s in symbols[i:i + BATCH]]
        counters["batches"] += 1
        try:
            bars_by_symbol = client.daily_batch(batch, start, today)
        except _RateLimited:
            # Unlike Tiingo, a 429 here means the per-minute ceiling, not a monthly wall. Stop the
            # pass and say so; the remaining symbols stay stale and therefore sort to the FRONT of
            # the next run's work list.
            counters["rate_limited"] = True
            log.warning("prices_alpaca: 429; stopping with %d symbols untried",
                        len(symbols) - i)
            break
        except Exception as exc:        # one bad batch must never kill the run
            reject(conn, "prices_alpaca", ",".join(batch[:20]),
                   f"{type(exc).__name__}: {exc}", counters)
            conn.commit()
            continue

        for symbol in batch:
            bars = bars_by_symbol.get(symbol) or []
            if not bars:
                counters["no_data"] += 1
                continue
            inserted = 0
            with conn.cursor() as cur:
                for bar in bars:
                    v = _valid_bar(bar, today)
                    if v is None:
                        continue
                    day, o, h, low, c, vol = v
                    cur.execute(
                        """INSERT INTO prices_eod (symbol, day, open, high, low, close, volume, source)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (symbol, day) DO UPDATE SET
                               open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                               close=EXCLUDED.close, volume=EXCLUDED.volume, source=EXCLUDED.source""",
                        (symbol, day, o, h, low, c, vol, SOURCE),
                    )
                    inserted += 1
            conn.commit()
            counters["with_data"] += 1
            counters["rows"] += inserted
        log.info("prices_alpaca: batch %d/%d, %d symbols, %d rows so far",
                 counters["batches"], (len(symbols) + BATCH - 1) // BATCH, len(batch),
                 counters["rows"])
    return counters
