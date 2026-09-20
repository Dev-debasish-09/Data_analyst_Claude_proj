"""Synthetic retail data generator (DEV ENVIRONMENT ONLY).

Builds one year (52 weeks) of fake transactions in a local SQLite file that matches the
Retail Pulse schema: txn_hdr, txn_itm, upc, store, lookup_day, household_segmentation, promo.

Realism built in:
  * Seasonality  - annual sine wave, holiday-week bumps, day-of-week pattern, and
                   department-level seasonal shapes (e.g. beverages peak in summer).
  * Promo lift   - promoted UPC/store/weeks are chosen far more often and in larger
                   quantities, scaled by discount depth.
  * Planted anomalies (recorded in the dev-only `dev_ground_truth` table so detection
    logic can be tested against a known answer):
      1. Regional stockout - the 8 top-selling Beverages UPCs sell zero in every West-region
         store for weeks 30-33, after 29 weeks of normal sales history.
      2. A promo-free week (week 20) for testing the "no promos" edge case.

Usage (from the project root):
    python scripts/generate_synthetic_data.py [--output PATH] [--seed N] [--force]

The generator refuses to run unless RETAIL_PULSE_ENV is dev, and output defaults to the
SQLite path in RETAIL_PULSE_DB_URL. The database is gitignored (*.db).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import ConfigError, load_settings  # noqa: E402

# --------------------------------------------------------------------------- constants
N_WEEKS = 52
N_DAYS = N_WEEKS * 7
START_DATE = date(2025, 1, 1)
N_STORES = 24
N_HOUSEHOLDS = 1500
BASKETS_PER_STORE_WEEK = 55  # average, before size/season scaling
REGIONS = ["North", "South", "East", "West"]

HOLIDAYS = {
    date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 14), date(2025, 5, 26),
    date(2025, 7, 4), date(2025, 9, 1), date(2025, 10, 31), date(2025, 11, 27),
    date(2025, 12, 24), date(2025, 12, 25),
}  # fmt: skip
# Extra weekly demand lift around the big shopping weeks (Thanksgiving = wk 48, Christmas = wk 51/52).
WEEK_HOLIDAY_BUMP = {47: 0.15, 48: 0.30, 51: 0.25, 52: 0.20}
DAY_OF_WEEK_WEIGHT = np.array([0.85, 0.85, 0.9, 0.95, 1.15, 1.35, 1.2])  # by weekday(), Mon=0

# department -> (commodities, brands, price range, seasonal peak week, seasonal amplitude, n_upcs)
DEPARTMENTS = {
    "Produce": (["Fruit", "Vegetables", "Salad"], ["FreshFarm", "GreenValley", "OrchardCo"], (0.8, 5.0), 28, 0.15, 40),
    "Dairy": (["Milk", "Cheese", "Yogurt"], ["DairyPure", "MooBrand", "CreamCo"], (1.5, 6.5), 26, 0.05, 30),
    "Bakery": (["Bread", "Pastry", "Cake"], ["DailyLoaf", "SweetOven", "CrustCo"], (1.5, 7.0), 50, 0.25, 25),
    "Beverages": (["Soda", "Juice", "Water"], ["FizzUp", "SunSip", "AquaClear"], (1.0, 8.0), 28, 0.35, 30),
    "Frozen": (["Meals", "Desserts", "Vegetables"], ["ChillCo", "FrostFare", "IceBay"], (2.5, 9.0), 51, 0.20, 25),
    "Snacks": (["Chips", "Cookies", "Candy"], ["CrunchTime", "SnackShack", "SweetTreat"], (1.2, 6.0), 44, 0.20, 30),
    "Household": (["Cleaning", "Paper", "Laundry"], ["SparkleCo", "HomeEase", "PureWash"], (2.0, 14.0), 13, 0.05, 25),
    "Meat": (["Beef", "Poultry", "Seafood"], ["PrimeCut", "FarmHouse", "OceanCatch"], (4.0, 18.0), 27, 0.15, 35),
}  # fmt: skip

# store format -> (weight, size_sqft range, traffic multiplier)
STORE_FORMATS = {
    "Supercenter": (0.3, (90_000, 150_000), 1.7),
    "Standard": (0.5, (35_000, 60_000), 1.0),
    "Express": (0.2, (8_000, 15_000), 0.5),
}

# segment -> (share, income bands, family-size range, basket-size multiplier)
SEGMENTS = {
    "Budget Families": (0.30, ["<35k", "35-60k"], (3, 6), 1.25),
    "Affluent Households": (0.20, ["100-150k", "150k+"], (1, 4), 1.10),
    "Young Singles": (0.25, ["<35k", "35-60k", "60-100k"], (1, 2), 0.70),
    "Established Couples": (0.25, ["60-100k", "100-150k"], (2, 3), 0.95),
}

STOCKOUT = {"region": "West", "department": "Beverages", "n_upcs": 8, "start_week": 30, "end_week": 33}
NO_PROMO_WEEK = 20

SCHEMA = """
CREATE TABLE lookup_day (
    day INTEGER PRIMARY KEY, week INTEGER NOT NULL, calendar_date TEXT NOT NULL,
    holiday_flag INTEGER NOT NULL, season TEXT NOT NULL);
