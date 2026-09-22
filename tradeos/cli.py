"""TradeOSS command line.

  python -m tradeos.cli migrate
  python -m tradeos.cli sync-tickers
  python -m tradeos.cli ingest-form4  --date 2026-07-14 [--limit 25]
  python -m tradeos.cli ingest-13dg   --date 2026-07-14 [--limit 25]
  python -m tradeos.cli ingest-13f    --date 2026-07-14 [--limit 25]
  python -m tradeos.cli backfill-form4 --from 2024-07-01 --to 2026-07-14
  python -m tradeos.cli backfill-13dg  --from 2024-07-01 --to 2026-07-14
  python -m tradeos.cli backfill-13f   --from 2024-07-01 --to 2026-07-14
  python -m tradeos.cli resolve-entities
  python -m tradeos.cli resolve-cusips [--limit 200]
  python -m tradeos.cli status
"""
from __future__ import annotations

import argparse
import logging
import os
import secrets
from datetime import date

from . import authn, config, db
from .ingestion import prices_alpaca
from .ingestion.prices_alpaca import AlpacaClient, ingest_prices_alpaca

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

# httpx logs every request at INFO with the FULL URL, query string included. Any API authenticated
# with `?token=` or `?key=` therefore prints its credential into stdout, and from there into a CI
# log, a captured shell session, or a screenshot. Tiingo is exactly that shape, and the key showed
# up in plain text the first time deep price history was pulled by hand.
#
# `scheduler.redact()` already strips query strings from anything STORED, but it never saw these —
# they come from httpx's own logger, not from an exception this code handles. Lifting that one
# logger to WARNING removes the whole class of leak and costs nothing: the suppressed lines say
# "HTTP Request: GET <url> 200 OK", which the per-source counters already report more usefully.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def cmd_migrate(_args) -> None:
    with db.connect() as conn:
        ran = db.run_migrations(conn)
        print(f"applied migrations: {ran or 'none (up to date)'}")
def _price_worklist(conn, args) -> list[str]:
    """The symbols a price pass should fetch, in the order it should fetch them.

    THREE SELECTORS WHERE THERE WERE SIX. `--symbols-from-clusters`, `--only-missing` and
    `--only-missing-history` all started from `signal_clusters`, and that table is gone: the
    universe is now whatever the price vendor lists (see `_universe_worklist`), which is the whole
    reason a fresh clone has AAPL in it at all.

    Every branch returns a list ordered by STALENESS, never by symbol — see the note above
    `_STALENESS_ORDER` in `ingestion/prices_alpaca.py` for the measured damage the alphabetical
    version did.
    """
    if args.only_stale:
        # Default the cutoff to the freshest close anything has, so "stale" means "behind the rest
        # of the table" without the operator having to look the date up.
        if args.stale_before:
            cutoff = date.fromisoformat(args.stale_before)
        else:
            with conn.cursor() as cur:
                cur.execute("SELECT max(day) FROM prices_eod")
                cutoff = cur.fetchone()[0]
        return prices_alpaca.symbols_stale(conn, cutoff) if cutoff else []
    return [s.strip().upper() for s in args.symbols.split(",") if s.strip()]


def _universe_worklist(conn, client, only_new: bool) -> list[str]:
    """Every tradable, non-OTC US equity and ETF Alpaca lists, oldest-data-first.

    THE POINT OF THIS FUNCTION IS WHAT IT DOES NOT READ. Every other selector above starts from
    `signal_clusters`, so the set of symbols anyone could publish a call on was decided by an
    insider signal — 2,018 small-cap-skewed names. Measured 2026-09-22 against the list a person
    actually reaches for, 18 of 21 were absent, including AAPL, NVDA, TSLA, GOOGL, AMZN, META and
    QQQ. On a fresh clone the research tables do not exist at all, so a new instance had an empty
    universe and nothing a caller could call. This asks the price vendor what exists instead.

    Ordered by staleness, oldest first, for the reason `symbols_stale` is: a quota-limited pass
    that ends early must leave the table evenly behind rather than alphabetically behind. SPY leads
    regardless — it is the benchmark, and a stale SPY makes every other symbol unscoreable.
    """
    listed = client.assets()
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, max(day) FROM prices_eod GROUP BY symbol")
        held = dict(cur.fetchall())
    if only_new:
        return sorted(set(listed) - set(held))
    # `date.min` sorts the never-fetched to the front, which is what a first run wants.
    ordered = sorted(listed, key=lambda sym: (held.get(sym) or date.min, sym))
    return prices_alpaca._spy_first(ordered)


