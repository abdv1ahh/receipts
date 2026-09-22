"""The hash chain. Pure: no database, no clock, no randomness, no imports from this package.

Every call carries the hash of the call before it, so the sequence is welded together. Change one
character of one thesis and that call's hash changes; every hash after it was computed over the
old one, so the whole tail stops matching. Remove a call and the same thing happens. Swap two and
both break. There is no way to alter history that leaves the chain intact, which is exactly what
`verify_chain` is for and exactly what the Verify button on a record page runs.

WHAT THIS PROVES, precisely, because overclaiming it would be worse than not having it:

  * against the CALLER, it is tamper evident. They can publish, and that is all. They cannot edit,
    delete, reorder or backdate, and any attempt is visible to anyone who checks.
  * against the OPERATOR of this database, it is NOT. We hold every field, so we could rewrite a
    call and recompute the entire chain from that point. Closing that hole needs an anchor outside
    our control — publishing the chain head daily somewhere we cannot revise — which is on the
    roadmap and is not built. The methodology page says this in these words. It is not a
    blockchain and must never be described as one.

THE CANONICAL PAYLOAD IS A WIRE FORMAT. Once a call is sealed, its bytes are fixed forever, so the
field list, the field ORDER and the encoding below can never change. Adding a field, reordering
two, or changing how a timestamp is rendered would invalidate every chain ever published. If a new
sealed field is genuinely needed, it goes in a version 2 payload with a version marker, and both
have to be supported for as long as any v1 call exists.

WHY LENGTH PREFIXES rather than a delimiter. A thesis is free text a caller writes. With a plain
separator, a caller could type a separator into their own thesis and make two different calls
serialise to identical bytes, which is a hash collision they control — a forged prev_hash link.
Escaping is the usual answer and it is fragile; this codebase already learned once that
`str.replace` cannot sanitise a delimiter (see the prompt fence in claims.py). Prefixing each
field with its byte length removes the ambiguity instead of trying to escape it: the reader knows
how many bytes to take before it looks at them, so no content can ever be mistaken for structure.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

# The genesis link. A caller's first call chains from this, which is what makes "this is the first
# thing they ever published" a checkable statement rather than an assertion.
GENESIS_HASH = "0" * 64

# THE SEALED FIELDS, IN ORDER. Frozen forever — see the module docstring.
#
# Note what is NOT here: nothing from the resolution columns. The outcome is measured after the
# fact and must be writable once; sealing it would make scoring impossible. The chain protects the
# commitment, and the trigger plus the ledger arithmetic protect the score.
SEALED_FIELDS = (
    "caller_id",
    "seq",
    "symbol",
    "direction",
    "horizon_days",
    "confidence",
    "thesis",
    "benchmark_symbol",
    "published_at",
    "knowable_time",
)


def _render(value) -> str:
    """One value as canonical text.

    Timestamps become UTC ISO 8601 to the microsecond, always with an explicit trailing Z, so a
    call sealed by a server running in Dubai and one running in UTC produce identical bytes.
    Numerics become strings, and a Decimal is normalised so 30 and 30.00 cannot be two payloads.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("a sealed timestamp must be timezone-aware")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, bool):
        raise TypeError("no sealed field is a boolean; refusing an ambiguous rendering")
    if value is None:
        raise ValueError("a sealed field cannot be null")
    return str(value)


def rendered_fields(call: dict) -> dict[str, str]:
    """The sealed fields as canonical TEXT, in order. The half of the wire format a client cannot
    be asked to reinvent.

    This exists so a visitor's browser can recompute the chain itself. Two of the ten fields are
    timestamps, and their rendering — microseconds, an explicit trailing Z — is part of the sealed
    bytes, which a JavaScript `Date` round trip silently drops. Sending rendered text means the
    browser only has to frame and hash, and the one authority on HOW a value becomes bytes stays
    here.

    It is deliberately not "the payload, pre-assembled": the framing is what a caller could
    otherwise smuggle structure through (see the module docstring on length prefixes), so that
    part is the client's own work and is the part worth checking independently.
    """
    out = {}
    for name in SEALED_FIELDS:
        if name not in call:
            raise KeyError(f"sealed field {name!r} is missing; a partial call cannot be sealed")
        out[name] = _render(call[name])
    return out


