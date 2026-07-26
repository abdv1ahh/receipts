"""Offline tests for Phase 8: first-run setup, tier gating, and the OAuth flow.

The OAuth tests are the important ones here, and they are also the incomplete ones. The live
handshake with Google has never been run — no credentials were available — so what is covered is
every decision the code makes *about* a response, against payloads shaped like real ones. The
network round trip is a known gap, recorded here rather than papered over.
"""
import inspect
import json
import re
import time
from base64 import urlsafe_b64encode

import pytest

from tradeos import authn, billing, mail, oauth, onboarding

# ------------------------------------------------------------------ tier gating

def test_exposure_is_paid_and_the_ledger_is_not():
    """The split the brief specifies. The Ledger is deliberately absent from every tier's
    entitlements: an accuracy record behind a paywall is not an accuracy record."""
    assert billing.entitlements("free")["exposure"] is False
    for tier in ("retail", "pro", "admin"):
        assert billing.entitlements(tier)["exposure"] is True
    for tier in billing.ENTITLEMENTS:
        assert "ledger" not in billing.ENTITLEMENTS[tier]


def test_an_unknown_tier_falls_back_to_the_least_privilege():
    assert billing.entitlements("enterprise") == billing.ENTITLEMENTS["free"]
    assert billing.entitlements(None) == billing.ENTITLEMENTS["free"]


def test_the_exposure_gate_is_enforced_in_the_route_not_the_client():
    from tradeos import app as app_module

    src = inspect.getsource(app_module.exposure_view)
    assert 'entitlements(user["tier"])["exposure"]' in src
    # And it explains itself rather than returning a bare 403 — a locked feature that says nothing
    # is indistinguishable from a broken one.
    assert '"locked": True' in src and '"what"' in src


# ------------------------------------------------------------------ first-run setup

def test_symbols_are_cleaned_deduplicated_and_capped():
    out = onboarding._clean_symbols(["  pbr ", "VALE", "vale", "", None, "toolongsymbolname"])
    assert out == ["PBR", "VALE", "TOOLONGSYMBO"]       # upper, deduped, trimmed to 12


def test_a_none_in_the_list_is_dropped_rather_than_becoming_a_ticker():
    """`str(None)` is "NONE", so a naive uppercase would quietly add a holding called NONE to
    someone's watchlist. Found by reading this function's real output rather than assuming it."""
    assert onboarding._clean_symbols([None, "", "  ", "NVDA"]) == ["NVDA"]


def test_the_watchlist_cap_holds():
    out = onboarding._clean_symbols([f"SYM{i}" for i in range(50)])
    assert len(out) == onboarding.MAX_WATCHLIST


def test_finishing_with_nothing_chosen_still_counts_as_answered():
    """Asked and answered, including "answered with nothing". Re-asking every session is the
    nagging the brief rules out."""
    src = inspect.getsource(onboarding.complete)
    assert "onboarded_at  = now()" in src
    # Nothing in the write path may reject an empty submission.
    assert "raise" not in src


def test_setup_never_gates_a_feature():
    """A reader who skips forever gets the whole product. If this module ever grows a check that
    something is unavailable without a frame, this test is the tripwire."""
    src = inspect.getsource(onboarding)
    for word in ("entitlement", "locked", "403", "forbidden", "required"):
        assert word not in src.lower().replace("not required", ""), f"onboarding mentions {word!r}"


def test_a_skip_is_temporary_by_construction():
    """"Gently persistent" — a skip snoozes, it never sets a permanent flag."""
    src = inspect.getsource(onboarding.snooze)
    assert "snoozed_until = now() +" in src
    assert "onboarded_at" not in src              # skipping must not mark it complete


def test_the_watchlist_write_is_additive():
    """Onboarding seeds a list; it must never replace one."""
    src = inspect.getsource(onboarding.complete)
    assert "ON CONFLICT DO NOTHING" in src
    assert "DELETE FROM watchlists" not in src


# ------------------------------------------------------------------ OAuth: reading the token

def _jwt(payload: dict) -> str:
    """A JWT-shaped string. Only the payload segment is ever read — see property 5 in oauth.py."""
    seg = urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"header.{seg}.signature"