def cmd_ingest_prices_alpaca(args) -> None:
    """The default price path. Batched, so 500 symbols is five requests rather than 500."""
    start = date.fromisoformat(args.start)
    key_id, secret = config.alpaca_credentials()
    client = AlpacaClient(key_id, secret)
    try:
        with db.connect() as conn:
            if getattr(args, "universe", False):
                symbols = _universe_worklist(conn, client, only_new=args.only_new)
            else:
                symbols = _price_worklist(conn, args)
            if args.limit:
                symbols = symbols[: args.limit]
            counters = ingest_prices_alpaca(conn, client, symbols, start)
        print(f"ingest-prices-alpaca: {counters}")
    finally:
        client.close()
def cmd_check_source(args) -> None:
    """Make a REAL call to one source and say plainly whether it worked.

    `status` reports what has already been ingested and `preflight` reports what is configured;
    neither answers the question an operator actually has after pasting a key in, which is "did
    that work?". This does, and it names the failure rather than leaving a silent empty panel.
    """
    from . import sources
    key = args.source
    src = sources.by_key(key)
    if not src:
        print(f"check-source: unknown source {key!r}. Known: "
              f"{', '.join(s['key'] for s in sources.catalog())}")
        raise SystemExit(2)
    if src["state"] == sources.NEEDS_KEY:
        print(f"check-source {key}: NOT CONFIGURED — set {' and '.join(src['env'])} in .env, then "
              f"restart with `docker compose up -d`.")
        print(f"  where to get it: {src['signup_url']}")
        raise SystemExit(1)
    if src["state"] == sources.UNAVAILABLE:
        print(f"check-source {key}: UNAVAILABLE by design — {src['note']}")
        raise SystemExit(1)

    ok, detail = _probe(key)
    print(f"check-source {key}: {'OK' if ok else 'FAILED'} — {detail}")
    raise SystemExit(0 if ok else 1)


def _probe(key: str) -> tuple[bool, str]:
    """One cheap live call per source. Returns (ok, human-readable detail).

    ONE SOURCE, because there is one source. Thirteen probes went with the plane they belonged to;
    this is the Alpaca one, unchanged.

    Exceptions are caught and described rather than raised: an operator running this has just
    pasted a credential and needs to be told what is wrong, not shown a traceback. The message
    never echoes the credential — httpx puts the full URL in its exception text, so only the
    exception TYPE and status code are surfaced.
    """
    import httpx
    try:
        if key == "alpaca":
            # Ask for ONE bar of SPY. A bad or missing credential returns 401/403 here — unlike
            # OpenFIGI and Tiingo's /api/test, this endpoint does not answer unauthenticated
            # callers at all, so a 200 genuinely proves the key works. Cheap: one bar, one symbol.
            # `config` is rebound by a local import later in this function, which makes
            # the module-level name unusable here (ruff F823). Alias it.
            from . import config as _config
            from .ingestion.prices_alpaca import ALPACA_BARS_URL
            key_id, secret = _config.alpaca_credentials()
            with httpx.Client(timeout=20.0, follow_redirects=False) as client:
                r = client.get(ALPACA_BARS_URL,
                               headers={"APCA-API-KEY-ID": key_id,
                                        "APCA-API-SECRET-KEY": secret,
                                        "Accept": "application/json"},
                               params={"symbols": "SPY", "timeframe": "1Day",
                                       "start": "2026-01-02", "limit": 1, "adjustment": "all"})
            if r.status_code in (401, 403):
                return False, (f"HTTP {r.status_code} — the credential was rejected. Check BOTH "
                               "ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY, and remember that "
                               "docker-compose.yml enumerates env vars, so a value in .env alone "
                               "does not reach the container until `docker compose up -d api worker`.")
            if r.status_code == 429:
                return True, "credential accepted (rate limited right now — 200 requests/minute)"
            r.raise_for_status()
            bars = (r.json().get("bars") or {}).get("SPY") or []
            if not bars:
                return False, "authenticated, but the response carried no SPY bar"
            return True, f"credential accepted; read a SPY bar dated {bars[0].get('t', '?')[:10]}"
        return False, "no live probe is defined for this source yet"
    except httpx.HTTPStatusError as exc:
        return False, (f"HTTP {exc.response.status_code} — "
                       f"{'credentials rejected' if exc.response.status_code in (401, 403) else 'request failed'}")
    except Exception as exc:
        return False, f"{type(exc).__name__} (no credential is included in this message)"