CREATE TABLE store (
    store_id INTEGER PRIMARY KEY, region TEXT NOT NULL, store_format TEXT NOT NULL,
    size_sqft INTEGER NOT NULL);
CREATE TABLE upc (
    upc INTEGER PRIMARY KEY, department TEXT NOT NULL, commodity TEXT NOT NULL,
    brand TEXT NOT NULL, base_price REAL NOT NULL);
CREATE TABLE household_segmentation (
    household_id INTEGER PRIMARY KEY, segment_name TEXT NOT NULL, income_band TEXT NOT NULL,
    family_size INTEGER NOT NULL);
CREATE TABLE promo (
    upc INTEGER NOT NULL REFERENCES upc(upc), store_id INTEGER NOT NULL REFERENCES store(store_id),
    week INTEGER NOT NULL, promo_type TEXT NOT NULL, discount_pct REAL NOT NULL,
    PRIMARY KEY (upc, store_id, week));
CREATE TABLE txn_hdr (
    basket_id INTEGER PRIMARY KEY, household_id INTEGER NOT NULL REFERENCES household_segmentation(household_id),
    store_id INTEGER NOT NULL REFERENCES store(store_id), day INTEGER NOT NULL REFERENCES lookup_day(day),
    week INTEGER NOT NULL, trans_time TEXT NOT NULL, total_basket_value REAL NOT NULL);
CREATE TABLE txn_itm (
    basket_id INTEGER NOT NULL REFERENCES txn_hdr(basket_id), household_id INTEGER NOT NULL,
    store_id INTEGER NOT NULL, day INTEGER NOT NULL, upc INTEGER NOT NULL REFERENCES upc(upc),
    quantity INTEGER NOT NULL, sales_value REAL NOT NULL, retail_discount REAL NOT NULL,
    coupon_discount REAL NOT NULL, promo_flag INTEGER NOT NULL);
-- Dev-only answer key for the planted anomalies. Never exists in staging/prod.
CREATE TABLE dev_ground_truth (
    anomaly_type TEXT NOT NULL, region TEXT, store_id INTEGER, upc INTEGER,
    start_week INTEGER, end_week INTEGER, note TEXT);
