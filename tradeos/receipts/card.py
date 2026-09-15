"""The share card for one public record — the only marketing asset this product has.

MOVED HERE from `presentation.py`, and the move is not tidying. `presentation` opens with
`from .signals.convergence import DEFAULT_PARAMS`, so the route serving this card imported the
convergence signal — the dead plane the deletion is meant to remove. `docs/receipts_protected.md`
recorded `signals/` as "NOT A DEPENDENCY. Not in the graph, not referenced", and
`docs/receipts_gap_analysis.md` §5.3 corrected that by measurement: removing
`tradeos.signals.convergence` from `sys.modules` broke `GET /api/card/receipt/{handle}`. The
dependency ran through the ROUTE, which a package-level graph rooted at `receipts/` cannot see.
`_BUCKETS` is used only by `smart_money_score`; this card never touched it. Moving the two
functions severs `presentation` AND `signals` from Receipts in one step.

WHY THERE IS A PNG AT ALL. The card was SVG, and `og:image` pointed at it with a RELATIVE URL.
Either defect alone breaks a link preview: the Open Graph protocol requires an absolute URL, and no
major platform renders SVG as a preview image — X's card spec accepts JPG, PNG, WEBP and GIF, and
Facebook's scraper does not accept SVG either. So the single mechanism the whole distribution model
rests on ("checkers arrive for free when callers share their page") produced a bare text link, and
had never once worked. The SVG is kept and still served: it is sharper in a browser tab, it is what
`/r/{handle}` shows in the page body, and it costs nothing.

FONTS. Measured in the running image: `/usr/share/fonts` holds ZERO TrueType files, and
`docs/receipts_gap_analysis.md` §GAP 3 concluded from that a font must be installed or vendored.
It does not: Pillow 12.3.0's `ImageFont.load_default(size=...)` returns a SCALABLE FreeTypeFont
(Aileron, embedded in the wheel since Pillow 10.1), so the card renders at any size with no apt
layer, no vendored `.ttf`, no Dockerfile change and nothing new in `requirements.txt`. One family
rather than three is a real cost and it is why the layout below leans on scale, weight and colour
instead of on a serif/mono contrast the browser card can use.

THE ONE RULE NEITHER RENDERER MAY BREAK: a gated record shows counts and the words Low N, and
never a percentage. A share card travels further from its own context than anything else in this
product, so it is the worst possible place to print a rate the sample cannot support.

AND THE SECOND RULE: losses are as large as wins. A card that only ever showed good numbers would
be an advertisement rather than a receipt, and the thing being sold here is that it is a receipt.
The two house records read 40.8% and 48.5% — below a coin flip — and the card has to be something a
caller would still post at those numbers. What makes it postable is not the rate; it is that the
record is sealed and checkable, which is what the card leads with.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- the palette
#
# Low saturation on purpose. Neon green for a hit and alarm red for a miss would put a thumb on the
# scale of how a reader feels about a number that is meant to be read, not reacted to — and a
# record that makes its own losses look like emergencies is a record nobody will publish honestly.
INK = {
    "bg": "#05060c", "panel": "#0e111b", "border": "#1b2130",
    "text": "#eaecf4", "muted": "#8b93ab", "faint": "#7b83a0",
    "hit": "#7fb69a", "miss": "#c98a95", "accent": "#6e8cff",
    "dim": "#3a4256",
}
_SERIF = "Instrument Serif, Iowan Old Style, Georgia, serif"
_MONO = "IBM Plex Mono, ui-monospace, SF Mono, Menlo, Consolas, monospace"
_SANS = "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif"

WIDTH, HEIGHT = 1200, 630          # the Open Graph standard, and what every platform crops to


def _xml_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ---------------------------------------------------------------- the SVG (unchanged behaviour)

def _count_block(x: int, label: str, value: int, colour: str) -> str:
    return (f'<text x="{x}" y="330" font-family="{_MONO}" font-size="58" font-weight="600" '
            f'fill="{colour}">{value}</text>'
            f'<text x="{x}" y="364" font-family="{_SANS}" font-size="19" fill="{INK["faint"]}" '
            f'letter-spacing="1.5">{_xml_escape(label)}</text>')


def receipt_card_svg(handle: str, display_name: str, counts: dict, hit_rate: float | None,
                     hit_rate_ci: list | None, resolved_scoreable: int, links: int,
                     brand: str, verified: bool = False, is_house: bool = False) -> str:
    """The share card for one public record. Pure: every value is passed in from a real query.

    `hit_rate` arriving as None IS the gated case, and it is the only signal this function needs:
    `record.summary` already refuses to return a rate below the sample gate, so a percentage can
    never reach this card without having cleared it upstream.
    """
    ink = INK
    gated = hit_rate is None

    if gated:
        headline = (f'<text x="80" y="470" font-family="{_MONO}" font-size="40" fill="{ink["muted"]}" '
                    f'letter-spacing="2">LOW N</text>'
                    f'<text x="230" y="470" font-family="{_SANS}" font-size="23" fill="{ink["faint"]}">'
                    f'{resolved_scoreable} resolved so far. A rate is not shown below 25.</text>')
    else:
        ci = ""
        if hit_rate_ci:
            ci = (f'<text x="330" y="470" font-family="{_MONO}" font-size="25" fill="{ink["faint"]}">'
                  f'95% interval {hit_rate_ci[0]:.1%} to {hit_rate_ci[1]:.1%}</text>')
        headline = (f'<text x="80" y="478" font-family="{_MONO}" font-size="62" font-weight="600" '
                    f'fill="{ink["text"]}">{hit_rate:.1%}</text>'
                    f'<text x="330" y="440" font-family="{_SANS}" font-size="23" fill="{ink["muted"]}">'
                    f'right on {resolved_scoreable} resolved calls</text>{ci}')

    house = ""
    if is_house:
        house = (f'<text x="80" y="212" font-family="{_SANS}" font-size="20" fill="{ink["accent"]}" '
                 f'letter-spacing="1.5">OUR OWN SIGNAL ENGINE</text>')

    mark = "&#10003; verified" if verified else "unverified"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="{ink["bg"]}"/>
  <rect x="40" y="40" width="1120" height="550" rx="18" fill="{ink["panel"]}" stroke="{ink["border"]}"/>
  <text x="80" y="112" font-family="{_SANS}" font-size="21" font-weight="700" fill="{ink["accent"]}" letter-spacing="3">{_xml_escape(brand.upper())}</text>
  <text x="1120" y="112" font-family="{_SANS}" font-size="19" fill="{ink["faint"]}" text-anchor="end">{mark}</text>
  <line x1="80" y1="140" x2="1120" y2="140" stroke="{ink["border"]}"/>
  {house}
  <text x="80" y="{"268" if is_house else "250"}" font-family="{_SERIF}" font-size="60" fill="{ink["text"]}">{_xml_escape(display_name)}</text>
  <text x="80" y="{"306" if is_house else "288"}" font-family="{_MONO}" font-size="25" fill="{ink["muted"]}">@{_xml_escape(handle)}</text>
  {_count_block(80, "HIT", counts.get("hit", 0), ink["hit"])}
  {_count_block(240, "MISS", counts.get("miss", 0), ink["miss"])}
  {_count_block(400, "INCONCLUSIVE", counts.get("inconclusive", 0), ink["muted"])}
  {_count_block(690, "UNSCOREABLE", counts.get("unscoreable", 0), ink["muted"])}
  {_count_block(960, "OPEN", counts.get("open", 0), ink["muted"])}
  <line x1="80" y1="400" x2="1120" y2="400" stroke="{ink["border"]}"/>
  {headline}
  <text x="1120" y="470" font-family="{_MONO}" font-size="23" fill="{ink["accent"]}" text-anchor="end">{links} sealed calls, chained</text>
  <text x="80" y="548" font-family="{_SANS}" font-size="19" fill="{ink["faint"]}">Past performance does not predict future results. This measures public statements and is not investment advice.</text>
</svg>'''


# ---------------------------------------------------------------- the PNG (what a feed renders)

# The faces, in preference order, and why any files are named here at all.
#
# Pillow 12's `load_default(size=)` returns a SCALABLE face (Aileron), so a card renders with no
# font installed, and that is what the first version of this used. Then it was measured. Rendering
# a private-use codepoint gives a font's tofu signature in pixels, and against that signature
# Aileron draws U+00E9 (e-acute) as a BOX -- along with the em dash, the bullet, the check mark and
# every arrow. A caller whose name carries an accent would have seen boxes where their own name
# should be, on the one asset this product asks them to post.
#
# So the image installs `fonts-dejavu-core` (one apt layer, ~3MB, nothing added to
# `requirements.txt`) and this resolves to it. `load_default` stays as the fallback, because a
# missing font has to degrade to an uglier card rather than to a 500 on a public route.
_FACES = {
    "sans": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "mono": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "serif": "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
}
_unavailable: set[str] = set()


def _font(size: int, face: str = "sans"):
    """A scalable face at `size`, preferring DejaVu and falling back to Pillow's embedded one."""
    path = _FACES.get(face)
    if path and path not in _unavailable:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            # Remembered, so a missing font costs one failed open per process rather than one per
            # text run on every card this worker ever renders.
            _unavailable.add(path)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                                   # pragma: no cover - Pillow < 10.1
        return ImageFont.load_default()