def cmd_preflight(_args) -> None:
    """Verify the environment is production-ready before boot: DB reachable + migrated, SEC UA set,
    a valid AI provider, secure cookies, and no dev-default secrets. Non-zero exit on any hard problem."""
    import re
    from pathlib import Path
    problems, warnings = [], []
    dburl = os.environ.get("DATABASE_URL", "")
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            applied = db.applied_versions(conn)
        files = sorted(int(re.match(r"(\d+)_", p.name).group(1)) for p in Path(db.MIGRATIONS_DIR).glob("*.sql") if re.match(r"\d+_", p.name))
        pending = [v for v in files if v not in applied]
        if pending:
            warnings.append(f"migrations not applied: {pending} — run `python -m tradeos.cli migrate`.")
    except Exception as e:
        problems.append(f"cannot connect to DATABASE_URL ({type(e).__name__}: {e}).")
    if ":tradeos@" in dburl:
        warnings.append("DATABASE_URL uses the dev-default password 'tradeos' — set a strong POSTGRES_PASSWORD in production.")
    # The share card's absolute URL. A hard problem rather than a warning: unset, every `og:image`
    # and `og:url` this instance emits points at localhost, so a caller's shared record renders as
    # a bare text link on every platform — which is the whole distribution model, silently off.
    if not config.public_base_url_configured():
        problems.append("PUBLIC_BASE_URL is not set, so every share card and og:url would point at "
                        "http://localhost:8000. Set it to the origin this instance is reachable at, "
                        "e.g. https://rhumb.example.")
    else:
        try:
            base = config.public_base_url()
            if base.startswith("http://") and "localhost" not in base and "127.0.0.1" not in base:
                warnings.append(f"PUBLIC_BASE_URL is {base} — an http:// origin means link "
                                f"previews are fetched over plaintext and some platforms skip them.")
        except config.ConfigError as e:
            problems.append(str(e))
    if os.environ.get("COOKIE_SECURE", "false").lower() != "true":
        warnings.append("COOKIE_SECURE is not 'true' — set it in production so session cookies require HTTPS (also enables HSTS).")

    # Phase 8. DEV_ORIGINS widens the CSRF origin check and exists only for the Vite dev server;
    # left set in production it is a real hole, so it is a PROBLEM rather than a warning.
    if os.environ.get("DEV_ORIGINS", "").strip():
        problems.append("DEV_ORIGINS is set — it widens the CSRF origin check and is development-only. "
                        "Clear it in production.")
    # Mail. Unconfigured means a forgotten password is unrecoverable, which is a warning; the dev
    # echo being on in production is a capability leak into the logs, which is a problem.
    if not (os.environ.get("SMTP_HOST") and os.environ.get("MAIL_FROM")):
        warnings.append("SMTP_HOST/MAIL_FROM are empty — email verification and password reset "
                        "cannot send, so a forgotten password is unrecoverable.")
    if os.environ.get("MAIL_DEV_ECHO", "").strip().lower() in ("1", "true", "yes"):
        problems.append("MAIL_DEV_ECHO is on — verification and password-reset LINKS are written to "
                        "the server log. Development only; clear it.")

    # Half-configured OAuth is worse than none: the button appears and the callback fails.
    gid, gsecret = os.environ.get("GOOGLE_CLIENT_ID"), os.environ.get("GOOGLE_CLIENT_SECRET")
    if bool(gid) != bool(gsecret):
        problems.append("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must both be set or both empty.")
    if gid and gsecret:
        base = os.environ.get("PUBLIC_BASE_URL", "")
        if not base:
            problems.append("Google sign-in is configured but PUBLIC_BASE_URL is empty — the redirect "
                            "URI would be built against localhost and Google would reject it.")
        elif base.startswith("http://") and "localhost" not in base:
            problems.append(f"PUBLIC_BASE_URL is plain http ({base}) — an OAuth redirect over http "
                            "leaks the authorization code.")
        warnings.append("Google sign-in is configured, but its live handshake has never been "
                        "exercised against Google (see tradeos/oauth.py). Test a real sign-in before "
                        "relying on it.")
    for w in warnings:
        print(f"  ⚠ {w}")
    for p in problems:
        print(f"  ✗ {p}")
    if problems:
        print(f"preflight: {len(problems)} problem(s), {len(warnings)} warning(s) — NOT ready.")
        raise SystemExit(1)
    print(f"preflight: OK ({len(warnings)} warning(s)).")
