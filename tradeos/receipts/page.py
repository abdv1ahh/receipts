"""The public record page: what a stranger sees after tapping a shared link.

This is the only page in the product written for someone with no account, no context and about two
seconds of patience, and it is the one every share lands on. It used to be a card image and an
"open the full record" link, so a visitor had to click twice before seeing anything they could
judge — and the second click dropped them inside the research terminal, past a sidebar of eleven
surfaces that 401 for them, a search field, an upgrade button and a notification bell.

SERVER RENDERED, DELIBERATELY, and not the app bundle with its chrome hidden. Three reasons, in
order of how much they matter:

  * SPEED. The app bundle is 434KB of JavaScript and 137KB of CSS for eleven surfaces this visitor
    will never open, and nothing renders until it has parsed and fetched. This page is one document
    with its stylesheet inline: the record is on screen before a bundle would have finished
    downloading.
  * NO CHROME BY CONSTRUCTION. There is no shell here to strip, so no future change to the app's
    navigation can leak a research rail onto a shared record. A gate you have to remember to apply
    is a gate that eventually is not applied.
  * IT SURVIVES THE APP. A record is permanent and public; the surfaces around it are not.

WHAT KEEPS IT FROM DRIFTING from the in-app record surface, which is the real cost of rendering the
same thing twice: it renders the payload `/api/receipts/{handle}` returns, unchanged, assembled by
the same function. Both surfaces therefore read one summary, and the sample gate — the rule that no
percentage exists below 25 resolved calls — is applied once, in `record.summary`, and cannot be
worked around by either. The formatting is the only thing duplicated, and the tests assert the gate
at the boundary rather than trusting that.

The verify panel is the centrepiece and its script lives in `verify.js`, served as a file because
the app sends `script-src 'self'` — an inline script is refused by the browser silently.
"""
from __future__ import annotations

from datetime import UTC, datetime

from .card import _xml_escape as e

# The stylesheet, inline. One document, one round trip, and no dependency on a build artifact that
# may or may not have been rebuilt. Colours are the app's own tokens, copied rather than imported
# for the same reason the markup is: this page must not break when the bundle changes.
#
# The accent is spent in exactly one place — the verify panel — which is the rule the in-app
# Receipts surfaces already follow, because it is the one moment something is proved rather than
# asserted.
STYLE = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --bg:#05060c; --panel:#0e111b; --card:#12151f; --border:#1b2130; --border-2:#2a3247;
  --text:#eaecf4; --muted:#8b93ab; --faint:#7b83a0; --accent:#6e8cff;
  --green:#2fe3a0; --red:#ff6b81; --amber:#ffc25c;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 -apple-system,BlinkMacSystemFont,
  "Segoe UI",Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}
.num,.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
a{color:var(--accent)}
.wrap{max-width:760px;margin:0 auto;padding:0 20px 72px}

/* the only chrome: a wordmark, which is not a link, because the one outbound action on this
   page is claiming a handle and a second door dilutes it */
.pr-top{display:flex;align-items:center;gap:9px;padding:20px 0 26px;color:var(--muted);
  font-size:13px;letter-spacing:.02em}
.pr-mark{color:var(--accent)}
.pr-top b{color:var(--text);font-weight:600}

