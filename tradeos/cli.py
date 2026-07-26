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
from datetime import UTC, date, datetime, time, timedelta

from psycopg import sql

from . import alerts, authn, config, db
from .backtest import run as backtest
from .config import sec_user_agent
from .ingestion import form13f, schedule13
from .ingestion.edgar_client import EdgarClient
from .ingestion.finra import FinraClient, ingest_short_interest
from .ingestion.prices import TiingoClient, ingest_prices
from .ingestion.runner import ingest_day as ingest_form4_day
from .library import sync_library
from .resolution.entities import backfill_insider_entities
from .resolution.openfigi import OpenFigiClient, resolve_cusips
from .resolution.tickers import sync_tickers
from .signals import definitions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

# each ingest command maps to a (module) exposing ingest_day + a human label
INGESTERS = {
    "ingest-form4": (ingest_form4_day, "Form 4"),
    "ingest-13dg": (schedule13.ingest_day, "Schedule 13D/G"),
    "ingest-13f": (form13f.ingest_day, "Form 13F"),
}
BACKFILLERS = {
    "backfill-form4": ingest_form4_day,
    "backfill-13dg": schedule13.ingest_day,
    "backfill-13f": form13f.ingest_day,
}


def cmd_migrate(_args) -> None:
    with db.connect() as conn:
        ran = db.run_migrations(conn)
        print(f"applied migrations: {ran or 'none (up to date)'}")


def cmd_sync_tickers(_args) -> None:
    client = EdgarClient(sec_user_agent())
    try:
        with db.connect() as conn:
            counters = sync_tickers(conn, client)
        print(f"sync-tickers: {counters}")
    finally:
        client.close()


def cmd_ingest(args) -> None:
    ingest_fn, label = INGESTERS[args._command]
    day = date.fromisoformat(args.date)
    client = EdgarClient(sec_user_agent())
    try:
        with db.connect() as conn:
            counters = ingest_fn(conn, client, day, limit=args.limit)
        print(f"{label} {day}: {counters}")
    finally:
        client.close()


def cmd_backfill(args) -> None:
    ingest_fn = BACKFILLERS[args._command]
    start, end = date.fromisoformat(args.from_date), date.fromisoformat(args.to_date)
    client = EdgarClient(sec_user_agent())
    try:
        with db.connect() as conn:
            day = start
            while day <= end:
                if day.weekday() < 5:  # EDGAR indexes exist for business days
                    try:
                        counters = ingest_fn(conn, client, day)
                        print(f"{day}: {counters}")
                    except Exception as exc:  # a market holiday 404s; log and move on
                        print(f"{day}: skipped ({type(exc).__name__}: {exc})")
                day += timedelta(days=1)
    finally:
        client.close()


def cmd_resolve_entities(_args) -> None:
    with db.connect() as conn:
        updated = backfill_insider_entities(conn)
        print(f"resolve-entities: linked {updated} insider transactions to issuer entities")


def cmd_resolve_cusips(args) -> None:
    figi = OpenFigiClient(api_key=os.environ.get("OPENFIGI_API_KEY"))
    try:
        with db.connect() as conn:
            counters = resolve_cusips(conn, figi, limit=args.limit)
        print(f"resolve-cusips: {counters}")
    finally:
        figi.close()


def cmd_signals_register(args) -> None:
    with db.connect() as conn:
        version, created = definitions.register(conn, args.changelog)
        if created:
            print(f"registered convergence v{version}")
        else:
            print(f"convergence v{version} already current (module hash unchanged); nothing to register")