def cmd_scheduler(args) -> None:
    from . import scheduler
    if args.once:
        with db.connect() as conn:
            results = scheduler.run_once(conn, force=args.force)
        for r in results:
            print(f"  {r['job']}: {r['status']} ({r['duration_ms']}ms) {r['detail']}")
        print(f"scheduler: ran {len(results)} job(s)")
    else:
        scheduler.run_forever(tick_seconds=args.tick)
def cmd_seed_admin(args) -> None:
    import getpass

    import pyotp
    pw = os.environ.get("TRADEOS_ADMIN_PASSWORD") or getpass.getpass("admin password: ")
    if authn.is_weak_password(pw):
        print("refused: password too short or too common")
        return
    secret = authn.new_totp_secret()
    email = args.email.strip().lower()
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, password_hash, tier, totp_secret) VALUES (%s,%s,'admin',%s) "
                "ON CONFLICT (email) DO NOTHING RETURNING id",
                (email, authn.hash_password(pw), secret),
            )
            row = cur.fetchone()
            conn.commit()
        if not row:
            print(f"admin {email} already exists; not modified")
            return
        authn.audit(conn, "system", "seed_admin", email)
    uri = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=config.brand_name())
    print(f"admin created: {email}")
    print("add this TOTP to your authenticator app (required for admin login):")
    print(f"  secret: {secret}")
    print(f"  otpauth: {uri}")


def cmd_seed_house_records(_args) -> None:
    """Import our own signal engine's resolved record as the first two callers on the board.

    Nothing is invented: it reads `claims` and `claim_outcomes` and preserves their real timestamps
    and verdicts. See `receipts/seed.py` for why the record it publishes is unflattering and why we
    publish it anyway.
    """
    from .receipts.seed import seed_house_records
    with db.connect() as conn:
        out = seed_house_records(conn)
    for handle, result in out.items():
        if result.get("skipped"):
            print(f"seed-house-records {handle}: skipped, {result['existing_calls']} calls already "
                  f"sealed (an append only record is never imported twice)")
        else:
            print(f"seed-house-records {handle}: {result['imported']} calls sealed "
                  f"({result['hit']}H/{result['miss']}M/{result['inconclusive']}I/"
                  f"{result['unscoreable']}U), chain head {result['chain_head'][:16]}")


def cmd_resolve_calls(args) -> None:
    """Score every published call whose horizon has closed. The manual form of the scheduler job."""
    from .receipts import scoring
    with db.connect() as conn:
        print(f"resolve-calls: {scoring.resolve_due(conn, limit=args.limit)}")


def cmd_verify_chain(args) -> None:
    """Recompute one caller's whole chain from the stored fields and report."""
    from .receipts import calls as receipts_calls
    from .receipts import chain, record
    with db.connect() as conn:
        caller = record.caller(args.handle, conn)
        if not caller:
            print(f"verify-chain: no caller {args.handle!r}")
            raise SystemExit(2)
        result = chain.verify_chain(receipts_calls.for_chain(caller["id"], conn))
    if result["intact"]:
        print(f"verify-chain {args.handle}: INTACT, {result['links']} links, "
              f"head {result.get('head', '')[:16]}")
    else:
        print(f"verify-chain {args.handle}: BROKEN at seq {result['broken_at_seq']} "
              f"({result['reason']})")
    raise SystemExit(0 if result["intact"] else 1)