.pr-name{font-size:31px;line-height:1.15;margin:0;letter-spacing:-.02em}
.pr-handle{font-family:var(--mono);color:var(--muted);font-size:14px;margin-top:5px}
.pr-badges{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.pr-badge{font-size:11.5px;padding:3px 9px;border-radius:999px;border:1px solid var(--border-2);
  color:var(--muted)}
.pr-badge.ok{color:var(--green);border-color:rgba(47,227,160,.34)}
.pr-badge.ours{color:var(--amber);border-color:rgba(255,194,92,.34)}
.pr-bio{color:var(--muted);margin:14px 0 0;overflow-wrap:anywhere}
.pr-note{margin:14px 0 0;padding:11px 13px;border-left:2px solid var(--border-2);
  background:rgba(255,255,255,.015);color:var(--faint);font-size:12.5px;line-height:1.65}

h2{font-size:12px;text-transform:uppercase;letter-spacing:.13em;color:var(--faint);
  font-weight:600;margin:0 0 4px}
section{margin-top:38px}
.lede{color:var(--muted);font-size:13px;margin:0 0 14px;line-height:1.6}

/* ---- the check: the one place the accent is spent ---- */
.pr-verify{margin-top:30px;border:1px solid rgba(110,140,255,.34);border-radius:16px;
  background:linear-gradient(160deg,rgba(110,140,255,.10),rgba(110,140,255,.02));padding:20px}
.pr-verify h2{color:var(--accent)}
.pr-chainhead{font-family:var(--mono);font-size:11.5px;color:var(--faint);margin-top:8px;
  overflow-wrap:anywhere}
.pr-verify p{margin:10px 0 0;font-size:13.5px;color:var(--muted);line-height:1.65}
.pr-verify-go{display:none;margin-top:16px;width:100%;padding:13px 18px;border-radius:11px;
  border:0;background:var(--accent);color:#05060d;font:600 15px/1 inherit;cursor:pointer}
.pr-verify.ready .pr-verify-go{display:block}
.pr-verify-go:disabled{opacity:.55;cursor:default}
.pr-bar{height:4px;border-radius:3px;background:rgba(110,140,255,.18);margin:16px 0 10px;
  overflow:hidden}
.pr-bar>i{display:block;height:100%;width:0;background:var(--accent);transition:width .12s linear}
.pr-live{font-family:var(--mono);font-size:11.5px;color:var(--accent);overflow-wrap:anywhere;
  min-height:1.4em}
.pr-livecount{font-size:12.5px;color:var(--muted);margin-top:6px}
.pr-result{margin-top:16px;padding:14px;border-radius:11px;font-size:13.5px;line-height:1.6}
.pr-result.ok{background:rgba(47,227,160,.09);border:1px solid rgba(47,227,160,.3)}
.pr-result.broken{background:rgba(255,107,129,.09);border:1px solid rgba(255,107,129,.3)}
.pr-result b{display:block;font-size:15px;margin-bottom:5px}
.pr-result.ok b{color:var(--green)}
.pr-result.broken b{color:var(--red)}
.pr-result p{margin:0;color:var(--muted);font-size:13px}
.pr-result-actions{display:flex;flex-wrap:wrap;gap:14px;margin-top:12px}
.pr-linkbtn{background:0;border:0;padding:0;color:var(--accent);font:600 13px/1.4 inherit;
  cursor:pointer;text-align:left;text-decoration:underline;text-underline-offset:3px}
.pr-bytes{margin:10px 0 0;padding:12px;background:#05060c;border:1px solid var(--border);
  border-radius:9px;font-family:var(--mono);font-size:10.5px;line-height:1.55;color:var(--faint);
  white-space:pre-wrap;overflow-wrap:anywhere;max-height:320px;overflow:auto}
.pr-howto{margin:9px 0 0;font-size:11.5px;color:var(--faint);line-height:1.6;
  overflow-wrap:anywhere}
.pr-caveat{margin-top:12px !important;padding-top:11px;border-top:1px solid var(--border);
  font-size:12px !important;color:var(--faint) !important}
.pr-nojs{margin-top:14px;font-size:12.5px;color:var(--faint)}

/* ---- counts and rate ---- */
.pr-counts{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin-bottom:16px}
.pr-count{background:var(--panel);border:1px solid var(--border);border-radius:11px;
  padding:13px 8px;text-align:center}
.pr-count b{display:block;font-family:var(--mono);font-size:25px;font-weight:600;line-height:1.1}
.pr-count span{display:block;font-size:10.5px;color:var(--faint);margin-top:4px}
.pr-count.hit b{color:var(--green)} .pr-count.miss b{color:var(--red)}
.pr-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,230px),1fr));gap:12px}
.pr-stat{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:15px}
.pr-stat-l{display:block;font-size:12px;color:var(--faint)}
.pr-stat-v{display:block;font-family:var(--mono);font-size:30px;font-weight:600;margin:6px 0 2px}
.pr-stat-ci{display:block;font-family:var(--mono);font-size:11.5px;color:var(--muted)}
.pr-signif{margin-top:13px;font-size:12.5px;color:var(--muted);line-height:1.7}
.pr-signif b{color:var(--text)}
.pr-gate{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:17px}
.pr-gate-top{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.pr-gate-chip{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--amber);
  border:1px solid rgba(255,194,92,.36);border-radius:999px;padding:3px 9px}
.pr-gate-n{font-family:var(--mono);font-size:26px;font-weight:600}
.pr-gate-bar{height:5px;border-radius:3px;background:var(--border);margin:14px 0 8px;
  overflow:hidden}
.pr-gate-bar>span{display:block;height:100%;background:var(--amber)}
.pr-gate p{margin:8px 0 0;font-size:12.5px;color:var(--muted);line-height:1.65}

/* ---- rows ---- */
.rows{border:1px solid var(--border);border-radius:12px;overflow:hidden;background:var(--panel)}
.rc-call-row{display:grid;grid-template-columns:44px 62px 46px 40px minmax(0,1fr) 84px;
  gap:9px;align-items:center;padding:11px 13px;border-top:1px solid var(--border);font-size:13px}
