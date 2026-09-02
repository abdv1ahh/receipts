"""Proving a caller controls the audience they claim.

The question this answers is narrow and worth stating exactly: not "who is this person" but "is
whoever publishes here the same party who publishes at that newsletter or that site". That is the
only claim a record page makes, and it is the only one that needs proving. Identity documents would
prove something else, cost money, and create a file of passports we have no business holding.

The mechanism is the oldest one on the web and it is free. We issue a one time code; the caller
publishes it somewhere only they can publish; they paste back the URL; a human confirms. No third
party API, no scraping, nothing to pay for, and it degrades to a manual review rather than to a
wrong answer.

TWO METHODS, BOTH FREE:

  public_post   put the code in a public post, a newsletter issue, or a pinned message. Best for
                someone whose audience lives on a platform rather than a domain.
  meta_tag      put the code in a meta tag on a page of your own site. Best for someone with a
                domain, and the cheapest to check.

`wallet_signature` is declared in the migration's CHECK constraint and is deliberately not
implemented and not offered in the interface. It is there so the column does not need altering
later, not as a hint that it is coming.

WHY NOTHING IS FETCHED HERE. Confirming an evidence URL by having the server fetch it makes this
endpoint a request forwarder aimed at any address a stranger names, which is a server side request
forgery hole. `radar.webhook_target_ok` already solves exactly this problem in this codebase: it
refuses anything that is not https, and refuses private, loopback, link local and metadata
addresses on every resolved IP, then re-checks at send time because DNS can change between the
check and the request. If automated fetching is ever added here, it must call THAT function. It
must not grow a second one, because the second one is the one that will be missing a case.
"""
from __future__ import annotations

import secrets

import psycopg

# Methods a caller may actually choose today.
METHODS = ("public_post", "meta_tag")

CODE_PREFIX = "receipts-verify-"
# 8 characters from a 32 character alphabet is 40 bits. The code is not a secret that protects
# anything: it is a nonce that has to be hard to guess before the caller publishes it, and it is
# reviewed by a human afterwards. 40 bits is far past that bar.
_ALPHABET = "abcdefghijkmnopqrstuvwxyz23456789"      # no l, no 1, no 0, no o


def new_code() -> str:
    return CODE_PREFIX + "".join(secrets.choice(_ALPHABET) for _ in range(8))


INSTRUCTIONS = {
    "public_post": ("Publish this code, exactly as written, in a public post or a newsletter issue "
                    "that your audience can see. Then paste the link to that post below. It can "
                    "be deleted once you are verified."),
    "meta_tag": ("Add this tag to the head of any page on your own site, then paste the address of "
                 "that page below:\n"
                 '<meta name="receipts-verify" content="{code}">'),
}


def start(caller_id: int, method: str, conn: psycopg.Connection) -> dict:
    """Issue a one time code and return the instructions for the chosen method.

    A caller may restart as often as they like. Each start issues a fresh code and supersedes any
    earlier pending request, so a code pasted into the wrong place is fixed by trying again rather
    than by asking us.
    """
    if method not in METHODS:
        return {"error": f"choose one of: {', '.join(METHODS)}."}
    code = new_code()
    with conn.cursor() as cur:
        cur.execute("""UPDATE caller_verifications SET status = 'rejected', resolved_at = now()
                        WHERE caller_id = %s AND status = 'pending'""", (caller_id,))
        cur.execute("""INSERT INTO caller_verifications (caller_id, code, method)
                       VALUES (%s, %s, %s) RETURNING id, created_at""",
                    (caller_id, code, method))
        vid, created = cur.fetchone()
    conn.commit()
    return {"id": vid, "code": code, "method": method,
            "created_at": created.isoformat(),
            "instructions": INSTRUCTIONS[method].format(code=code)}


def confirm(caller_id: int, evidence_url: str, conn: psycopg.Connection) -> dict:
    """Record where the code was published and put the request in front of a human.

    The URL is stored and shown to a reviewer. It is not fetched. See the module docstring.
    """
    url = (evidence_url or "").strip()
    if not url.lower().startswith("https://"):
        return {"error": "the evidence link has to be an https address."}

    with conn.cursor() as cur:
        cur.execute("""SELECT id, code, method FROM caller_verifications
                        WHERE caller_id = %s AND status = 'pending'
                     ORDER BY created_at DESC LIMIT 1""", (caller_id,))
        row = cur.fetchone()
        if not row:
            return {"error": "there is no verification in progress. Start one first."}
        vid, code, method = row
        cur.execute("UPDATE caller_verifications SET evidence_url = %s WHERE id = %s", (url, vid))
    conn.commit()
    return {"id": vid, "status": "pending", "code": code, "method": method, "evidence_url": url,
            "note": "Submitted. A person checks the link and confirms that the code is on it. "
                    "Until then your record page is live but shows as unverified."}


def pending(conn: psycopg.Connection) -> list[dict]:
    """Everything waiting for a reviewer, oldest first. The admin queue."""
    with conn.cursor() as cur:
        cur.execute("""SELECT v.id, v.caller_id, c.handle, c.display_name, v.code, v.method,
                              v.evidence_url, v.created_at
                         FROM caller_verifications v JOIN callers c ON c.id = v.caller_id
                        WHERE v.status = 'pending' AND v.evidence_url IS NOT NULL
                     ORDER BY v.created_at""")
        return [{"id": r[0], "caller_id": r[1], "handle": r[2], "display_name": r[3], "code": r[4],
                 "method": r[5], "evidence_url": r[6], "created_at": r[7].isoformat()}
                for r in cur.fetchall()]


def review(verification_id: int, approve: bool, conn: psycopg.Connection) -> dict:
    """A reviewer's decision. Approving stamps the caller as verified with the method used.

    Rejecting does not delete anything and does not touch a single call. A caller who cannot prove
    their audience still has a record; it simply says unverified, which is the truth about it.
    """
    with conn.cursor() as cur:
        cur.execute("""SELECT caller_id, method, evidence_url, status FROM caller_verifications
                        WHERE id = %s""", (verification_id,))
        row = cur.fetchone()
        if not row:
            return {"error": f"there is no verification {verification_id}."}
        caller_id, method, evidence_url, status = row
        if status != "pending":
            return {"error": f"this request was already {status}."}

        cur.execute("""UPDATE caller_verifications SET status = %s, resolved_at = now()
                        WHERE id = %s""", ("confirmed" if approve else "rejected", verification_id))
        if approve:
            cur.execute("""UPDATE callers SET verified_at = now(), verification_method = %s,
                                              verification_evidence_url = %s
                            WHERE id = %s""", (method, evidence_url, caller_id))
    conn.commit()
    return {"id": verification_id, "caller_id": caller_id,
            "status": "confirmed" if approve else "rejected"}
