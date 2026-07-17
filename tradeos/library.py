"""Intelligence library loader (Slice 5, build-plan 4.6 / 7.1).

Loads the reviewable content file (content/library/entries.json) into library_entries. Every
entry is original prose with listed public sources; entries ship as 'draft' pending founder
review (docs/review-queue.md). The library is wired into cluster detail so the product teaches
in the same moment it informs — and does so without depending on any LLM.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import psycopg
from psycopg.types.json import Json

log = logging.getLogger("tradeos.library")
CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "library" / "entries.json"


def load_entries() -> list[dict]:
    return json.loads(CONTENT_PATH.read_text())


def sync_library(conn: psycopg.Connection) -> dict:
    entries = load_entries()
    counters = {"entries": len(entries), "upserted": 0}
    with conn.cursor() as cur:
        for e in entries:
            cur.execute(
                """INSERT INTO library_entries (slug, kind, title, body_md, sources, linked_source_classes, review_status)
                   VALUES (%s,%s,%s,%s,%s,%s,'draft')
                   ON CONFLICT (slug) DO UPDATE SET
                       kind=EXCLUDED.kind, title=EXCLUDED.title, body_md=EXCLUDED.body_md,
                       sources=EXCLUDED.sources, linked_source_classes=EXCLUDED.linked_source_classes""",
                (e["slug"], e["kind"], e["title"], e["body_md"], Json(e["sources"]),
                 e.get("linked_source_classes", [])),
            )
            counters["upserted"] += 1
    conn.commit()
    log.info("sync-library: %s", counters)
    return counters