.rc-call-row:first-child{border-top:0}
.rc-call-row .seq{font-family:var(--mono);color:var(--faint);font-size:11.5px}
.rc-call-row .sym{font-family:var(--mono);font-weight:600}
.rc-call-row .dir{color:var(--muted);font-size:12px}
.rc-call-row .hor{font-family:var(--mono);color:var(--muted);font-size:12px}
.rc-call-row .out{font-family:var(--mono);font-size:12px;text-align:right;overflow-wrap:anywhere}
.rc-call-row .when{font-family:var(--mono);color:var(--faint);font-size:11.5px;text-align:right}
.chip{display:inline-block;font-size:10.5px;padding:2px 8px;border-radius:999px;
  border:1px solid var(--border-2);color:var(--muted);white-space:nowrap}
.chip.hit{color:var(--green);border-color:rgba(47,227,160,.34)}
.chip.miss{color:var(--red);border-color:rgba(255,107,129,.34)}
.chip.open{color:var(--accent);border-color:rgba(110,140,255,.34)}
.pos{color:var(--green)} .neg{color:var(--red)}
.why{color:var(--faint);font-size:11px}

.loss{display:grid;grid-template-columns:62px 60px 76px minmax(0,1fr) 84px;gap:10px;
  align-items:baseline;padding:12px 13px;border-top:1px solid var(--border);font-size:13px}
.loss:first-child{border-top:0}
.loss .sym{font-family:var(--mono);font-weight:600}
.loss .dir{color:var(--muted);font-size:12px}
.loss .x{font-family:var(--mono);color:var(--red)}
.loss .th{color:var(--muted);font-size:12.5px;overflow-wrap:anywhere}
.loss .th.none{color:var(--faint);font-style:italic}
.loss .when{font-family:var(--mono);color:var(--faint);font-size:11.5px;text-align:right}

.openrow{padding:13px;border-top:1px solid var(--border)}
.openrow:first-child{border-top:0}
.openrow-head{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline;font-size:13px}
.openrow-head .sym{font-family:var(--mono);font-weight:600}
.openrow-why{display:block;margin-top:6px;font-size:12.5px;color:var(--muted);line-height:1.6}
.openrow-why b{color:var(--amber);font-weight:600}
.openrow-detail{display:block;margin-top:3px;color:var(--faint);font-size:12px;line-height:1.6;
  overflow-wrap:anywhere}
.openrow-when{color:var(--faint)}

/* Wide content scrolls inside its own box so the PAGE never scrolls sideways. Measured at 375px
   before this existed: the calibration table pushed the document 10px wide. */
.scrollx{overflow-x:auto;-webkit-overflow-scrolling:touch}
table.cal{width:100%;border-collapse:collapse;font-size:13px;min-width:320px;
  border:1px solid var(--border);border-radius:12px;overflow:hidden;background:var(--panel)}
table.cal th{text-align:left;font-size:10.5px;text-transform:uppercase;letter-spacing:.1em;
  color:var(--faint);font-weight:600;padding:10px 13px;border-bottom:1px solid var(--border)}
table.cal td{padding:10px 13px;border-top:1px solid var(--border);font-family:var(--mono)}
table.cal td:first-child{font-family:inherit}
table.cal th:not(:first-child),table.cal td:not(:first-child){text-align:right}
.thin{color:var(--faint);font-size:11.5px;font-family:inherit}

.empty{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:20px;
  color:var(--muted);font-size:13px;line-height:1.65}
.empty b{display:block;color:var(--text);margin-bottom:5px}

/* ---- the one ask ---- */
.pr-cta-box{margin-top:44px;padding:24px;border:1px solid var(--border-2);border-radius:16px;
  background:var(--card);text-align:center}