CREATE INDEX ix_itm_store_day ON txn_itm(store_id, day);
CREATE INDEX ix_itm_upc ON txn_itm(upc);
CREATE INDEX ix_itm_basket ON txn_itm(basket_id);
CREATE INDEX ix_hdr_store_week ON txn_hdr(store_id, week);
CREATE INDEX ix_hdr_household ON txn_hdr(household_id);
"""


# --------------------------------------------------------------------------- dimensions
def season_of(d: date) -> str:
    return {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Spring",
            6: "Summer", 7: "Summer", 8: "Summer"}.get(d.month, "Fall")  # fmt: skip


def build_lookup_day() -> pd.DataFrame:
    rows = []
    for day in range(1, N_DAYS + 1):
        d = START_DATE + timedelta(days=day - 1)
        rows.append((day, (day - 1) // 7 + 1, d.isoformat(), int(d in HOLIDAYS), season_of(d)))
    return pd.DataFrame(rows, columns=["day", "week", "calendar_date", "holiday_flag", "season"])


def build_stores(rng: np.random.Generator) -> pd.DataFrame:
    formats = list(STORE_FORMATS)
    fmt_p = [STORE_FORMATS[f][0] for f in formats]
    rows = []
    for i in range(N_STORES):
        fmt = formats[rng.choice(len(formats), p=fmt_p)]
        lo, hi = STORE_FORMATS[fmt][1]
        rows.append((i + 1, REGIONS[i % len(REGIONS)], fmt, int(rng.integers(lo, hi))))
    return pd.DataFrame(rows, columns=["store_id", "region", "store_format", "size_sqft"])


def build_upcs(rng: np.random.Generator) -> pd.DataFrame:
    rows, upc = [], 1_000_000
    for dept, (commodities, brands, (lo, hi), *_, n) in DEPARTMENTS.items():
        for _ in range(n):
            upc += 1
            price = round(float(rng.uniform(lo, hi)), 2)
            rows.append((upc, dept, rng.choice(commodities), rng.choice(brands), price))
    return pd.DataFrame(rows, columns=["upc", "department", "commodity", "brand", "base_price"])


def build_households(rng: np.random.Generator) -> pd.DataFrame:
    names = list(SEGMENTS)
    seg_idx = rng.choice(len(names), size=N_HOUSEHOLDS, p=[SEGMENTS[n][0] for n in names])
    rows = []
    for i, s in enumerate(seg_idx):
        _, bands, (fs_lo, fs_hi), _ = SEGMENTS[names[s]]
        rows.append((i + 1, names[s], rng.choice(bands), int(rng.integers(fs_lo, fs_hi + 1))))
    return pd.DataFrame(rows, columns=["household_id", "segment_name", "income_band", "family_size"])


def build_promos(rng: np.random.Generator, upcs: pd.DataFrame, stores: pd.DataFrame) -> pd.DataFrame:
    """Each week ~20 UPCs are promoted in a random subset of regions (whole-region promos)."""
    types = {"TPR": (0.10, 0.30), "Feature": (0.15, 0.35), "Display": (0.10, 0.25)}
    rows = []
    for week in range(1, N_WEEKS + 1):
        if week == NO_PROMO_WEEK:
            continue
        for upc in rng.choice(upcs["upc"].to_numpy(), size=20, replace=False):
            ptype = rng.choice(list(types))
            pct = round(float(rng.uniform(*types[ptype])), 2)
            regions = rng.choice(REGIONS, size=int(rng.integers(1, len(REGIONS) + 1)), replace=False)
            for sid in stores.loc[stores["region"].isin(regions), "store_id"]:
                rows.append((int(upc), int(sid), week, ptype, pct))
    return pd.DataFrame(rows, columns=["upc", "store_id", "week", "promo_type", "discount_pct"])


# --------------------------------------------------------------------------- transactions
def week_demand_factor(week: int, lookup: pd.DataFrame) -> float:
    annual = 1 + 0.10 * np.sin(2 * np.pi * (week - 10) / N_WEEKS)
    n_holidays = int(lookup.loc[lookup["week"] == week, "holiday_flag"].sum())
    return float(annual + 0.05 * n_holidays + WEEK_HOLIDAY_BUMP.get(week, 0.0))


def dept_seasonality(depts: np.ndarray, week: int) -> np.ndarray:
    """Multiplier per UPC from its department's seasonal shape (cosine peaking at peak week)."""
    factors = {
        d: 1 + amp * np.cos(2 * np.pi * (week - peak) / N_WEEKS)
        for d, (_, _, _, peak, amp, _) in DEPARTMENTS.items()
    }
    return np.array([factors[d] for d in depts])