def cmd_seed_demo(args) -> None:
    """A ready-to-use account with a handle and nothing published: tier=pro, no TOTP, so it logs in
    with email and password alone. Idempotent.

    IT SEEDS NO CALLS, and that is the point rather than an omission. This used to pre-populate
    journal trades, a portfolio and a watchlist "so the product looks alive on first login" — and
    those surfaces are gone. Inventing calls to fill the gap would put fabricated entries into a
    permanent, sealed, public record whose entire argument is that nothing in it was made up. There
    is no `--i-know` for that one. What a fresh instance shows instead is the truth: an empty
    record, and a publish form.

    (`seed-house-records` is the other half of this and it is not a substitute: it imports 473
    calls the signal engine actually made, from tables only the author's database has.)

    THE PASSWORD IS GENERATED, NOT FIXED. It used to default to a constant that also appeared in
    CLAUDE.md, GO-LIVE.md, two runbooks and this docstring — so every reader of the repository knew
    the credentials of a tier=pro account with no second factor, on every instance that had ever run
    this command. It is now 24 hex characters from the OS CSPRNG, printed once and stored nowhere
    but the password hash. Set TRADEOS_DEMO_PASSWORD to choose your own.

    AND IT REFUSES TO RUN ON AN INSTANCE THAT LOOKS LIKE PRODUCTION. `COOKIE_SECURE=true` means
    session cookies are being issued over TLS, which means real users. A demo account is a
    permanent, fully-privileged, MFA-less login, so seeding one there should be a decision rather
    than a habit: `--i-know` is how you say it was one.
    """
    email = os.environ.get("TRADEOS_DEMO_EMAIL", "demo@example.invalid").strip().lower()
    handle = os.environ.get("TRADEOS_DEMO_HANDLE", "demo-caller").strip().lower()
    if os.environ.get("COOKIE_SECURE", "false").lower() == "true" and not getattr(args, "i_know", False):
        raise SystemExit(
            "refusing: COOKIE_SECURE=true, so this instance is serving real users over TLS.\n"
            "A demo account is a permanent tier=pro login with no second factor. If you genuinely\n"
            "want one here, re-run with --i-know.")
    pw = os.environ.get("TRADEOS_DEMO_PASSWORD") or secrets.token_hex(12)
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, password_hash, tier) VALUES (%s,%s,'pro') "
                "ON CONFLICT (email) DO NOTHING RETURNING id", (email, authn.hash_password(pw)))
            row = cur.fetchone()
            if not row:
                print(f"demo account {email} already exists; not modified")
                return
            uid = row[0]
            cur.execute(
                """INSERT INTO callers (handle, display_name, kind, user_id, jurisdiction_attested)
                   VALUES (%s, 'Demo Caller', 'human', %s, true)
                   ON CONFLICT (handle) DO NOTHING""", (handle, uid))
        conn.commit()
    print(f"demo account ready: {email}")
    print(f"  password: {pw}")
    print("  (printed once; it is stored only as an argon2 hash)")
    print(f"  handle:   @{handle} — an empty record, which is what an honest one looks like on day one")


def cmd_create_invites(args) -> None:
    with db.connect() as conn:
        codes = [authn.create_invite(conn, None) for _ in range(args.n)]
    print(f"{args.n} invite codes:")
    for c in codes:
        print(f"  {c}")


def cmd_status(_args) -> None:
    """What the instance actually holds, in the order an operator asks.

    The price feed FIRST, because it is the only thing that can silently stop the product working:
    a stale benchmark makes every open call unscoreable, and `resolve_due` refuses the whole batch
    rather than half-scoring against it. The three counts after it answer "is anything here".
    """
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT source, last_success_at, last_record_knowable, records_total, "
                    "rejects_total FROM feed_health ORDER BY source")
        rows = cur.fetchall()
        if not rows:
            print("no feeds have run yet")
        for source, ok_at, knowable, total, rejects in rows:
            print(f"{source}: last run {ok_at}, freshest record {knowable}, "
                  f"{total} records, {rejects} rejects")

        cur.execute("SELECT count(DISTINCT symbol), max(day) FROM prices_eod")
        symbols, newest = cur.fetchone()
        cur.execute("SELECT max(day) FROM prices_eod WHERE symbol = 'SPY'")
        spy = cur.fetchone()[0]
        print(f"prices: {symbols or 0} symbols, newest close {newest or 'none'}")
        if spy != newest:
            # Named separately rather than folded into the line above. SPY being behind the rest of
            # the table is not one stale symbol among many: it is the benchmark, so it blocks every
            # publish and defers every resolution at once.
            print(f"  SPY runs to {spy or 'none'} — BEHIND the rest of the table, so nothing "
                  f"can be scored and publishing is blocked until it catches up")

        cur.execute("SELECT count(*), count(*) FILTER (WHERE verdict IS NULL) FROM calls")
        total, still_open = cur.fetchone()
        cur.execute("SELECT count(*) FROM callers")
        print(f"record: {cur.fetchone()[0]} caller(s), {total} sealed call(s), {still_open} open")