def _claims(**over):
    base = {"iss": "https://accounts.google.com", "aud": "client-123", "sub": "108120",
            "exp": time.time() + 3600, "email": "Someone@Example.com", "email_verified": True}
    base.update(over)
    return base


def test_a_well_formed_token_yields_the_fields_worth_keeping():
    got = oauth.validate_claims(oauth.decode_id_token(_jwt(_claims())), "client-123")
    assert got["subject"] == "108120"
    assert got["email"] == "someone@example.com"           # normalised


def test_a_token_for_another_application_is_refused():
    """Without the audience check, a token minted for any other Google app would sign someone in
    here — the classic confused-deputy on OAuth."""
    with pytest.raises(oauth.OAuthError, match="different application"):
        oauth.validate_claims(_claims(aud="someone-elses-client"), "client-123")


def test_an_audience_list_is_accepted_when_it_contains_us():
    got = oauth.validate_claims(_claims(aud=["other", "client-123"]), "client-123")
    assert got["subject"] == "108120"


def test_a_token_from_another_issuer_is_refused():
    with pytest.raises(oauth.OAuthError, match="unexpected issuer"):
        oauth.validate_claims(_claims(iss="https://evil.example"), "client-123")


def test_an_expired_token_is_refused_and_a_missing_exp_counts_as_expired():
    with pytest.raises(oauth.OAuthError, match="expired"):
        oauth.validate_claims(_claims(exp=time.time() - 3600), "client-123")
    with pytest.raises(oauth.OAuthError, match="expired"):
        oauth.validate_claims(_claims(exp=None), "client-123")


def test_a_small_clock_skew_is_tolerated():
    """An honestly-wrong server clock should not lock everyone out."""
    got = oauth.validate_claims(_claims(exp=time.time() - 30), "client-123")
    assert got["subject"] == "108120"


def test_an_unverified_email_is_refused():
    """Otherwise anyone who can set an unverified address at the provider could claim a local
    account with that address."""
    with pytest.raises(oauth.OAuthError, match="not verified"):
        oauth.validate_claims(_claims(email_verified=False), "client-123")
    with pytest.raises(oauth.OAuthError, match="not verified"):
        oauth.validate_claims(_claims(email_verified=None), "client-123")


def test_a_string_true_is_accepted_since_not_every_provider_sends_a_bool():
    assert oauth.validate_claims(_claims(email_verified="true"), "client-123")["subject"]


def test_a_token_with_no_subject_or_no_email_is_refused():
    with pytest.raises(oauth.OAuthError, match="no subject"):
        oauth.validate_claims(_claims(sub=None), "client-123")
    with pytest.raises(oauth.OAuthError, match="no email"):
        oauth.validate_claims(_claims(email=""), "client-123")


def test_garbage_in_place_of_a_token_raises_rather_than_crashing():
    for bad in ("", "not-a-jwt", "a.b", "a.!!!.c"):
        with pytest.raises(oauth.OAuthError):
            oauth.decode_id_token(bad)


# ------------------------------------------------------------------ OAuth: the security shape

def test_state_is_consumed_by_deletion_rather_than_read_then_deleted():
    """The entire CSRF defence. A read-then-delete has a window in which two callbacks both see a
    valid state; deleting with RETURNING closes it, and the absence of a row is the rejection."""
    # Everything AFTER the docstring. Not `getdoc()` + replace (it re-indents, so it never
    # matches), and not split-on-all-quotes (the SQL below is triple-quoted too). The docstring
    # names SELECT while explaining why it is not used, which would otherwise fail this test.
    body = inspect.getsource(oauth.consume_state).split('"""', 2)[2]
    assert "DELETE FROM oauth_states" in body and "RETURNING" in body
    assert "SELECT" not in body.upper()
    assert "make_interval(secs => %s)" in body         # and it expires


def test_identity_is_keyed_on_subject_never_on_email():
    """An email is reassignable — a corporate mailbox handed to a new employee would otherwise
    inherit the previous employee's account."""
    src = inspect.getsource(oauth.link_or_create)
    lookup = src[:src.index("cur.fetchone()")]
    assert "o.subject = %s" in lookup
    assert "o.email" not in lookup


