"""Offline tests for the alert planners: threshold logic, follow matching, actor labeling, and
stable dedup keys (the exactly-once guarantee the DB driver relies on). No network, no database."""
from tradeos import alerts


def _cluster(cid, score, symbol="AAA", entity_id=1, headline="4 insiders bought"):
    return {"cluster_id": cid, "smart_money_score": score, "symbol": symbol,
            "entity_id": entity_id, "name": "Acme Corp", "headline": headline}


def test_high_conviction_respects_threshold():
    clusters = [_cluster(1, 89, "NVDA"), _cluster(2, 60, "FOO"), _cluster(3, 75, "BAR")]
    out = alerts.high_conviction_notifications(clusters, min_score=75)
    syms = {n["symbol"] for n in out}
    assert syms == {"NVDA", "BAR"}                      # 75 is included, 60 excluded
    assert all(n["kind"] == "high_conviction" for n in out)
    assert {n["dedup_key"] for n in out} == {"hc:1", "hc:3"}   # stable, per-cluster


def test_high_conviction_falls_back_to_name_when_no_symbol():
    out = alerts.high_conviction_notifications([_cluster(9, 90, symbol=None)], 75)
    assert "Acme Corp" in out[0]["title"]
    assert out[0]["symbol"] is None                     # subject text falls back, symbol stays null


def test_followed_symbol_matches_case_insensitively():
    clusters = [_cluster(1, 55, "elan".upper()), _cluster(2, 40, "ZZZ")]
    out = alerts.followed_symbol_notifications(clusters, {"ELAN"})
    assert len(out) == 1 and out[0]["symbol"] == "ELAN"
    assert out[0]["dedup_key"] == "fs:1" and out[0]["kind"] == "followed_symbol"


def test_actor_notifications_label_and_dedup_by_event():
    events = [
        {"event_kind": "insider", "event_id": 100, "actor_name": "Jane Insider", "symbol": "AAA", "entity_id": 1},
        {"event_kind": "stake", "event_id": 200, "actor_name": "Elliott Management", "symbol": "BBB", "entity_id": 2},
    ]
    out = alerts.actor_notifications(events)
    assert out[0]["dedup_key"] == "fa:i:100" and "Jane Insider" in out[0]["title"]
    assert out[1]["dedup_key"] == "fa:s:200" and "Elliott Management" in out[1]["title"]
    assert all(n["kind"] == "followed_actor" for n in out)


def test_dedup_keys_are_unique_across_a_batch():
    clusters = [_cluster(i, 80, f"S{i}") for i in range(5)]
    keys = [n["dedup_key"] for n in alerts.high_conviction_notifications(clusters, 75)]
    assert len(keys) == len(set(keys))                  # no collisions -> no double-notify
