"""Sanity checks on the synthetic database itself, so the other tests can trust the answer key."""

from __future__ import annotations


def test_foreign_keys_are_consistent(db_path):
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_basket_totals_match_their_line_items(q):
    mismatched = q("""
        SELECT COUNT(*) AS n FROM txn_hdr h
        JOIN (SELECT basket_id, ROUND(SUM(sales_value - coupon_discount), 2) AS t
              FROM txn_itm GROUP BY basket_id) i USING (basket_id)
        WHERE ABS(h.total_basket_value - i.t) > 0.011""")
    assert mismatched["n"][0] == 0


def test_covers_a_full_year(q):
    assert q("SELECT COUNT(DISTINCT week) AS n FROM lookup_day")["n"][0] == 52


def test_planted_stockout_skus_sell_before_and_vanish_during(q, planted):
    upcs = ",".join(str(u) for u in sorted(planted.stockout_upcs))
    weekly = q(f"""
        SELECT h.week, SUM(i.quantity) AS units
        FROM txn_itm i JOIN txn_hdr h USING (basket_id) JOIN store s ON s.store_id = i.store_id
        WHERE s.region = :region AND i.upc IN ({upcs}) GROUP BY h.week""", region=planted.stockout_region
    ).set_index("week")["units"]
    during = range(planted.stockout_start_week, planted.stockout_end_week + 1)

    assert all(weekly.get(w, 0) == 0 for w in during), "planted SKUs must sell nothing during the outage"
    before = [weekly.get(w, 0) for w in range(1, planted.stockout_start_week)]
    assert all(u > 0 for u in before), "planted SKUs must have sales history before the outage"
    assert weekly.get(planted.stockout_end_week + 1, 0) > 0, "and recover afterwards"


def test_planted_promo_free_week_has_no_promos(q, planted):
    assert q("SELECT COUNT(*) AS n FROM promo WHERE week = :w", w=planted.no_promo_week)["n"][0] == 0
    assert q("SELECT COUNT(*) AS n FROM promo WHERE week = :w", w=planted.no_promo_week + 1)["n"][0] > 0