def test_an_existing_password_account_is_never_silently_merged():
    """Automatic merge-on-email is a well-worn account-takeover path."""
    src = inspect.getsource(oauth.link_or_create)
    after = src[src.index("SELECT id FROM users WHERE email"):]
    assert "raise OAuthError" in after
    assert "INSERT INTO oauth_identities" not in after[:after.index("raise OAuthError")]


def test_a_created_oauth_account_gets_an_unguessable_password():
    """`password_hash` is NOT NULL, so the account needs one. It must be random, not a constant —
    a shared sentinel would be a master password for every OAuth account."""
    src = inspect.getsource(oauth.link_or_create)
    assert "authn.hash_password(secrets.token_urlsafe(32))" in src


def test_the_token_exchange_never_logs_the_response_body():
    """The request carries the client secret and an error response can echo request parameters."""
    src = inspect.getsource(oauth.exchange_code)
    logged = [ln for ln in src.splitlines() if "log." in ln]
    assert logged, "the failure path must log something"
    for line in logged:
        assert "type(exc).__name__" in line             # the class, never the message or body
        for leak in ("r.text", "r.json", "str(exc)", "%s\", exc)"):
            assert leak not in line, f"log line leaks {leak!r}: {line.strip()}"


def test_a_banned_user_cannot_sign_in_through_the_side_door():
    src = inspect.getsource(oauth.link_or_create)
    assert "u.banned" in src and 'raise OAuthError("this account is suspended")' in src


def test_the_flow_is_inert_without_credentials():
    """Honest degradation: unconfigured means refused with a reason, never a half-working flow."""
    src = inspect.getsource(oauth.begin)
    assert "if not configured():" in src
    assert src.index("if not configured():") < src.index("secrets.token_urlsafe")


def test_the_callback_route_consumes_state_before_it_does_anything_else():
    """Order matters: exchanging the code first would let an attacker's code be redeemed before the
    CSRF check ran."""
    from tradeos import app as app_module

    src = inspect.getsource(app_module.auth_google_callback)
    assert src.index("consume_state") < src.index("exchange_code")


def test_the_callback_never_returns_a_raw_error_to_the_browser():
    """It is a navigation, not an API call — every failure lands on a page, not a JSON blob."""
    from tradeos import app as app_module

    src = inspect.getsource(app_module.auth_google_callback)
    assert "RedirectResponse" in src


def test_the_callback_sends_a_code_and_never_free_text():
    """The login screen renders this parameter, so whatever it carries is trusted-looking text on
    our real domain. If the handler reflected a MESSAGE, anyone could hand a victim a link to the
    genuine login page carrying any sentence they liked ("your account is locked, call ..."), and
    an internal exception string would travel through a URL bar into a browser.

    So the handler emits a short code, the client owns the wording, and it renders only codes it
    recognises. This fails if free text ever gets back into that redirect."""
    from tradeos import app as app_module

    src = inspect.getsource(app_module.auth_google_callback)
    # The redirect interpolates the code and nothing else.
    assert 'auth_error={code}' in src
    assert not re.search(r"auth_error=\{(?!code\})", src), "auth_error must carry only the code"
    # The exception detail may be LOGGED, but must never be the redirected value.
    assert "_fail(str(exc))" not in src
    assert re.search(r"_fail\(\s*[\"']\w+[\"']", src), "failures identify themselves by a literal code"


# ------------------------------------------------------------------ verification + reset (post-9)

def test_a_reset_request_never_reveals_whether_the_account_exists():
    """Otherwise the endpoint is a free membership oracle: point it at a list of addresses and
    learn which ones are customers. Both routes must answer identically either way."""
    from tradeos import app as app_module

    for fn in (app_module.auth_reset_request, app_module.auth_verify_request):
        src = inspect.getsource(fn)
        # Exactly one return, and it does not branch on whether a token was issued.
        assert src.count("return") == 1, f"{fn.__name__} has more than one response shape"
        assert "_ENUMERATION_SAFE" in src
        assert "if not token" not in src and "else:" not in src


def test_no_route_ever_returns_a_verification_or_reset_token():
    """The token is a temporary password. Returning it — even 'to help testing' — turns knowing an
    address into owning the account."""
    from tradeos import app as app_module

    for fn in (app_module.auth_reset_request, app_module.auth_verify_request,
               app_module.auth_reset_confirm, app_module.auth_verify_confirm):
        src = inspect.getsource(fn)
        assert '"token"' not in src.split("return")[-1], f"{fn.__name__} may return a token"