def font_covers(ch: str, face: str = "sans", size: int = 40) -> bool:
    """Whether the resolved face has a real glyph for `ch` rather than a tofu box.

    Pillow exposes no API for this, so it is measured: render `ch`, render a private-use codepoint
    no font ships, and compare the ink. Identical ink means the same `.notdef` box came back both
    times. The tests use this to stop the card silently regressing to boxes, which is exactly the
    kind of defect nobody notices until a caller posts one.
    """
    def ink(c: str) -> int:
        img = Image.new("L", (size * 3, size * 3), 0)
        ImageDraw.Draw(img).text((4, 4), c, font=_font(size, face), fill=255)
        # `get_flattened_data`, not `getdata`: the latter is deprecated for removal in Pillow 14
        # and emits a warning on every call, which this makes one of per glyph per test.
        return sum(1 for px in img.get_flattened_data() if px > 40)
    return ink(ch) != ink("\ue000")


def _plural(n: int, one: str, many: str | None = None) -> str:
    """`1 sealed call`, not `1 sealed calls`. The card is the product's shop window and a grammar
    slip on it reads as carelessness about everything else."""
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _text(d: ImageDraw.ImageDraw, xy, s: str, size: int, colour: str,
          anchor: str = "la", face: str = "sans") -> float:
    """Draw, and return the advance width so the NEXT run can start where this one ended.

    Returned rather than estimated. The first version of this card positioned inline runs with
    arithmetic on the character count -- `80 + 12 * len(brand) + 34` -- and at 1200px the brand
    name collided with the tagline beside it. A proportional face has no character width to
    multiply, and `textlength` is the only thing that knows.
    """
    font = _font(size, face)
    d.text(xy, s, font=font, fill=colour, anchor=anchor)
    return d.textlength(s, font=font)