.pr-cta-box h3{margin:0 0 7px;font-size:18px}
.pr-cta-box p{margin:0 0 17px;color:var(--muted);font-size:13px;line-height:1.65}
.pr-cta{display:inline-block;padding:13px 26px;border-radius:11px;background:var(--accent);
  color:#05060d;font-weight:600;text-decoration:none}
.pr-foot{margin-top:30px;color:var(--faint);font-size:11.5px;line-height:1.7}
.pr-rules{margin-top:22px;color:var(--faint);font-size:12px;line-height:1.75}
.pr-rules b{color:var(--muted);font-weight:600}

/* NARROW SCREENS — must stay LAST. A media query adds no specificity, so a rule here loses to an
   identical selector declared after it. Checked at 375px. */
@media (max-width:560px){
  .wrap{padding:0 14px 60px}
  .pr-name{font-size:25px}
  .pr-counts{grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}
  .pr-count{padding:11px 4px}
  .pr-count b{font-size:22px}
  /* Two lines rather than six squeezed columns. The verdict and the number are what a reader
     scans for, so they share the top line with the symbol; the rest drops below it. Measured at
     375px with everything on one row: "waiting on our prices" wrapped onto three lines and made
     every open call four rows tall. */
  .rc-call-row{grid-template-columns:auto auto minmax(0,1fr);row-gap:2px;padding:10px 12px}
  .rc-call-row .seq,.rc-call-row .hor{display:none}
  .rc-call-row .out{grid-column:3;grid-row:1;text-align:right}
  .rc-call-row .chip{grid-column:2;grid-row:1}
  .rc-call-row .dir{grid-column:1;grid-row:2}
  .rc-call-row .when{grid-column:2 / -1;grid-row:2;text-align:right}
  .loss{grid-template-columns:minmax(0,1fr) 78px;row-gap:3px}
  .loss .dir,.loss .when{display:none}
  .loss .th{grid-column:1 / -1}
  table.cal th,table.cal td{padding:9px 10px}
}
"""

_VERDICT_CLASS = {"hit": "hit", "miss": "miss", "inconclusive": "", "unscoreable": ""}


# ------------------------------------------------------------------ formatting
#
# Small and local on purpose. The NUMBERS are never computed here — every one of them arrives
# already decided by `record.summary`, including the sample gate, so the worst a formatter here can
# do is print a number badly rather than print one that should not exist.

def _pct(value: float | None, dp: int = 1) -> str:
    return "not scored" if value is None else f"{value * 100:.{dp}f}%"


def _signed(value: float | None, dp: int = 2) -> str:
    if value is None:
        return "not scored"
    return f"{value * 100:+.{dp}f}%"


def _day(iso: str | None) -> str:
    return str(iso)[:10] if iso else "not held"


def _short(h: str | None) -> str:
    return f"{h[:10]}…{h[-6:]}" if h else "not held"


def _ago(iso: str | None) -> str | None:
    """How long ago, in the coarsest unit that is still true.

    Exists for one sentence: an open call past its horizon has to read as "we looked N hours ago
    and the prices still are not there", never as a blank. A reader who cannot tell "waiting" from
    "withheld" will assume the second, on the one product whose whole proposition is that nothing
    is withheld.
    """
    if not iso:
        return None
    try:
        when = datetime.fromisoformat(str(iso))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    mins = max(0, round((datetime.now(UTC) - when).total_seconds() / 60))
    if mins < 2:
        return "just now"
    if mins < 60:
        return f"{mins} minutes ago"
    hours = round(mins / 60)
    if hours < 24:
        return f"{hours} hour{'' if hours == 1 else 's'} ago"
    days = round(hours / 24)
    return f"{days} day{'' if days == 1 else 's'} ago"


def _https_only(url: str | None) -> str | None:
    """A URL, or nothing we are willing to put in an href.

    https only, and an allowlist rather than a blocklist: `javascript:` is the obvious one and
    `data:` and `vbs:` are the ones a blocklist forgets. The server refuses anything else on the
    way in; this is the second lock, so a row written by a path that does not exist yet still
    cannot become a link on a page built to be shared.
    """
    u = (url or "").strip()
    return u if u.lower().startswith("https://") else None


# ------------------------------------------------------------------ sections

def _header(caller: dict) -> str:
    out = [f'<h1 class="pr-name">{e(caller["display_name"])}</h1>',
           f'<div class="pr-handle">@{e(caller["handle"])}</div>']

    badges = []
    if caller["verified_at"]:
        how = str(caller["verification_method"] or "").replace("_", " ")
        badges.append(f'<span class="pr-badge ok">verified'
                      f'{" as ours" if how == "house" else f" by {e(how)}"}</span>')
    if caller["is_house"]:
        badges.append('<span class="pr-badge ours">our own signal engine</span>')
    if caller["kind"] == "algorithm":
        badges.append('<span class="pr-badge">algorithm</span>')
    evidence = _https_only(caller.get("verification_evidence_url"))
    if evidence:
        badges.append(f'<a class="pr-badge" href="{e(evidence)}" target="_blank" '
                      f'rel="noreferrer noopener nofollow">evidence</a>')
    audience = _https_only(caller.get("audience_url"))
    if audience:
        badges.append(f'<a class="pr-badge" href="{e(audience)}" target="_blank" '
                      f'rel="noreferrer noopener nofollow">'
                      f'{e(audience.replace("https://", ""))}</a>')
    if badges:
        out.append(f'<div class="pr-badges">{"".join(badges)}</div>')
    return "".join(out)


def _who(caller: dict, house: dict | None) -> str:
    """Who is speaking, and what we have and have not checked about them.

    BELOW the counts, not above them. Measured at 375px with the bio and the house note where the
    in-app surface puts them: a stranger's entire first screen was prose and they reached the end
    of it without seeing a single number. The record is the thing they came for, and the
    qualifications belong next to the numbers they qualify rather than in front of them.
    """
    out = []
    if caller.get("bio"):
        out.append(f'<p class="pr-bio">{e(caller["bio"])}</p>')

    # The identity note, from the server's one definition (`record.identity_note`), never a second
    # copy: two statements about what we have and have not verified would drift, and the copy that
    # drifts is the one that overstates. Shown for a verified caller too unless they are ours —
    # proving control of a newsletter is not an identity check.
    if not (caller["is_house"] or (caller["verified_at"] and caller.get("account_verified"))):
        out.append(f'<p class="pr-note">{e(caller["identity_note"])}</p>')
    if house:
        out.append(_house_banner(house))
    return "".join(out)


def _verify(caller: dict, links: int, head: str, caveat: str) -> str:
    """The centrepiece. Everything inside is filled in by `verify.js` in the visitor's browser.

    The panel states before the click what the click will do, because "Verify" on its own reads as
    a decoration. What it must leave behind is the understanding that the CALLER could not have
    edited this — and, stated in the same breath rather than buried, that we could.

    "Fingerprint" rather than "hash" in everything above the button. The reader this panel has to
    convince is the one who does not know what a hash is; the word SHA-256 appears once, below,
    where it is evidence rather than jargon.

    The one-call and no-call wordings are not polish. A caller's first record is a one-call record,
    and it is the screen they will look hardest at — "Recompute all 1 fingerprints" on the day
    someone stakes their name on this is the sentence that tells them nobody has used it.
    """
    if not links:
        return (
            '<section class="pr-verify"><h2>Check it yourself</h2>'
            '<p>Nothing has been published under this handle yet, so there is nothing to check. '
            'The moment a call is sealed here, this panel lets anyone recompute the whole record '
            'in their own browser.</p></section>')

    if links == 1:
        what = ('<p>This record holds <b>one</b> sealed call, carrying a fingerprint computed from '
                'its own text. Change a single character of it and the fingerprint stops '
                'matching. Every call published after it will carry the fingerprint of the one '
                'before, so the record welds itself together as it grows.</p>')
        press = ('<p>Press the button and your own browser downloads the sealed call and '
                 'recomputes that fingerprint on this device. We are not asked whether the record '
                 'is intact — your browser works it out.</p>')
        label = "Recompute the fingerprint here"
    else:
        what = (f'<p>Each of these <b>{links}</b> calls carries a fingerprint of the one published '
                f'before it, so they are welded into a sequence. Change a word, delete a call, '
                f'reorder two or move a date, and the fingerprints stop matching from that point '
                f'on.</p>')
        press = (f'<p>Press the button and your own browser downloads every sealed call and '
                 f'recomputes all {links} fingerprints on this device. We are not asked whether '
                 f'the record is intact — your browser works it out.</p>')
        label = f"Recompute all {links} fingerprints here"

    return (
        f'<section class="pr-verify" data-verify data-handle="{e(caller["handle"])}" '
        f'data-links="{links}" data-caveat="{e(caveat)}">'
        f'<h2>Check it yourself</h2>'
        f'{what}'
        f'<div class="pr-chainhead">latest fingerprint {e(_short(head))}</div>'
        f'{press}'
        f'<button class="pr-verify-go" data-verify-go type="button">{label}</button>'
        f'<div data-verify-live hidden>'
        f'<div class="pr-bar"><i data-verify-bar></i></div>'
        f'<div class="pr-live" data-verify-row></div>'
        f'<div class="pr-livecount" data-verify-count></div>'
        f'</div>'
        f'<div data-verify-result hidden></div>'
        f'<noscript><p class="pr-nojs">Checking the record needs JavaScript, because the '
        f'arithmetic is deliberately done on your device rather than on ours. The record below is '
        f'the same either way.</p></noscript>'
        f'</section>')


def _counts(counts: dict) -> str:
    """All five, always, and a zero rather than a gap: a record showing four counts invites the
    question of what the fifth one was."""
    cells = "".join(
        f'<div class="pr-count {_VERDICT_CLASS.get(key, "")}"><b>{counts.get(key, 0)}</b>'
        f'<span>{key}</span></div>'
        for key in ("hit", "miss", "inconclusive", "unscoreable", "open"))
    return f'<div class="pr-counts">{cells}</div>'


def _rate(summary: dict) -> str:
    """The statistics, or the reason there are none.

    `record.summary` withholds every percentage below the gate, so this cannot print one that the
    sample does not support: there is nothing here to print.
    """
    if summary["gated"]:
        n, gate = summary["resolved_scoreable"], summary["sample_gate"]
        bar = ""
        if summary["remaining_to_gate"] > 0:
            width = round(100 * n / gate)
            left = summary["remaining_to_gate"]
            bar = (f'<div class="pr-gate-bar"><span style="width:{width}%"></span></div>'
                   f'<p><b>{left} more {"call" if left == 1 else "calls"}</b> need to resolve '
                   f'before a rate is shown.</p>')
        return (f'<div class="pr-gate"><div class="pr-gate-top">'
                f'<span class="pr-gate-chip">too few to rate</span>'
                f'<span class="pr-gate-n">{n}</span>'
                f'<span class="lede" style="margin:0">resolved as a hit or a miss so far, '
                f'against the {gate} this site requires</span></div>'
                f'{bar}<p>{e(summary["gate_reason"])}</p></div>')

    ci, eci = summary["hit_rate_ci"], summary["expectancy_ci"]
    blocks = [
        f'<div class="pr-stat"><span class="pr-stat-l">right on '
        f'{summary["resolved_scoreable"]} resolved calls</span>'
        f'<b class="pr-stat-v">{_pct(summary["hit_rate"])}</b>'
        + (f'<span class="pr-stat-ci">95% interval {_pct(ci[0])} to {_pct(ci[1])}</span>'
           if ci else "") + '</div>',
        f'<div class="pr-stat"><span class="pr-stat-l">average excess per call against SPY</span>'
        f'<b class="pr-stat-v">{_signed(summary["expectancy"])}</b>'
        + (f'<span class="pr-stat-ci">95% interval {_signed(eci[0])} to {_signed(eci[1])}</span>'
           if eci else "") + '</div>',
    ]

    # Both statistics, even where they disagree. Frequency can sit significantly below chance while
    # the returns cancel out, and publishing only one of those would be true and misleading at the
    # same time.
    lines = []
    if eci:
        lines.append(
            "<b>The interval on the average spans zero, so on this sample no edge is shown in "
            "either direction.</b>" if eci[0] < 0 < eci[1] else
            f"<b>The interval on the average does not span zero, so this sample does show an "
            f"effect of {_signed(summary['expectancy'])} per call.</b>")
    if summary.get("z_vs_coinflip") is not None:
        z = summary["z_vs_coinflip"]
        lines.append(f"How often, separately: {abs(z):.2f} standard errors "
                     f"{'below' if z < 0 else 'above'} a coin flip.")
    if summary.get("sample_needed_1pct") is not None:
        lines.append(f"At the spread measured here it would take "
                     f"{summary['sample_needed_1pct']:,} resolved calls to detect a 1% per call "
                     f"edge, against the {summary['resolved_scoreable']} held.")
    return (f'<div class="pr-stats">{"".join(blocks)}</div>'
            f'<p class="pr-signif">{" ".join(lines)}</p>')


def _losses(misses: list[dict], total: int) -> str:
    if not misses:
        return ('<div class="empty"><b>No misses yet</b>Nothing here has resolved against the '
                'caller so far. This panel exists to be filled: it is the first breakdown on the '
                'page, above every other, and it stays that way.</div>')
    rows = "".join(
        f'<div class="loss"><span class="sym">{e(m["symbol"])}</span>'
        f'<span class="dir">said {e(m["direction"])}</span>'
        f'<span class="x">{_signed(m["excess_return"])}</span>'
        f'<span class="th{"" if m.get("thesis") else " none"}">'
        f'{e(m["thesis"]) if m.get("thesis") else "no reasoning published"}</span>'
        f'<span class="when">{_day(m["published_at"])}</span></div>'
        for m in misses)
    more = ""
    if total > len(misses):
        more = (f'<p class="lede" style="margin:12px 0 0">The {len(misses)} most recent of '
                f'{total}. Every one of them is in the full list below, which cannot be edited '
                f'and from which nothing can be removed.</p>')
    return f'<div class="rows">{rows}</div>{more}'


# The short form of each open reason, for a row in a list of hundreds. The full sentence comes
# from the scorer and sits beside it; repeating the whole thing in the "every call" list would push
# every other column off a phone.
_OPEN_SHORT = {
    "waiting_for_benchmark": "waiting on our benchmark",
    "waiting_for_subject_price": "waiting on our prices",
    "subject_series_ended": "price feed stopped",
}


def _open_calls(open_calls: list[dict]) -> str:
    rows = []
    for c in open_calls:
        when = _ago(c.get("open_checked_at"))
        if c.get("open_reason_code"):
            # A SHORT LABEL emphasised, and the scorer's own sentence beside it in the body colour.
            # The whole sentence was bold amber at first and it read like an error the reader was
            # supposed to do something about — when the thing it actually says is "this is our
            # data catching up, and here is when we last looked". Emphasis is for the label; the
            # explanation is prose. The sentence itself is never re-worded here: a second
            # vocabulary for why we have not scored something is a second thing that can be wrong.
            why = (f'<b>{_OPEN_SHORT.get(c["open_reason_code"], "waiting")}</b>'
                   + (f'<span class="openrow-when"> · last checked {e(when)}</span>' if when
                      else "")
                   + f'<span class="openrow-detail">{e(c["open_reason"])}</span>')
        else:
            why = "the window has not closed yet, so there is nothing to score"
        rows.append(
            f'<div class="openrow"><div class="openrow-head">'
            f'<span class="sym">{e(c["symbol"])}</span>'
            f'<span class="dir">said {e(c["direction"])}</span>'
            f'<span class="hor">{c["horizon_days"]} days</span>'
            f'<span class="openrow-when">{_day(c["published_at"])}</span></div>'
            f'<span class="openrow-why">{why}</span></div>')
    return f'<div class="rows">{"".join(rows)}</div>'


def _calibration(rows: list[dict]) -> str:
    if not any(r["n"] > 0 for r in rows):
        return ('<div class="empty"><b>Nothing to calibrate yet</b>Calibration compares what a '
                'caller said their confidence was against what actually happened. It appears once '
                'calls have resolved in each bucket.</div>')
    body = ""
    for r in rows:
        if r["observed"] is None:
            observed = (f'<span class="thin">'
                        f'{"no calls yet" if r["n"] == 0 else f"{r['n']} resolved, too few"}'
                        f'</span>')
        else:
            ci = (f' <span class="thin">({r["observed_ci"][0] * 100:.0f} to '
                  f'{r["observed_ci"][1] * 100:.0f})</span>') if r.get("observed_ci") else ""
            observed = f'{r["observed"] * 100:.1f}%{ci}'
        body += (f'<tr><td>{e(r["stated"])}</td><td>{r["n"]}</td><td>{observed}</td>'
                 f'<td>{r["hit"]}</td><td>{r["miss"]}</td></tr>')
    return ('<div class="scrollx"><table class="cal">'
            '<thead><tr><th>stated</th><th>resolved</th><th>observed</th>'
            f'<th>hit</th><th>miss</th></tr></thead><tbody>{body}</tbody></table></div>')


def _all_calls(calls: list[dict]) -> str:
    if not calls:
        return ('<div class="empty"><b>No calls published yet</b>This record is empty and says so. '
                'Nothing has been sealed, so there is nothing to score and nothing to hide. A '
                'record starts here for everyone.</div>')
    rows = []
    for c in calls:
        verdict = c["verdict"] or "open"
        if verdict == "unscoreable":
            # A chip with no reason beside it tells a reader less than nothing, so the reason sits
            # on the row rather than one click away.
            outcome = f'<span class="why">{e(c.get("verdict_note") or "")}</span>'
        elif not c["verdict"] and c.get("open_reason_code"):
            outcome = f'<span class="why">{_OPEN_SHORT.get(c["open_reason_code"], "waiting")}</span>'
        elif c.get("excess_return") is None:
            outcome = ""
        else:
            sign = "pos" if c["excess_return"] > 0 else "neg" if c["excess_return"] < 0 else ""
            outcome = f'<span class="{sign}">{_signed(c["excess_return"])}</span>'
        rows.append(
            f'<div class="rc-call-row"><span class="seq">#{c["seq"]}</span>'
            f'<span class="sym">{e(c["symbol"])}</span>'
            f'<span class="dir">{e(c["direction"])}</span>'
            f'<span class="hor">{c["horizon_days"]}d</span>'
            f'<span class="chip {_VERDICT_CLASS.get(verdict, "open" if verdict == "open" else "")}">'
            f'{verdict}</span>'
            f'<span class="out">{outcome}</span>'
            f'<span class="when">{_day(c["published_at"])}</span></div>')
    return f'<div class="rows">{"".join(rows)}</div>'


def _rules(methodology: dict) -> str:
    """The scoring rules, inline rather than a link.

    A link to the methodology page would be a second thing to click on a page whose one ask is
    "start your own record", and the visitor who wonders what "right" means here should not have to
    leave to find out. Read from `record.methodology`, so it cannot drift from the scorer.
    """
    horizons = ", ".join(str(h) for h in methodology["horizons"])
    return (f'<p class="pr-rules"><b>How this is scored.</b> A call names a symbol, a direction '
            f'and a window of {horizons} days, before the outcome is known. It enters at the close '
            f'of the first session strictly after it was published, and exits at the close on or '
            f'after its window. The result is measured against SPY over the same days, so a call '
            f'that said up in a week when the whole market rose is not credited with the market\'s '
            f'move. A move inside plus or minus {methodology["noise_floor"]:.0%} against SPY is '
            f'recorded as inconclusive rather than counted either way. No rate is published below '
            f'{methodology["sample_gate"]} resolved calls.</p>')


# ------------------------------------------------------------------ the page

def render(data: dict, *, brand: str, caveat: str, methodology: dict) -> str:
    """The whole page. `data` is the payload `/api/receipts/{handle}` returns, unchanged.

    Taking the API's own payload rather than re-querying is what stops this page and the in-app
    record surface from drifting into showing different records for the same caller — and it means
    the sample gate is applied once, upstream, where neither surface can route around it.
    """
    caller, summary = data["caller"], data["summary"]
    counts = summary["counts"]

    open_section = ""
    if data["open_calls"]:
        open_section = (
            '<section><h2>Open calls</h2>'
            '<p class="lede">Published, not yet scored. Every one of these will appear below '
            'whichever way it goes; none of them can be withdrawn. Where the window has already '
            'closed, the reason it has not been scored yet is on the row.</p>'
            f'{_open_calls(data["open_calls"])}</section>')

    return f'''<div class="wrap">
<header class="pr-top"><span class="pr-mark">&#9670;</span><b>{e(brand)}</b>
<span>&middot; a public record of market calls</span></header>

{_header(caller)}

<section><h2>The record</h2>
{_counts(counts)}
{_rate(summary)}
</section>

{_who(caller, data.get("house"))}

{_verify(caller, data["chain_links"], data["chain_head"], caveat)}

<section><h2>The losses</h2>
<p class="lede">First, and in full. Every competitor can copy a feature; none of them can
retroactively publish a record they did not keep.</p>
{_losses(data["misses"], counts.get("miss", 0))}
</section>

{open_section}

<section><h2>Calibration</h2>
<p class="lede">What they said their confidence was, against what happened. A caller who is right
more often when they said they were sure is worth reading. One whose high confidence calls do worse
than their low confidence ones is not, however good the headline looks.</p>
{_calibration(data["calibration"])}
</section>

<section><h2>Every call</h2>
<p class="lede">All {data["chain_links"]}, newest first, including the ones that went nowhere.
Nothing can be removed from this list.</p>
{_all_calls(data["calls"])}
</section>

<div class="pr-cta-box">
<h3>Start your own record</h3>
<p>Pick a handle, publish a dated call before the outcome is known, and it is sealed the same way
these are. It cannot be edited and it cannot be deleted &mdash; including by us.</p>
<a class="pr-cta" href="/claim">Claim a handle</a>
</div>

{_rules(methodology)}
<p class="pr-foot">{e(data["disclaimer"])}</p>
</div>'''


def _house_banner(house: dict) -> str:
    """The label a record carries when it is ours. Stated plainly, because a house record that
    reads like anyone else's is the one dishonest thing this product could do.

    Every clause is derived, never asserted: the in-app copy of this banner once said "which is
    below a coin flip" unconditionally with nothing checking the rate.
    """
    rate = house.get("hit_rate")
    versus = ("" if rate is None
              else ", which is below a coin flip" if rate < 0.5
              else ", which is above a coin flip, and the interval below says how much to read "
                   "into that" if rate > 0.5
              else ", which is a coin flip")
    eci = house.get("expectancy_ci")
    spans = bool(eci) and eci[0] < 0 < eci[1]
    said = ("too few to state a rate on" if rate is None
            else f"it was right {_pct(rate)} of the time{versus}")
    extra = (" Its expectancy interval spans zero, so no edge is shown in either direction."
             if spans else "")
    return (f'<p class="pr-note">This is our own signal engine, not a person. Across both '
            f'registered versions of it, {house["resolved_scoreable"]} calls resolved as a hit or '
            f'a miss and {said}.{extra} We publish it because a scoreboard that only shows winners '
            f'is not a scoreboard.</p>')


def not_found(handle: str, brand: str) -> str:
    """A dead handle is a readable page, not an error.

    It says the specific thing that is true here and is worth a stranger knowing: a call cannot be
    deleted, so a link that does not resolve was never a link to a real record.
    """
    return (f'<div class="wrap">'
            f'<header class="pr-top"><span class="pr-mark">&#9670;</span><b>{e(brand)}</b></header>'
            f'<h1 class="pr-name">No record here</h1>'
            f'<p class="pr-bio">Nobody holds the handle @{e(handle)}. Nothing has been removed: a '
            f'call cannot be deleted once it is published, so a link that does not resolve was '
            f'never a link to a real record.</p>'
            f'<div class="pr-cta-box"><h3>Start your own record</h3>'
            f'<p>Pick a handle, publish a dated call before the outcome is known, and it is sealed '
            f'so that it cannot be edited or deleted &mdash; including by us.</p>'
            f'<a class="pr-cta" href="/claim">Claim a handle</a></div></div>')
