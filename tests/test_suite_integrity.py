"""The suite is not allowed to go green by not running.

WHY THIS FILE EXISTS, and it is a measurement rather than a principle. The database-backed test
modules open with

    try:
        from tradeos import db, something
        _IMPORTS_OK = True
    except Exception:
        _IMPORTS_OK = False

and skip the whole file when that flag is False. The intent is good: `make test` must stay runnable
on a machine with no database and no driver. The hole is that `except Exception` cannot tell
"psycopg is not installed here" from "this file imports a module that was deleted" — and during the
Receipts extraction it could not. `test_receipts_api.py` still imported `presentation`, which had
just been removed, so 38 assertions covering the public HTTP boundary reported themselves as
SKIPPED and the run said `354 passed`. Green, and covering nothing.

The check is the one thing the guard cannot do for itself: if the database IS reachable from here,
then every module carrying that flag must have set it True. A skip is then a real environment, and
never a stale import.
"""
from __future__ import annotations

import importlib
import pathlib

import pytest

TESTS = pathlib.Path(__file__).resolve().parent


def _db_reachable() -> bool:
    try:
        from tradeos import db
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_reachable(),
                    reason="no database here, so a guarded skip is honest and there is nothing to check")
def test_no_module_skips_itself_on_a_stale_import():
    """Runs only where the guards' own premise is false — a machine that HAS a database. Anything
    still reporting `_IMPORTS_OK = False` there is importing something that is not there."""
    broken = {}
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name == pathlib.Path(__file__).name:
            continue
        module = importlib.import_module(f"tests.{path.stem}")
        if getattr(module, "_IMPORTS_OK", True) is False:
            broken[path.name] = _why(path)
    assert not broken, (
        "these files are skipping themselves on a broken import, not on a missing database:\n" +
        "\n".join(f"  {name}: {why}" for name, why in sorted(broken.items())))


def _why(path: pathlib.Path) -> str:
    """Re-run the guarded import block so the failure is NAMED rather than left as a flag.

    A test that says "something in this file does not import" and stops has reproduced the
    original problem one level up.
    """
    src = path.read_text()
    if "try:" not in src:
        return "no guarded import block found"
    body = src.split("try:", 1)[1].split("except", 1)[0]
    code = "\n".join(line[4:] if line.startswith("    ") else line for line in body.splitlines())
    try:
        exec(compile(code, str(path), "exec"), {})            # noqa: S102 — our own test source
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return "the guarded block imports cleanly; the flag is set somewhere else"