def receipt_card_png(handle: str, display_name: str, counts: dict, hit_rate: float | None,
                     hit_rate_ci: list | None, resolved_scoreable: int, links: int,
                     brand: str, verified: bool = False, is_house: bool = False,
                     sample_gate: int = 25) -> bytes:
    """1200x630 PNG for `og:image`. Same gate, same honesty, different medium.

    DESIGNED FOR A THUMBNAIL, because that is where almost everyone sees it: a feed renders this at
    roughly 300px wide, which is a 4x reduction, and a phone timeline can be narrower still. Only
    three things are allowed to be large enough to survive that — the handle, the outcome bar and
    the headline figure — and everything else is deliberately texture. The recurring mistake in
    card design is to fill the space with legible-at-full-size detail that becomes grey noise at
    the size it is actually viewed.

    THE OUTCOME BAR is the load-bearing element and the reason this reads at 120px. Text stops
    resolving long before a proportion does, so the record's shape — how much of it is red —
    survives every reduction. It is also the most honest possible summary: a caller cannot crop
    their losses out of a bar that is mostly losses.
    """
    img = Image.new("RGB", (WIDTH, HEIGHT), INK["bg"])
    d = ImageDraw.Draw(img)
    gated = hit_rate is None

    # the panel
    d.rounded_rectangle([40, 40, WIDTH - 40, HEIGHT - 40], radius=18,
                        fill=INK["panel"], outline=INK["border"], width=1)

    # --- the strip along the top: who is publishing this, and what it is
    w = _text(d, (80, 84), brand.upper(), 26, INK["accent"])
    _text(d, (80 + w + 22, 88), "a public record of market calls", 22, INK["faint"])
    _text(d, (WIDTH - 80, 88), "verified" if verified else "unverified", 22,
          INK["hit"] if verified else INK["faint"], anchor="ra")
    d.line([80, 130, WIDTH - 80, 130], fill=INK["border"], width=1)

    # --- WHO. The handle is the largest text on the card, because it is the thing a reader has to
    #     carry away: the record is at that address and nowhere else.
    _text(d, (80, 166), f"@{handle}", 58, INK["text"], face="mono")
    _text(d, (80, 244), display_name, 34, INK["muted"], face="serif")
    if is_house:
        _text(d, (WIDTH - 80, 172), "OUR OWN SIGNAL ENGINE", 22, INK["accent"], anchor="ra")

    # --- THE BAR. Hit, miss, inconclusive, in proportion, full width.
    hit, miss, inc = counts.get("hit", 0), counts.get("miss", 0), counts.get("inconclusive", 0)
    resolved = hit + miss + inc
    bar_y, bar_h = 316, 34
    if resolved:
        x = 80.0
        span = float(WIDTH - 160)
        for n, colour in ((hit, INK["hit"]), (miss, INK["miss"]), (inc, INK["dim"])):
            if not n:
                continue
            w = span * n / resolved
            d.rectangle([x, bar_y, x + max(2.0, w) - 1, bar_y + bar_h], fill=colour)
            x += w
        # The legend. WINS AND LOSSES AT THE SAME SIZE, side by side and in that order: a card
        # whose losses were smaller than its wins would be an advertisement, not a receipt.
        for i, (label, n, colour) in enumerate((("right", hit, INK["hit"]),
                                                ("wrong", miss, INK["miss"]),
                                                ("inconclusive", inc, INK["muted"]))):
            x = 80 + i * 300
            w = _text(d, (x, bar_y + 52), str(n), 42, colour, face="bold")
            _text(d, (x + w + 16, bar_y + 70), label, 22, INK["faint"])
    else:
        # NOTHING RESOLVED YET, which is the card almost every new caller will share -- and the
        # first version of this printed "0 right, 0 wrong, 0 inconclusive, nothing resolved yet".
        # Three zeros read as a record that has failed to produce, which is not what is true: what
        # is true is that a commitment has been sealed before the outcome was known and is pending.
        # That is also the only part worth posting at this stage, so it leads.
        #
        # Not flattery. The gate below still refuses a percentage and still says LOW N. This
        # changes which TRUE thing is largest, not whether an unflattering one is shown.
        open_n = counts.get("open", 0)
        d.rectangle([80, bar_y, WIDTH - 80, bar_y + bar_h], fill=INK["panel"],
                    outline=INK["accent"], width=2)
        _text(d, (WIDTH // 2, bar_y + bar_h // 2), "OPEN - WAITING FOR THE WINDOW TO CLOSE", 20,
              INK["accent"], anchor="mm")
        w = _text(d, (80, bar_y + 52), str(open_n), 42, INK["text"], face="bold")
        _text(d, (80 + w + 16, bar_y + 70),
              f"{_plural(open_n, 'call')} published and sealed before the outcome was known. "
              f"{'None have' if open_n != 1 else 'It has not'} resolved yet.", 22, INK["faint"])

    # --- THE HEADLINE. A rate if the sample earned one; the count and the words LOW N if not.
    d.line([80, 452, WIDTH - 80, 452], fill=INK["border"], width=1)
    if gated:
        w = _text(d, (80, 480), "LOW N", 38, INK["muted"], face="bold")
        _text(d, (80 + w + 26, 490), f"{resolved_scoreable} resolved so far. A rate is not shown "
                                     f"below {sample_gate}.", 24, INK["faint"])
    else:
        w = _text(d, (80, 474), f"{hit_rate:.1%}", 56, INK["text"], face="bold")
        _text(d, (80 + w + 22, 476), f"right on {resolved_scoreable} resolved calls", 24,
              INK["muted"])
        if hit_rate_ci:
            # The interval, on the card, always. A rate without it is the number that misleads, and
            # a share card is the furthest this product's numbers travel from their own context.
            _text(d, (80 + w + 22, 508),
                  f"95% interval {hit_rate_ci[0]:.1%} to {hit_rate_ci[1]:.1%}", 22, INK["faint"])

    # --- the footer. The chain, which is the actual claim, and the disclaimer.
    _text(d, (WIDTH - 80, 480), f"{_plural(links, 'sealed call')}, chained", 24, INK["accent"],
          anchor="ra")
    _text(d, (WIDTH - 80, 512), "each carrying the hash of the one before it", 20, INK["faint"],
          anchor="ra")
    # Inside the panel, with room under it. At 19px a baseline any lower crossed the panel's own
    # bottom border, which reads as a rendering fault rather than as small print.
    # Measured against the panel's own width rather than eyeballed: DejaVu is wider than the
    # embedded face this was first drawn in, and at 19px the original wording ran 1080px into a
    # 1040px space, ending flush against the panel border. The record page carries the disclaimer
    # in full; the card carries the two clauses that have to travel with a number.
    _text(d, (80, 552), "Measures public statements. Not investment advice. Past performance "
                        "does not predict future results.", 19, INK["dim"])

    buf = io.BytesIO()
    # `optimize` rather than a quality setting: a PNG is lossless, and every platform that fetches
    # this refetches it rarely, so the few kB matter less than not resampling the type.
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
