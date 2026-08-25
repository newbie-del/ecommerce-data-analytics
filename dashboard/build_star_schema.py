"""
E-COMMERCE ANALYTICS  |  POWER BI STAR SCHEMA BUILD
===================================================

Turns the flat analytical table into an import-ready star schema for Power BI.

INPUT   ../data/processed/orders_features.csv
        ../data/processed/customer_metrics.csv
        ../data/processed/rfm_segments.csv
        ../data/processed/products.csv
OUTPUT  data/fact_sales.csv
        data/dim_date.csv
        data/dim_customer.csv
        data/dim_product.csv
        data/dim_geography.csv
        data/dim_returns_coverage.csv
        data/model_manifest.json

WHY A STAR SCHEMA RATHER THAN THE FLAT FILE
-------------------------------------------
Power BI could import orders_features.csv directly, and plenty of portfolio
projects do. It is the wrong choice here for three concrete reasons:

  1. A single flat table cannot filter two date roles. This data has an order
     date AND a ship date; a shared dim_date with an inactive relationship to
     ship_date is the only way to slice by either without duplicating the fact.
  2. dim_customer must carry the RFM segment so the Customer page can slice by
     it. On a flat table the segment would have to be repeated on all 51,290
     rows, and any correction would need a full reload.
  3. Cardinality. product_label is up to 200 characters; repeating it 51,290
     times instead of storing it once per product bloats the model for no gain.

GRAIN AND KEYS
--------------
fact_sales is one row per order line, keyed by order_line_id. The dimension
keys are the resolved keys from the cleaning layer, NOT the raw ids - see the
warning in sql/00_schema.sql. Using raw customer_id here would double the
customer count in every visual on the Customer page.

Run: python dashboard/build_star_schema.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROCESSED = ROOT / "data" / "processed"
OUT = HERE / "data"
OUT.mkdir(parents=True, exist_ok=True)

GEO_COLS = ["market", "region", "country", "state", "city"]


def date_key(s: pd.Series) -> pd.Series:
    """Integer YYYYMMDD surrogate key - the conventional Power BI date key."""
    return (s.dt.year * 10_000 + s.dt.month * 100 + s.dt.day).astype("int32")


def main() -> None:
    lines = pd.read_csv(PROCESSED / "orders_features.csv",
                        parse_dates=["order_date", "ship_date"], encoding="utf-8")
    cust = pd.read_csv(PROCESSED / "customer_metrics.csv",
                       parse_dates=["first_order_date", "last_order_date"], encoding="utf-8")
    rfm = pd.read_csv(PROCESSED / "rfm_segments.csv", encoding="utf-8")
    prod = pd.read_csv(PROCESSED / "products.csv", encoding="utf-8")

    # ---------------------------------------------------------------- dim_date
    # Spans order AND ship dates. Ship dates run into Jan 2015, so a calendar
    # built only from order dates would leave 2015 ship rows unrelated - which
    # shows up as a blank row in every ship-date visual.
    start = min(lines["order_date"].min(), lines["ship_date"].min())
    end = max(lines["order_date"].max(), lines["ship_date"].max())
    cal = pd.DataFrame({"date": pd.date_range(start, end, freq="D")})
    cal["date_key"] = date_key(cal["date"])
    cal["year"] = cal["date"].dt.year.astype("int16")
    cal["quarter"] = cal["date"].dt.quarter.astype("int8")
    cal["quarter_label"] = "Q" + cal["quarter"].astype(str)
    cal["month"] = cal["date"].dt.month.astype("int8")
    cal["month_name"] = cal["date"].dt.month_name()
    cal["month_short"] = cal["date"].dt.strftime("%b")
    cal["year_month"] = cal["date"].dt.strftime("%Y-%m")
    cal["year_month_label"] = cal["date"].dt.strftime("%b %Y")
    # Explicit sort column: without it Power BI sorts "Apr 2011" alphabetically.
    cal["year_month_sort"] = (cal["year"] * 100 + cal["month"]).astype("int32")
    cal["day_of_week"] = cal["date"].dt.day_name()
    cal["day_of_week_sort"] = cal["date"].dt.dayofweek.astype("int8")
    cal["is_weekend"] = cal["date"].dt.dayofweek.isin([5, 6]).astype("int8")
    cal = cal[["date_key", "date", "year", "quarter", "quarter_label", "month",
               "month_name", "month_short", "year_month", "year_month_label",
               "year_month_sort", "day_of_week", "day_of_week_sort", "is_weekend"]]

    # ------------------------------------------------------------ dim_customer
    seg = rfm[["customer_key", "segment", "segment_action", "label_caveat",
               "r_score", "f_score", "m_score", "rfm_sum",
               "days_since_last_purchase", "days_since_first_purchase"]]
    dim_customer = (
        cust[["customer_key", "customer_segment", "primary_market", "primary_country",
              "first_order_date", "last_order_date", "order_frequency",
              "lifetime_revenue", "lifetime_profit", "avg_order_value",
              "profit_margin_pct", "cohort_month", "is_repeat_customer",
              "avg_days_between_orders", "returned_orders", "measured_orders"]]
        .merge(seg, on="customer_key", how="left")
    )
    # Readable name for visuals: customer_key is an upper-case slug.
    names = lines.groupby("customer_key")["customer_name"].first()
    dim_customer["customer_name"] = dim_customer["customer_key"].map(names)
    dim_customer["is_unprofitable"] = (dim_customer["lifetime_profit"] < 0).astype("int8")
    dim_customer["cohort_year"] = dim_customer["first_order_date"].dt.year.astype("int16")
    dim_customer["first_order_date_key"] = date_key(dim_customer["first_order_date"])

    # ------------------------------------------------------------- dim_product
    dim_product = prod[["product_id", "product_label", "category", "sub_category",
                        "brand", "name_variants", "ambiguous_name",
                        "n_lines", "quantity", "revenue", "profit"]].copy()
    dim_product = dim_product.rename(columns={
        "n_lines": "lifetime_order_lines", "quantity": "lifetime_units",
        "revenue": "lifetime_revenue", "profit": "lifetime_profit"})
    dim_product["lifetime_margin_pct"] = np.where(
        dim_product["lifetime_revenue"] > 0,
        dim_product["lifetime_profit"] / dim_product["lifetime_revenue"] * 100, np.nan)
    # Quadrant, precomputed so the same definition is used by the notebook, the
    # SQL and the dashboard instead of three drifting versions.
    median_rev = dim_product["lifetime_revenue"].median()
    dim_product["revenue_tier"] = np.where(
        dim_product["lifetime_revenue"] >= median_rev, "High revenue", "Low revenue")
    dim_product["profit_quadrant"] = np.select(
        [(dim_product["lifetime_revenue"] >= median_rev) & (dim_product["lifetime_profit"] > 0),
         (dim_product["lifetime_revenue"] >= median_rev) & (dim_product["lifetime_profit"] <= 0),
         (dim_product["lifetime_revenue"] < median_rev) & (dim_product["lifetime_profit"] > 0)],
        ["1 High revenue / High profit", "2 High revenue / LOW profit",
         "3 Low revenue / High margin"],
        default="4 Low revenue / Low profit")
    dim_product["is_ambiguous_name"] = dim_product["ambiguous_name"].astype("int8")

    # ----------------------------------------------------------- dim_geography
    geo = lines[GEO_COLS].drop_duplicates().sort_values(GEO_COLS).reset_index(drop=True)
    geo.insert(0, "geography_key", np.arange(1, len(geo) + 1, dtype="int32"))

    # ------------------------------------------------- dim_returns_coverage
    covered = sorted(lines.loc[lines["returns_measured"] == 1, "market"].unique())
    coverage = pd.DataFrame({"market": sorted(lines["market"].unique())})
    coverage["has_returns_data"] = coverage["market"].isin(covered).astype("int8")
    coverage["coverage_note"] = np.where(
        coverage["has_returns_data"] == 1,
        "Returns recorded - rate is valid",
        "NO return records - rate is UNKNOWN, not zero")

    # ------------------------------------------------ fact_cohort_retention
    # The retention matrix needs MONTHS-SINCE-ACQUISITION, which cannot be
    # derived in DAX without a costly calculated column spanning two tables.
    # Reshaping the already-computed matrix to long form gives Power BI exactly
    # the grain it needs, and guarantees the dashboard heatmap and the notebook
    # heatmap are the same numbers rather than two independent calculations.
    retention = pd.read_csv(PROCESSED / "cohort_retention.csv", index_col=0)
    counts = pd.read_csv(PROCESSED / "cohort_counts.csv", index_col=0)
    ret_long = (
        retention.stack().rename("retention_pct").reset_index()
        .rename(columns={retention.index.name or "index": "cohort_month",
                         "level_1": "period_index"})
    )
    cnt_long = (
        counts.stack().rename("active_customers").reset_index()
        .rename(columns={counts.index.name or "index": "cohort_month",
                         "level_1": "period_index"})
    )
    ret_long.columns = ["cohort_month", "period_index", "retention_pct"]
    cnt_long.columns = ["cohort_month", "period_index", "active_customers"]
    cohort = ret_long.merge(cnt_long, on=["cohort_month", "period_index"], how="left")
    cohort["period_index"] = cohort["period_index"].astype(int)
    size = cohort.loc[cohort["period_index"] == 0,
                      ["cohort_month", "active_customers"]].rename(
        columns={"active_customers": "cohort_size"})
    cohort = cohort.merge(size, on="cohort_month", how="left")
    # Drop cells beyond a cohort's observation window - they are structurally
    # absent, not zero, and plotting them as 0% would fake a retention cliff.
    cohort = cohort[cohort["active_customers"].notna() & (cohort["cohort_size"] > 0)]
    cohort["cohort_month_sort"] = (
        cohort["cohort_month"].str.slice(0, 4).astype(int) * 100
        + cohort["cohort_month"].str.slice(5, 7).astype(int)).astype("int32")

    # --------------------------------------------------------------- fact
    fact = lines.merge(geo, on=GEO_COLS, how="left", validate="many_to_one")
    if fact["geography_key"].isna().any():
        raise AssertionError("geography join left unmatched rows")

    fact["order_date_key"] = date_key(fact["order_date"])
    fact["ship_date_key"] = date_key(fact["ship_date"])

    fact_sales = fact[[
        "order_line_id", "order_id", "order_key",
        "order_date_key", "ship_date_key",
        "customer_key", "product_id", "geography_key",
        "ship_mode", "order_priority", "discount_band",
        "quantity", "revenue", "list_revenue", "discount", "discount_amount",
        "cost", "profit", "shipping_cost",
        "return_flag", "returns_measured", "is_loss_making", "ship_lag_days",
    ]].rename(columns={"product_id": "product_key"})

    # -------------------------------------------------- referential integrity
    # A star schema that silently loses rows to a broken key produces visuals
    # that are quietly wrong, so every relationship is asserted before writing.
    checks = {
        "fact rows preserved": len(fact_sales) == len(lines),
        "order_date_key resolves": fact_sales["order_date_key"].isin(cal["date_key"]).all(),
        "ship_date_key resolves": fact_sales["ship_date_key"].isin(cal["date_key"]).all(),
        "customer_key resolves": fact_sales["customer_key"].isin(dim_customer["customer_key"]).all(),
        "product_key resolves": fact_sales["product_key"].isin(dim_product["product_id"]).all(),
        "geography_key resolves": fact_sales["geography_key"].isin(geo["geography_key"]).all(),
        "dim_customer unique": dim_customer["customer_key"].is_unique,
        "dim_product unique": dim_product["product_id"].is_unique,
        "dim_date unique": cal["date_key"].is_unique,
        "dim_geography unique": geo["geography_key"].is_unique,
        "revenue preserved": abs(fact_sales["revenue"].sum() - lines["revenue"].sum()) < 0.01,
        "profit preserved": abs(fact_sales["profit"].sum() - lines["profit"].sum()) < 0.01,
    }
    failed = [k for k, v in checks.items() if not v]
    if failed:
        raise AssertionError(f"star schema integrity failed: {failed}")

    # --------------------------------------------------------------- write
    tables = {
        "fact_sales": fact_sales,
        "dim_date": cal,
        "dim_customer": dim_customer,
        "dim_product": dim_product,
        "dim_geography": geo,
        "dim_returns_coverage": coverage,
        "fact_cohort_retention": cohort,
    }
    for name, df in tables.items():
        df.to_csv(OUT / f"{name}.csv", index=False, encoding="utf-8")

    manifest = {
        "generated_from": "data/processed/orders_features.csv",
        "grain": "fact_sales = one row per order line",
        "snapshot_date": str(lines["order_date"].max().date()),
        "tables": {name: {"rows": int(len(df)), "columns": int(df.shape[1])}
                   for name, df in tables.items()},
        "relationships": [
            {"from": "fact_sales[order_date_key]", "to": "dim_date[date_key]",
             "cardinality": "many-to-one", "active": True,
             "note": "primary date role"},
            {"from": "fact_sales[ship_date_key]", "to": "dim_date[date_key]",
             "cardinality": "many-to-one", "active": False,
             "note": "inactive; activate via USERELATIONSHIP for ship-date measures"},
            {"from": "fact_sales[customer_key]", "to": "dim_customer[customer_key]",
             "cardinality": "many-to-one", "active": True},
            {"from": "fact_sales[product_key]", "to": "dim_product[product_id]",
             "cardinality": "many-to-one", "active": True},
            {"from": "fact_sales[geography_key]", "to": "dim_geography[geography_key]",
             "cardinality": "many-to-one", "active": True},
            {"from": "dim_geography[market]", "to": "dim_returns_coverage[market]",
             "cardinality": "many-to-one", "active": True,
             "note": "carries the returns-coverage flag so no visual reports 0% "
                     "for an unmeasured market"},
        ],
        "integrity_checks": {k: bool(v) for k, v in checks.items()},
    }
    (OUT / "model_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STAR SCHEMA BUILT")
    print("=" * 66)
    for name, df in tables.items():
        print(f"  {name:<24} {len(df):>7,} rows x {df.shape[1]:>2} cols")
    print()
    print(f"  date range          : {cal['date'].min().date()} to {cal['date'].max().date()}")
    print(f"  revenue reconciles  : {fact_sales['revenue'].sum():,.2f}")
    print(f"  profit reconciles   : {fact_sales['profit'].sum():,.2f}")
    print(f"  integrity checks    : {len(checks)}/{len(checks)} passed")
    print(f"\n  written to {OUT}")


if __name__ == "__main__":
    main()