def _parse_as_of(s: str | None) -> datetime:
    if not s:
        return datetime.now(UTC)
    if len(s) == 10:  # a bare date means end of that day (everything knowable by then)
        return datetime.combine(date.fromisoformat(s), time(23, 59, 59), tzinfo=UTC)
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def cmd_compute_signals(args) -> None:
    with db.connect() as conn:
        if args.daily:
            results = definitions.compute_daily(conn, date.fromisoformat(args.from_date), date.fromisoformat(args.to_date))
            for r in results:
                print(f"{r['as_of']}: {r['published']} clusters ({r['high']}H/{r['medium']}M/{r['low']}L) from {r['candidates']} candidates")
            print(f"daily compute complete: {len(results)} as_of points")
        else:
            counters = definitions.compute_and_store(conn, _parse_as_of(args.as_of))
            print(f"compute-signals: {counters}")


def cmd_ingest_prices(args) -> None:
    start = date.fromisoformat(args.start)
    client = TiingoClient(os.environ.get("TIINGO_API_KEY", ""))
    try:
        with db.connect() as conn:
            if args.only_missing_history:
                symbols = backtest.symbols_for_clusters_missing_history(conn, date.fromisoformat(args.history_before))
            elif args.only_missing:
                symbols = backtest.symbols_for_clusters_missing(conn)  # quota-efficient free-tier top-up
            elif args.symbols_from_clusters:
                symbols = backtest.symbols_for_clusters(conn)
            else:
                symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
            if args.limit:
                symbols = symbols[: args.limit]  # bound a pass so free-tier 429s don't stall it
            counters = ingest_prices(conn, client, symbols, start)
        print(f"ingest-prices: {counters}")
    finally:
        client.close()


def cmd_ingest_short_interest(args) -> None:
    client = FinraClient()
    try:
        with db.connect() as conn:
            counters = ingest_short_interest(conn, client, date.fromisoformat(args.start))
        print(f"ingest-short-interest: {counters}")
    finally:
        client.close()