def test_tokens_are_stored_hashed_never_raw():
    """Reading the table must grant nothing."""
    src = inspect.getsource(authn.issue_token)
    assert "_hash_token(token)" in src
    assert "VALUES (%s, %s, %s," in src and "token)" not in src.split("VALUES")[1][:60]


def test_a_token_is_single_use_by_the_update_itself():
    """`used_at IS NULL` in the WHERE plus RETURNING. A read-then-mark has a window in which two
    concurrent redemptions both succeed — for a reset token that is two people setting a password."""
    src = inspect.getsource(authn.consume_token)
    assert "UPDATE auth_tokens SET used_at = now()" in src
    assert "used_at IS NULL" in src and "RETURNING user_id" in src
    assert "expires_at > now()" in src
    assert "SELECT" not in src.upper().split('"""')[-1]


def test_issuing_a_token_invalidates_the_previous_one():
    """A second 'reset my password' click must not leave the first link live."""
    src = inspect.getsource(authn.issue_token)
    invalidate = src.index("UPDATE auth_tokens SET used_at")
    insert = src.index("INSERT INTO auth_tokens")
    assert invalidate < insert, "the old token is not invalidated before the new one is minted"


def test_a_reset_signs_out_every_other_session():
    """A reset is what someone does when they think the account is compromised. Leaving the
    attacker's session alive makes it ceremonial."""
    src = inspect.getsource(authn.complete_password_reset)
    assert "DELETE FROM sessions WHERE user_id = %s" in src


def test_a_weak_password_is_refused_before_the_token_is_spent():
    """Otherwise one fat-fingered attempt burns the link and the user has to start over."""
    src = inspect.getsource(authn.complete_password_reset)
    assert src.index("is_weak_password") < src.index("consume_token")


def test_purposes_do_not_cross():
    """A verification link must not be redeemable as a password reset."""
    src = inspect.getsource(authn.consume_token)
    assert "purpose = %s" in src


def test_mail_refuses_to_send_when_unconfigured_unless_dev_echo_is_explicit():
    """The degraded path writes a capability into the log, so it cannot be the default."""
    src = inspect.getsource(mail.send)
    assert "if not configured():" in src
    assert "if dev_echo():" in src
    echo = inspect.getsource(mail.dev_echo)
    assert 'os.environ.get("MAIL_DEV_ECHO", "")' in echo       # absent means off


def test_mail_never_travels_unencrypted():
    """A message carrying a password-reset link does not go in the clear, even on a LAN."""
    src = inspect.getsource(mail.send)
    assert "starttls" in src and "SMTP_SSL" in src
    assert "s.login" in src


def test_a_mail_failure_logs_the_exception_type_not_the_envelope():
    """An SMTP error can echo the envelope, and the envelope is the recipient."""
    for line in inspect.getsource(mail.send).splitlines():
        if "log." in line and "exc" in line:
            assert "type(exc).__name__" in line
            assert "str(exc)" not in line and "%s\", exc" not in line


def test_the_link_puts_the_token_in_a_fragment_not_a_query_string():
    """A fragment is never transmitted to the server; a query string appears in the access log, in
    proxy logs, and in Referer headers. Verified before the change — uvicorn logged
    `GET /reset?token=...`, which is a working password reset sitting in a log file."""
    from tradeos import mail

    for body in (mail.reset_body("SECRET-TOKEN"), mail.verify_body("SECRET-TOKEN")):
        assert "#token=SECRET-TOKEN" in body
        assert "?token=" not in body


def test_the_request_routes_do_no_work_before_responding():
    """Both routes answer with identical wording so the response cannot reveal whether the address
    has an account — and then the response TIME would answer it anyway if the lookup, the token
    write and the SMTP round trip happened inline. Measured at 0.06s vs 0.01s before this moved."""
    from tradeos import app as app_module

    for fn in (app_module.auth_reset_request, app_module.auth_verify_request):
        src = inspect.getsource(fn)
        assert "background.add_task" in src, f"{fn.__name__} does work on the request path"
        assert "db.connect" not in src and "mail.send" not in src