def generate_transactions(rng, lookup, stores, upcs, households, promos, ground_truth):
    upc_ids = upcs["upc"].to_numpy()
    upc_dept = upcs["department"].to_numpy()
    upc_price = upcs["base_price"].to_numpy()
    n_upcs = len(upc_ids)
    popularity = rng.lognormal(mean=0.0, sigma=0.8, size=n_upcs)  # heavy-tailed SKU popularity

    # Plant the stockout: the most popular Beverages UPCs in the West region.
    bev_idx = np.where(upc_dept == STOCKOUT["department"])[0]
    stockout_idx = bev_idx[np.argsort(popularity[bev_idx])[::-1][: STOCKOUT["n_upcs"]]]
    west_stores = stores.loc[stores["region"] == STOCKOUT["region"], "store_id"].tolist()
    for sid in west_stores:
        for ix in stockout_idx:
            ground_truth.append(("regional_stockout", STOCKOUT["region"], sid, int(upc_ids[ix]),
                                 STOCKOUT["start_week"], STOCKOUT["end_week"],
                                 "Zero sales despite prior sales history"))  # fmt: skip
    ground_truth.append(("no_promo_week", None, None, None, NO_PROMO_WEEK, NO_PROMO_WEEK,
                         "No promo rows exist for this week"))  # fmt: skip

    hh_ids = households["household_id"].to_numpy()
    hh_seg_mult = households["segment_name"].map({k: v[3] for k, v in SEGMENTS.items()}).to_numpy()
    hh_home = rng.choice(stores["store_id"].to_numpy(), size=len(hh_ids))  # primary store
    home_pools = {sid: np.where(hh_home == sid)[0] for sid in stores["store_id"]}

    upc_pos = {u: i for i, u in enumerate(upc_ids)}
    promo_by_key = {k: g for k, g in promos.groupby(["store_id", "week"])}
    week_days = lookup.groupby("week")["day"].apply(list).to_dict()
    day_weight = {
        int(r.day): DAY_OF_WEEK_WEIGHT[(START_DATE + timedelta(days=int(r.day) - 1)).weekday()]
        * (0.3 if r.holiday_flag else 1.0)
        for r in lookup.itertuples()
    }
    hour_p = np.array([1, 2, 3, 4, 4, 4, 3, 3, 4, 5, 6, 5, 3, 2], dtype=float)  # 08:00-21:00
    hour_p /= hour_p.sum()

    hdr_parts, itm_parts, basket_id = [], [], 0
    for store in stores.itertuples():
        traffic = STORE_FORMATS[store.store_format][2]
        for week in range(1, N_WEEKS + 1):
            lam = BASKETS_PER_STORE_WEEK * traffic * week_demand_factor(week, lookup)
            n_b = int(rng.poisson(lam))
            if n_b == 0:
                continue

            days = np.array(week_days[week])
            dp = np.array([day_weight[d] for d in days])
            b_day = rng.choice(days, size=n_b, p=dp / dp.sum())
            local = rng.random(n_b) < 0.9  # 90% of baskets come from households homed here
            pool = home_pools[store.store_id]
            hh_ix = np.where(local & (len(pool) > 0),
                             pool[rng.integers(0, max(len(pool), 1), n_b)],
                             rng.integers(0, len(hh_ids), n_b))  # fmt: skip
            b_ids = np.arange(basket_id + 1, basket_id + n_b + 1)
            basket_id += n_b
            hours = rng.choice(np.arange(8, 22), size=n_b, p=hour_p)
            trans_time = [f"{h:02d}:{m:02d}:{s:02d}" for h, m, s in zip(
                hours, rng.integers(0, 60, n_b), rng.integers(0, 60, n_b), strict=True)]  # fmt: skip

            # Item weights for this store-week: popularity x dept season x promo lift x availability.
            w = popularity * dept_seasonality(upc_dept, week)
            promo_pct = np.zeros(n_upcs)
            g = promo_by_key.get((store.store_id, week))
            if g is not None:
                for u, pct in zip(g["upc"], g["discount_pct"], strict=True):
                    promo_pct[upc_pos[u]] = pct
            promoted = promo_pct > 0
            w = w * np.where(promoted, 1 + 12 * promo_pct, 1.0)  # ~3x-5x lift at 20-35% off
            if (store.region == STOCKOUT["region"]
                    and STOCKOUT["start_week"] <= week <= STOCKOUT["end_week"]):  # fmt: skip
                w[stockout_idx] = 0.0
                promoted[stockout_idx] = False
                promo_pct[stockout_idx] = 0.0
            p = w / w.sum()

            n_items = 1 + rng.poisson(6.0 * hh_seg_mult[hh_ix])
            basket_of_item = np.repeat(np.arange(n_b), n_items)
            item_upc = rng.choice(n_upcs, size=len(basket_of_item), p=p)
            item_promo = promoted[item_upc]
            qty = 1 + rng.poisson(np.where(item_promo, 0.7, 0.35))
            gross = qty * upc_price[item_upc]
            retail_disc = np.round(np.where(item_promo, gross * promo_pct[item_upc], 0.0), 2)
            coupon = np.round(np.where(rng.random(len(gross)) < 0.04, gross * 0.10, 0.0), 2)
            sales = np.round(gross - retail_disc, 2)
            total = np.round(np.bincount(basket_of_item, weights=sales - coupon, minlength=n_b), 2)

            hdr_parts.append(pd.DataFrame({
                "basket_id": b_ids, "household_id": hh_ids[hh_ix], "store_id": store.store_id,
                "day": b_day, "week": week, "trans_time": trans_time, "total_basket_value": total,
            }))  # fmt: skip
            itm_parts.append(pd.DataFrame({
                "basket_id": b_ids[basket_of_item], "household_id": hh_ids[hh_ix][basket_of_item],
                "store_id": store.store_id, "day": b_day[basket_of_item],
                "upc": upc_ids[item_upc], "quantity": qty, "sales_value": sales,
                "retail_discount": retail_disc, "coupon_discount": coupon,
                "promo_flag": item_promo.astype(int),
            }))  # fmt: skip
    return pd.concat(hdr_parts, ignore_index=True), pd.concat(itm_parts, ignore_index=True)