def cmd_ingest_sentiment(args) -> None:
    from . import sentiment, social
    from .ingestion import attention_wiki, social_reddit
    from .ingestion.sentiment_hn import ingest_hn
    totals = {}
    with db.connect() as conn:
        universe = sentiment.tracked_symbols(conn, limit=args.limit)
        if args.source in ("hn", "all"):
            totals["hn"] = ingest_hn(conn, universe, window_hours=args.window)
        if args.source in ("wikipedia", "wiki", "all"):
            totals["wikipedia"] = attention_wiki.ingest(conn, social.attention_universe(conn, universe))
        if args.source in ("reddit", "all"):
            totals["reddit"] = social_reddit.ingest(conn)   # honest no-op until REDDIT_CLIENT_ID/SECRET set
    print(f"ingest-sentiment: {totals}")


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

    Exceptions are caught and described rather than raised: an operator running this has just
    pasted a credential and needs to be told what is wrong, not shown a traceback. The message
    never echoes the credential — httpx puts the full URL in its exception text, so only the
    exception TYPE and status code are surfaced.
    """
    import httpx
    try:
        if key == "reddit":
            from .ingestion import social_reddit
            with httpx.Client(timeout=20.0) as client:
                token = social_reddit._token(client)
                posts = social_reddit._posts(client, token, "stocks", limit=1)
            return True, f"authenticated and read {len(posts)} post(s) from r/stocks"
        if key == "bluesky":
            from .ingestion import social_bluesky
            with httpx.Client(timeout=20.0, headers=social_bluesky.UA) as client:
                did = social_bluesky.resolve_did(client, "reuters.com")
            return (bool(did), f"resolved reuters.com to {did}" if did
                    else "could not resolve a known handle")
        if key == "tiingo":
            with httpx.Client(timeout=20.0) as client:
                r = client.get("https://api.tiingo.com/api/test",
                               headers={"Authorization": f"Token {os.environ['TIINGO_API_KEY']}"})
            r.raise_for_status()
            return True, "token accepted by Tiingo's test endpoint"
        if key == "coingecko":
            with httpx.Client(timeout=20.0) as client:
                r = client.get("https://api.coingecko.com/api/v3/ping")
            return r.status_code == 200, f"ping returned {r.status_code}"
        if key == "sec_edgar":
            from . import config
            return bool(config.sec_user_agent()), "SEC_USER_AGENT is set"
        return False, "no live probe is defined for this source yet"
    except httpx.HTTPStatusError as exc:
        return False, (f"HTTP {exc.response.status_code} — "
                       f"{'credentials rejected' if exc.response.status_code in (401, 403) else 'request failed'}")
    except Exception as exc:
        return False, f"{type(exc).__name__} (no credential is included in this message)"


def cmd_ingest_bluesky(args) -> None:
    """Posts from the consequential accounts on Bluesky. Keyless, so this works out of the box;
    edit the list with `seed-watchlist` or the accounts API."""
    from .ingestion import social_bluesky
    with db.connect() as conn:
        print(f"ingest-bluesky: {social_bluesky.ingest(conn, limit=args.limit)}")


def cmd_ingest_news(args) -> None:
    from .ingestion import news_rss, news_sec
    out: dict = {}
    if args.source in ("sec", "all"):
        client = EdgarClient(sec_user_agent())
        try:
            with db.connect() as conn:
                day = date.fromisoformat(args.date) if args.date else date.today()
                out["sec"] = news_sec.ingest_day(conn, client, day, limit=args.limit)
        finally:
            client.close()
    if args.source in ("rss", "all"):
        rc = news_rss.RssClient()
        try:
            with db.connect() as conn:
                out["rss"] = news_rss.ingest(conn, rc, limit_per_feed=args.limit or 40)
        finally:
            rc.close()
    print(f"ingest-news: {out}")


def cmd_analyze_news(args) -> None:
    from .intelligence import analyst
    provider = os.environ.get("EXPLAIN_PROVIDER", "template")
    with db.connect() as conn:
        print(f"analyze-news: {analyst.analyze_recent(conn, hours=args.hours, limit=args.limit, provider=provider)}")


def cmd_ingest_calendar(args) -> None:
    from .ingestion import calendar_nasdaq
    with db.connect() as conn:
        out = {}
        if args.source in ("earnings", "all"):
            out["earnings"] = calendar_nasdaq.ingest_earnings(conn, days_ahead=args.days)
        if args.source in ("economic", "all"):
            out["economic"] = calendar_nasdaq.ingest_economic(conn, days_ahead=args.days)
    print(f"ingest-calendar: {out}")


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
    if "@" not in os.environ.get("SEC_USER_AGENT", ""):
        problems.append("SEC_USER_AGENT must be like 'YourName you@example.com' (SEC fair-access policy).")
    # Validate the whole provider chain, not just its first entry. This check used to reject
    # 'openai' (which ships) and offer 'anthropic' (which does not) — a confidently wrong check is
    # worse than no check, because it tells an operator a working config is broken.
    from . import llm
    keyed = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}
    chain = llm.chain()
    unknown = [p for p in chain if p not in keyed and p != "template"]
    if unknown:
        problems.append(f"EXPLAIN_PROVIDER names unknown provider(s) {unknown} "
                        f"(valid: template, {', '.join(keyed)}; a comma list is a fallback chain).")
    usable = [p for p in chain if p in keyed and os.environ.get(keyed[p])]
    for p in chain:
        if p in keyed and not os.environ.get(keyed[p]):
            warnings.append(f"EXPLAIN_PROVIDER includes '{p}' but {keyed[p]} is empty — that link in "
                            "the chain is skipped.")
    if not usable and "template" not in chain:
        warnings.append("no provider in EXPLAIN_PROVIDER has a key — all AI prose falls back to "
                        "deterministic templates.")
    elif len(usable) == 1:
        warnings.append(f"only one usable AI provider ({usable[0]}). Add a second to "
                        "EXPLAIN_PROVIDER (comma-separated) so one outage does not silence every "
                        "AI surface.")
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


def cmd_spine(args) -> None:
    """Feed the event spine. `--backfill-news` is the one-time bootstrap that projects the whole
    news_items table in; the scheduler keeps it current with a small window after that."""
    from .ingestion import gdelt, news_adapter
    with db.connect() as conn:
        out = {}
        if args.source in ("news", "all"):
            out["news"] = news_adapter.backfill(conn, since_hours=None if args.backfill_news else 6)
        if args.source in ("gdelt", "all"):
            out["gdelt"] = gdelt.ingest(conn, timespan=args.timespan)
    print(f"spine: {out}")


def cmd_reprocess(args) -> None:
    """Re-derive clustering and scores over stored raw payloads.

    This is how a track record gets bootstrapped instead of waiting months for one: when the
    engine improves, history is re-read rather than re-fetched. Expensive, so it is admin-only
    and never runs on a schedule."""
    from . import spine
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM events WHERE knowable_time >= now() - make_interval(days => %s) "
                    "ORDER BY knowable_time", (args.days,))
        ids = [r[0] for r in cur.fetchall()]
        if args.reset:
            cur.execute("UPDATE events SET cluster_id = NULL WHERE id = ANY(%s)", (ids,))
            cur.execute("DELETE FROM event_clusters WHERE NOT EXISTS "
                        "(SELECT 1 FROM events e WHERE e.cluster_id = event_clusters.id)")
            conn.commit()
        clusters = set()
        for i, eid in enumerate(ids, 1):
            if args.reclassify:
                # Re-read the stored title/body through the current cue table. This is the point
                # of keeping raw payloads: an improved classifier is applied to history, not only
                # to what arrives next.
                cur.execute("SELECT title, body FROM events WHERE id = %s", (eid,))
                title, body = cur.fetchone()
                cur.execute("UPDATE events SET category = %s WHERE id = %s",
                            (spine.classify(title, body), eid))
            clusters.add(spine.assign_cluster(conn, eid))
            if i % 200 == 0:
                conn.commit()
                print(f"  {i}/{len(ids)}")
        conn.commit()
        for cid in clusters:
            spine.score_cluster(conn, cid)
        conn.commit()
    print(f"reprocess: {len(ids)} events -> {len(clusters)} clusters")


def cmd_seed_watchlist(_args) -> None:
    from . import watchlist_accounts
    with db.connect() as conn:
        print(f"seed-watchlist: {watchlist_accounts.seed(conn)}")


def cmd_seed_exposure(_args) -> None:
    from . import relevance
    with db.connect() as conn:
        print(f"seed-exposure: {relevance.seed(conn)}")


def cmd_interpret(args) -> None:
    from . import claims
    with db.connect() as conn:
        out = claims.interpret_recent(conn, hours=args.hours, limit=args.limit,
                                      min_novelty=args.min_novelty)
    print(f"interpret: {out['claims']} claims from {out['considered']} clusters")
    for s in out["skipped"]:
        print(f"  skipped event {s['event']}: {s['reason']}")


def cmd_measure_claims(_args) -> None:
    from . import ledger
    with db.connect() as conn:
        print(f"measure-claims: {ledger.measure_due(conn)}")


def cmd_import_signals(args) -> None:
    """Express historical convergence signals as scoreable claims and import their measured
    outcomes. Idempotent — re-running never inflates the record."""
    from . import smartmoney_claims
    with db.connect() as conn:
        out = smartmoney_claims.build(conn, horizon_days=args.horizon, since=args.since)
    print(f"import-signals: {out['claims_made']} claims, {out['outcomes_imported']} outcomes "
          f"({out['model_version']}), {out['skipped']} skipped")


def cmd_capture_context(args) -> None:
    """Reconstruct world context for trades logged before capture existed (Phase 6).

    A one-shot repair, not a scheduled job. New trades snapshot themselves at creation; this only
    fills the gap behind them, and it marks every row it writes `reconstructed` rather than passing
    it off as a live capture."""
    from . import journal_context
    with db.connect() as conn:
        out = journal_context.backfill(conn, limit=args.limit)
    print(f"capture-context: {out['trades']} trade(s) marked {out['basis']} — "
          f"{out['with_live_claims']} had live interpretations, {out['empty']} had none")


def cmd_ledger(_args) -> None:
    from . import ledger
    with db.connect() as conn:
        s = ledger.summary(conn)
        misses = ledger.recent_misses(conn, limit=5)
    o = s["overall"]
    rate = f"{o['hit_rate']:.1%}" if o["hit_rate"] is not None else "—"
    suff = "" if o["sufficient"] else "  (INSUFFICIENT SAMPLE — not a rate to publish)"
    print(f"hit rate: {rate}  ({o['hit']} hit / {o['miss']} miss, n={o['n']}){suff}")
    print(f"inconclusive {o['inconclusive']} · unscoreable {o['unscoreable']} · open {s['open_claims']}")
    for label, rows in s["by"].items():
        if rows:
            print(f"\nby {label}:")
            for r in rows:
                rr = f"{r['hit_rate']:.0%}" if r["hit_rate"] is not None else "—"
                flag = "" if r["sufficient"] else " (thin)"
                print(f"  {str(r['key'])[:26]:28} {rr:>5}  n={r['n']}{flag}")
    if misses:
        print("\nrecent misses (shown first, on purpose):")
        for m in misses:
            print(f"  {m['subject']:8} said {m['predicted']:5} got {m['excess_return']:+.1%}  {str(m['headline'])[:52]}")


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


def cmd_run_backtest(_args) -> None:
    with db.connect() as conn:
        counters = backtest.run_backtest(conn)
        print(f"run-backtest: {counters}")


def cmd_calibration(_args) -> None:
    with db.connect() as conn:
        cal = backtest.compute_calibration(conn)
    print(f"episodes: {cal['episodes_total']} total, {cal['episodes_priced']} priced, "
          f"{cal['episodes_excluded_missing_prices']} no-price-history, "
          f"{cal['episodes_too_recent_to_enter']} too-recent, {cal['episodes_excluded_no_symbol']} no-ticker; "
          f"raw clusters {cal['raw_cluster_count']}; horizons open {cal['horizons_open']}")
    for bucket, horizons in cal["per_bucket"].items():
        for h, c in horizons.items():
            if c["episodes"]:
                rate = f"{c['hit_rate']:.0%}" if c["sufficient"] else "insufficient sample"
                print(f"  {bucket:6s} {h:>3s}d: {rate} (n={c['episodes']})")


def cmd_sync_library(_args) -> None:
    with db.connect() as conn:
        print(f"sync-library: {sync_library(conn)}")


def cmd_generate_alerts(_args) -> None:
    with db.connect() as conn:
        print(f"generate-alerts: {alerts.generate_alerts(conn)}")


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


def cmd_seed_demo(_args) -> None:
    """A ready-to-use demo account: tier=pro (full features, no charge), NO TOTP (so it logs in with
    just email + password), pre-populated with a handle, journal trades, a portfolio, and a watchlist
    so the product looks alive on first login. Idempotent. Override creds via TRADEOS_DEMO_EMAIL /
    TRADEOS_DEMO_PASSWORD."""
    email = os.environ.get("TRADEOS_DEMO_EMAIL", "demo@tradeos.app").strip().lower()
    pw = os.environ.get("TRADEOS_DEMO_PASSWORD", "<generated at seed time>")
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, password_hash, tier, handle, bio) VALUES (%s,%s,'pro',%s,%s) "
                "ON CONFLICT (email) DO NOTHING RETURNING id",
                (email, authn.hash_password(pw), "demo_trader",
                 "Demo account — exploring smart-money convergence, journaling trades, and the AI tools."),
            )
            row = cur.fetchone()
            if not row:
                print(f"demo account {email} already exists; not modified")
                return
            uid = row[0]
            eid = sql.SQL("(SELECT entity_id FROM security_map WHERE symbol=%s "
                          "AND source='sec_company_tickers' ORDER BY confidence DESC LIMIT 1)")
            trades = [
                ("NVDA", "long", "closed", 120, 138, 110, 145, 80, "breakout", True, "2026-06-02", "2026-06-20"),
                ("MSFT", "long", "open", 410, None, 395, 465, 40, "pullback", True, "2026-06-25", None),
                ("AAPL", "long", "closed", 195, 186, 188, 215, 60, "earnings", False, "2026-05-15", "2026-05-30"),
                ("AMD", "long", "planned", 150, None, 138, 190, 50, "breakout", False, None, None),
                ("TSLA", "short", "closed", 250, 232, 265, 220, 30, "reversal", True, "2026-06-10", "2026-06-24"),
            ]
            for (sym, d, st, e, ex, stp, tg, sz, strat, pub, op, cl) in trades:
                cur.execute(
                    sql.SQL("""INSERT INTO trades (user_id, symbol, entity_id, asset_class, direction,
                                 status, entry_price, exit_price, stop_price, target_price, size,
                                 size_unit, strategy, is_public, opened_on, closed_on)
                               VALUES (%s,%s,{eid},'equity',%s,%s,%s,%s,%s,%s,%s,'shares',%s,%s,%s,%s)"""
                            ).format(eid=eid),
                    (uid, sym, sym, d, st, e, ex, stp, tg, sz, strat, pub, op, cl),
                )
            cur.execute("INSERT INTO portfolios (user_id, name, kind) VALUES (%s,'My shadows','manual') RETURNING id", (uid,))
            pid = cur.fetchone()[0]
            for sym, op in (("NVDA", "2026-06-02"), ("MSFT", "2026-06-25")):
                cur.execute(sql.SQL("INSERT INTO portfolio_positions (portfolio_id, symbol, "
                                    "entity_id, opened_on) VALUES (%s,%s,{eid},%s)").format(eid=eid),
                            (pid, sym, sym, op))
            for sym in ("NVDA", "MSFT", "AMD", "TSLA"):
                cur.execute("INSERT INTO watchlists (user_key, symbol) VALUES ('demo',%s) ON CONFLICT DO NOTHING", (sym,))
            # follow a few names so the Morning Brief's "Your names" section is alive on first login
            for sym in ("NVDA", "MSFT", "TSLA", "AMD"):
                cur.execute("INSERT INTO follows (user_id, kind, ref, label) VALUES (%s,'symbol',%s,%s) "
                            "ON CONFLICT DO NOTHING", (uid, sym, sym))
        conn.commit()
        authn.audit(conn, "system", "seed_demo", email)
    print(f"demo account created: {email}  (tier=pro, no MFA)")
    print(f"  password: {pw}")
    print("  Log in with that email + password — full Pro features, no charge.")


def cmd_create_invites(args) -> None:
    with db.connect() as conn:
        codes = [authn.create_invite(conn, None) for _ in range(args.n)]
    print(f"{args.n} invite codes:")
    for c in codes:
        print(f"  {c}")


def cmd_status(_args) -> None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT source, last_success_at, last_record_knowable, records_total, rejects_total FROM feed_health ORDER BY source")
        rows = cur.fetchall()
        if not rows:
            print("no feeds have run yet")
        for source, ok_at, knowable, total, rejects in rows:
            print(f"{source}: last run {ok_at}, freshest record {knowable}, {total} records, {rejects} rejects")
        cur.execute("SELECT count(*) FROM fund_holdings WHERE issuer_entity IS NULL")
        unresolved = cur.fetchone()[0]
        if unresolved:
            print(f"unresolved 13F holdings (CUSIP not yet mapped): {unresolved}")


def _add_ingest(sub, name: str) -> None:
    p = sub.add_parser(name)
    p.add_argument("--date", required=True)
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(fn=cmd_ingest, _command=name)


def _add_backfill(sub, name: str) -> None:
    p = sub.add_parser(name)
    p.add_argument("--from", dest="from_date", required=True)
    p.add_argument("--to", dest="to_date", required=True)
    p.set_defaults(fn=cmd_backfill, _command=name)


def main() -> None:
    p = argparse.ArgumentParser(prog="tradeos")
    sub = p.add_subparsers(required=True)

    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    sub.add_parser("sync-tickers").set_defaults(fn=cmd_sync_tickers)
    for name in INGESTERS:
        _add_ingest(sub, name)
    for name in BACKFILLERS:
        _add_backfill(sub, name)
    sub.add_parser("resolve-entities").set_defaults(fn=cmd_resolve_entities)
    rc = sub.add_parser("resolve-cusips")
    rc.add_argument("--limit", type=int, default=200)
    rc.set_defaults(fn=cmd_resolve_cusips)

    sr = sub.add_parser("signals-register")
    sr.add_argument("--changelog", required=True)
    sr.set_defaults(fn=cmd_signals_register)

    cs = sub.add_parser("compute-signals")
    cs.add_argument("--as-of", dest="as_of", default=None, help="ISO timestamp or date; default now")
    cs.add_argument("--daily", action="store_true", help="compute a set per business day in [--from,--to]")
    cs.add_argument("--from", dest="from_date", default=None)
    cs.add_argument("--to", dest="to_date", default=None)
    cs.set_defaults(fn=cmd_compute_signals)

    ip = sub.add_parser("ingest-prices")
    ip.add_argument("--symbols-from-clusters", action="store_true", dest="symbols_from_clusters")
    ip.add_argument("--only-missing", action="store_true", dest="only_missing",
                    help="only fetch cluster symbols with no prices yet (spend free-tier quota wisely)")
    ip.add_argument("--only-missing-history", action="store_true", dest="only_missing_history",
                    help="only fetch cluster symbols lacking price history before --history-before "
                         "(patient deep-history backfill; pair with --start 2024-04-01)")
    ip.add_argument("--history-before", default="2026-01-02",
                    help="cutoff date for --only-missing-history: symbols with no price row before this")
    ip.add_argument("--limit", type=int, default=0, help="cap symbols fetched this pass (0 = no cap)")
    ip.add_argument("--symbols", default="", help="comma-separated symbols if not --symbols-from-clusters")
    ip.add_argument("--start", default="2026-01-01")
    ip.set_defaults(fn=cmd_ingest_prices)

    si = sub.add_parser("ingest-short-interest")
    si.add_argument("--start", default="2026-05-01")
    si.set_defaults(fn=cmd_ingest_short_interest)

    isent = sub.add_parser("ingest-sentiment")
    isent.add_argument("--source", default="all", choices=["hn", "wikipedia", "wiki", "reddit", "all"])
    isent.add_argument("--limit", type=int, default=60)
    isent.add_argument("--window", type=int, default=48)
    isent.set_defaults(fn=cmd_ingest_sentiment)

    cs = sub.add_parser("check-source", help="make a real call to one source and report the result")
    cs.add_argument("source")
    cs.set_defaults(fn=cmd_check_source)

    ibs = sub.add_parser("ingest-bluesky")
    ibs.add_argument("--limit", type=int, default=25, help="posts per account")
    ibs.set_defaults(fn=cmd_ingest_bluesky)

    inn = sub.add_parser("ingest-news")
    inn.add_argument("--source", default="all", choices=["sec", "rss", "all"])
    inn.add_argument("--date", default=None, help="SEC 8-K day (default today); RSS ignores it")
    inn.add_argument("--limit", type=int, default=None, help="cap SEC filings / RSS items per feed")
    inn.set_defaults(fn=cmd_ingest_news)

    ann = sub.add_parser("analyze-news")
    ann.add_argument("--hours", type=int, default=72)
    ann.add_argument("--limit", type=int, default=12, help="max items to (LLM) analyze this pass")
    ann.set_defaults(fn=cmd_analyze_news)

    ical = sub.add_parser("ingest-calendar")
    ical.add_argument("--source", default="all", choices=["earnings", "economic", "all"])
    ical.add_argument("--days", type=int, default=14, help="days ahead to fetch")
    ical.set_defaults(fn=cmd_ingest_calendar)

    sp = sub.add_parser("spine", help="feed the event spine (Phase 2)")
    sp.add_argument("--source", choices=["news", "gdelt", "all"], default="all")
    sp.add_argument("--backfill-news", action="store_true",
                    help="project the WHOLE news_items table, not just the recent window")
    sp.add_argument("--timespan", default="2h", help="GDELT lookback, e.g. 2h / 24h")
    sp.set_defaults(fn=cmd_spine)

    rp = sub.add_parser("reprocess", help="re-derive clusters and scores over stored payloads (admin)")
    rp.add_argument("--days", type=int, default=7)
    rp.add_argument("--reset", action="store_true", help="drop existing cluster assignments first")
    rp.add_argument("--reclassify", action="store_true", help="also re-run the category cue table")
    rp.set_defaults(fn=cmd_reprocess)

    sw = sub.add_parser("seed-watchlist", help="seed the consequential-accounts watchlist")
    sw.set_defaults(fn=cmd_seed_watchlist)

    se = sub.add_parser("seed-exposure", help="load the country exposure reference data")
    se.set_defaults(fn=cmd_seed_exposure)

    ic = sub.add_parser("interpret", help="generate claims from recent event clusters (Phase 3)")
    ic.add_argument("--hours", type=int, default=24)
    ic.add_argument("--limit", type=int, default=5)
    ic.add_argument("--min-novelty", type=float, default=0.4)
    ic.set_defaults(fn=cmd_interpret)

    mc = sub.add_parser("measure-claims", help="score claims whose horizon has elapsed")
    mc.set_defaults(fn=cmd_measure_claims)

    isig = sub.add_parser("import-signals",
                          help="express convergence signals as claims and import their outcomes")
    isig.add_argument("--horizon", type=int, default=30, choices=[30, 90])
    isig.add_argument("--since", default=None, help="only clusters on/after this date")
    isig.set_defaults(fn=cmd_import_signals)

    cc = sub.add_parser("capture-context",
                        help="reconstruct world context for trades logged before capture existed")
    cc.add_argument("--limit", type=int, default=500)
    cc.set_defaults(fn=cmd_capture_context)

    lg = sub.add_parser("ledger", help="print the accuracy record, including its misses")
    lg.set_defaults(fn=cmd_ledger)

    sch = sub.add_parser("scheduler")
    sch.add_argument("--once", action="store_true", help="run one pass of due jobs and exit")
    sch.add_argument("--force", action="store_true", help="with --once, run every job regardless of interval")
    sch.add_argument("--tick", type=int, default=60, help="seconds between scheduler passes (run-forever)")
    sch.set_defaults(fn=cmd_scheduler)

    sub.add_parser("run-backtest").set_defaults(fn=cmd_run_backtest)
    sub.add_parser("calibration").set_defaults(fn=cmd_calibration)
    sub.add_parser("sync-library").set_defaults(fn=cmd_sync_library)
    sub.add_parser("generate-alerts").set_defaults(fn=cmd_generate_alerts)

    sa = sub.add_parser("seed-admin")
    sa.add_argument("--email", required=True)
    sa.set_defaults(fn=cmd_seed_admin)
    sub.add_parser("seed-demo").set_defaults(fn=cmd_seed_demo)
    ci = sub.add_parser("create-invites")
    ci.add_argument("--n", type=int, default=5)
    ci.set_defaults(fn=cmd_create_invites)

    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("preflight").set_defaults(fn=cmd_preflight)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