def canonical_payload(call: dict) -> str:
    """Deterministic serialisation of the sealed fields, in the fixed order above.

    Each field is rendered as `name:byte-length:value` and the fields are joined with newlines.
    The length prefix is what makes this unambiguous for free text; see the module docstring.
    """
    return "\n".join(f"{name}:{len(text.encode('utf-8'))}:{text}"
                      for name, text in rendered_fields(call).items())


def content_hash(payload: str, prev_hash: str) -> str:
    """sha256 of (prev_hash + payload), hex.

    The previous hash goes FIRST and is part of the hashed input rather than sitting beside it,
    which is what makes each link depend on every link before it.
    """
    return hashlib.sha256((prev_hash + payload).encode("utf-8")).hexdigest()


def seal(call: dict, prev_hash: str) -> tuple[str, str]:
    """(canonical_payload, content_hash) for one call chaining from `prev_hash`."""
    payload = canonical_payload(call)
    return payload, content_hash(payload, prev_hash)


# How a client must frame the values before hashing, stated as data rather than only in two
# codebases. It is on the wire at `/api/receipts/{handle}/chain` and in every export, so somebody
# checking a record in a language nobody here has written does not have to read this source to get
# the bytes right.
FRAMING = ("each field as name:byte-length-of-value:value, joined with newline; "
           "sha256 of (prev_hash + payload), hex")


def export_payload(caller: dict, conn) -> dict:
    """One caller's whole chain, in the shape a checker needs and nothing more.

    IDENTICAL TO WHAT `/api/receipts/{handle}/chain` PUTS ON THE WIRE, deliberately, so the
    exported file and the live endpoint cannot come to disagree — the browser verifier reads one
    and `export/check.mjs` reads the other, and they are the same code.

    Values are RENDERED to text here rather than sent as JSON types. Two of the ten sealed fields
    are timestamps whose sealed spelling carries microseconds and a trailing Z, both of which a
    JavaScript `Date` round trip drops; asking a checker to reinvent that spelling would mean an
    intact record reporting as broken.
    """
    from . import calls as calls_mod
    sealed = calls_mod.for_chain(caller["id"], conn)
    return {
        "handle": caller["handle"],
        "display_name": caller["display_name"],
        "is_house": caller["is_house"],
        "fields": list(SEALED_FIELDS),
        "genesis": GENESIS_HASH,
        "framing": FRAMING,
        "head": sealed[-1]["content_hash"] if sealed else GENESIS_HASH,
        "links": [{"seq": c["seq"], "prev_hash": c["prev_hash"],
                   "content_hash": c["content_hash"],
                   "values": rendered_fields(c)} for c in sealed],
    }


def verify_chain(calls: list[dict]) -> dict:
    """Recompute every hash in sequence and report whether the record is intact.

    `calls` is every call by one caller. They are sorted by `seq` here rather than trusted to
    arrive in order, because the ordering is part of what is being checked.

    Returns `broken_at_seq` for the FIRST link that does not reconcile. That is the useful one:
    once a link breaks, every later link is computed over a wrong prev_hash and would be reported
    broken too, which would bury the actual edit under its own consequences.
    """
    ordered = sorted(calls, key=lambda c: c["seq"])
    prev = GENESIS_HASH

    for i, call in enumerate(ordered, start=1):
        # A gap or a duplicate in the sequence is a break in its own right. Without this, removing
        # a call and renumbering nothing would leave every remaining hash self-consistent, and a
        # deletion is precisely what this exists to catch.
        if call["seq"] != i:
            return {"intact": False, "links": len(ordered), "checked": i - 1,
                    "broken_at_seq": call["seq"], "expected": str(i), "found": str(call["seq"]),
                    "reason": "the sequence has a gap or a duplicate, so a call is missing"}

        if call["prev_hash"] != prev:
            return {"intact": False, "links": len(ordered), "checked": i - 1,
                    "broken_at_seq": call["seq"], "expected": prev, "found": call["prev_hash"],
                    "reason": "this call does not chain from the one before it"}

        recomputed = content_hash(canonical_payload(call), prev)
        if recomputed != call["content_hash"]:
            return {"intact": False, "links": len(ordered), "checked": i - 1,
                    "broken_at_seq": call["seq"], "expected": recomputed,
                    "found": call["content_hash"],
                    "reason": "the stored hash does not match the call's own contents"}
        prev = recomputed

    return {"intact": True, "links": len(ordered), "checked": len(ordered),
            "broken_at_seq": None, "expected": None, "found": None,
            "head": prev if ordered else GENESIS_HASH,
            "reason": "every link recomputes from the published fields"}