# --------------------------------------------------------------------------- output
def resolve_output(cli_output: str | None) -> Path:
    """Only dev may generate synthetic data; default path comes from the dev DB URL."""
    try:
        settings = load_settings()
    except ConfigError as exc:
        raise SystemExit(f"Refusing to run: {exc}") from exc
    if not settings.is_dev:
        raise SystemExit(f"Refusing to run: synthetic data is dev-only (env={settings.env.value}).")
    if cli_output:
        return Path(cli_output)
    prefix = "sqlite:///"
    if not settings.db_url.startswith(prefix):
        raise SystemExit(f"Dev DB URL must be sqlite, got: {settings.db_url}")
    return Path(settings.db_url[len(prefix):])


def write_database(path: Path, tables: dict[str, pd.DataFrame]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        # Insert in FK-dependency order.
        for name in ["lookup_day", "store", "upc", "household_segmentation", "promo",
                     "txn_hdr", "txn_itm", "dev_ground_truth"]:  # fmt: skip
            tables[name].to_sql(name, conn, if_exists="append", index=False, chunksize=50_000)


def generate_database(out: Path, seed: int = 42) -> dict[str, pd.DataFrame]:
    """Build the full synthetic dataset and write it to `out` (which must not exist).

    Pure generation with no environment checks, so tests can build a throwaway database in a
    temp directory. The CLI (`main`) adds the dev-only guard and overwrite handling.
    """
    rng = np.random.default_rng(seed)
    lookup = build_lookup_day()
    stores = build_stores(rng)
    upcs = build_upcs(rng)
    households = build_households(rng)
    promos = build_promos(rng, upcs, stores)
    truth: list[tuple] = []
    hdr, itm = generate_transactions(rng, lookup, stores, upcs, households, promos, truth)
    truth_df = pd.DataFrame(truth, columns=["anomaly_type", "region", "store_id", "upc",
                                            "start_week", "end_week", "note"])  # fmt: skip

    tables = {
        "lookup_day": lookup, "store": stores, "upc": upcs, "household_segmentation": households,
        "promo": promos, "txn_hdr": hdr, "txn_itm": itm, "dev_ground_truth": truth_df,
    }  # fmt: skip
    write_database(out, tables)
    return tables


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--output", help="SQLite file path (default: from RETAIL_PULSE_DB_URL)")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducible data")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing database")
    args = parser.parse_args()

    out = resolve_output(args.output)
    if out.exists():
        if not args.force:
            raise SystemExit(f"{out} already exists; pass --force to overwrite.")
        out.unlink()

    tables = generate_database(out, args.seed)
    print(f"Wrote {out} (seed={args.seed})")
    for name in ["txn_hdr", "txn_itm", "promo", "upc", "store", "household_segmentation"]:
        print(f"  {name:<24}{len(tables[name]):>10,} rows")


if __name__ == "__main__":
    main()