def main() -> None:
    """Every command this product has.

    TWELVE, DOWN FROM FORTY-FOUR. What went with the research plane: the whole SEC path
    (ingest/backfill form4, 13D/G, 13F), entity and CUSIP resolution, signal registration and
    computation, the backtest and calibration runs, six other ingesters, the event spine, the claim
    engine, the ledger, the alert generator and four seeds.

    THE CUTS ARE BOUNDED BY set_defaults, ONE PER COMMAND, and that is not a stylistic note. This
    function was broken twice in one session by deletions that began on the right line and ended
    inside the next command's flags, which argparse accepts silently — the parser still builds, the
    command still registers, and a flag belonging to something else has quietly moved. Each block
    below was copied whole from the block it replaces rather than retyped, and
    `tests/test_cli_commands.py` runs `--help` on every one of them, because a registration that
    raises on --help is a command nobody can discover.
    """
    p = argparse.ArgumentParser(prog="tradeos")
    sub = p.add_subparsers(required=True)

    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)

    ipa = sub.add_parser("ingest-prices", aliases=["ingest-prices-alpaca"],
                         help="daily bars from Alpaca; batched, so 500 symbols is 5 requests")
    ipa.add_argument("--symbols-from-clusters", action="store_true", dest="symbols_from_clusters")
    ipa.add_argument("--only-missing", action="store_true", dest="only_missing",
                     help="only fetch cluster symbols with no prices yet")
    ipa.add_argument("--only-missing-history", action="store_true", dest="only_missing_history",
                     help="only fetch cluster symbols lacking history before --history-before")
    ipa.add_argument("--history-before", default="2026-01-02",
                     help="cutoff for --only-missing-history")
    ipa.add_argument("--only-stale", action="store_true", dest="only_stale",
                     help="only fetch symbols ALREADY stored whose series stops before "
                          "--stale-before (the top-up pass; SPY first, because a stale benchmark "
                          "unscoreables everything)")
    ipa.add_argument("--stale-before", default="",
                     help="cutoff for --only-stale; defaults to the freshest day any symbol has")
    ipa.add_argument("--limit", type=int, default=0, help="cap symbols fetched this pass (0 = no cap)")
    ipa.add_argument("--symbols", default="", help="comma-separated symbols if not --symbols-from-clusters")
    ipa.add_argument("--start", default="2026-01-01")
    ipa.add_argument("--universe", action="store_true",
                     help="every tradable non-OTC US equity and ETF Alpaca lists "
                          "(no research table involved)")
    ipa.add_argument("--only-new", action="store_true",
                     help="with --universe, fetch only symbols not already in prices_eod")
    ipa.set_defaults(fn=cmd_ingest_prices_alpaca)

    cs = sub.add_parser("check-source", help="make a real call to one source and report the result")
    cs.add_argument("source")
    cs.set_defaults(fn=cmd_check_source)

    sch = sub.add_parser("scheduler")
    sch.add_argument("--once", action="store_true", help="run one pass of due jobs and exit")
    sch.add_argument("--force", action="store_true", help="with --once, run every job regardless of interval")
    sch.add_argument("--tick", type=int, default=60, help="seconds between scheduler passes (run-forever)")
    sch.set_defaults(fn=cmd_scheduler)

    sa = sub.add_parser("seed-admin")
    sa.add_argument("--email", required=True)
    sa.set_defaults(fn=cmd_seed_admin)
    p_demo = sub.add_parser("seed-demo")
    p_demo.add_argument("--i-know", action="store_true",
                        help="seed a demo account even when COOKIE_SECURE=true (real users)")
    p_demo.set_defaults(fn=cmd_seed_demo)
    sub.add_parser("seed-house-records").set_defaults(fn=cmd_seed_house_records)
    rc = sub.add_parser("resolve-calls", help="score published calls whose horizon has closed")
    rc.add_argument("--limit", type=int, default=100)
    rc.set_defaults(fn=cmd_resolve_calls)
    vc = sub.add_parser("verify-chain", help="recompute one caller's chain and report")
    vc.add_argument("handle")
    vc.set_defaults(fn=cmd_verify_chain)
    ci = sub.add_parser("create-invites")
    ci.add_argument("--n", type=int, default=5)
    ci.set_defaults(fn=cmd_create_invites)

    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("preflight").set_defaults(fn=cmd_preflight)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
