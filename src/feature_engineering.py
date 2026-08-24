"""
E-COMMERCE ANALYTICS  |  FEATURE ENGINEERING
============================================

Builds every derived metric the analysis needs, from formulas rather than
hardcoded values, on top of the cleaned order-line table.

INPUT   data/processed/orders_clean.csv
OUTPUT  data/processed/orders_features.csv   order lines + derived metrics
        data/processed/orders_agg.csv        one row per order
        data/processed/customer_metrics.csv  one row per resolved customer
        data/processed/monthly_kpis.csv      month-level KPI time series

TWO MEASUREMENT DECISIONS THAT ARE STATED, NOT ASSUMED
------------------------------------------------------
1. `revenue` is NET of discount. This was tested empirically in the cleaning
   audit (section 10) across 6,671 products sold both at full price and at a
   discount: the model `unit = list x (1 - discount)` reproduces the observed
   unit price with 0.0% median error, versus 40% if revenue were gross. List
   revenue is therefore reconstructed exactly as `revenue / (1 - discount)`,
   not approximated.

2. Whether `shipping_cost` is ALREADY deducted from `profit` cannot be
   determined from this extract. Both readings are defensible: shipping is
   11.9% of net revenue, so netting it again would cut reported margin from
   11.61% to 0.91%. Rather than pick silently, this module reports `profit`
   exactly as recorded and exposes `profit_after_shipping` as an explicitly
   labelled worst-case scenario column. No headline figure double-counts
   shipping, and the ambiguity is disclosed in the README.

A NOTE ON RECENCY
-----------------
The data ends 2014-12-31. Recency is measured against that snapshot date, not
against today - otherwise every customer would look 12 years dormant. The
snapshot is written into the outputs so no downstream consumer can drift.

Run: python src/feature_engineering.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
CLEAN = PROCESSED / "orders_clean.csv"

DATE_COLS = ["order_date", "ship_date"]

# Discount bands used across the dashboard and the notebook. Defined once here
# so the Power BI model, the SQL and the notebook cannot drift apart.
DISCOUNT_BINS = [-0.001, 0.0, 0.10, 0.20, 0.30, 0.50, 1.0]
DISCOUNT_LABELS = ["0% (none)", "1-10%", "11-20%", "21-30%", "31-50%", "51%+"]


def load_clean(path: Path = CLEAN) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=DATE_COLS, encoding="utf-8")
    return df


# ===========================================================================
# LINE-LEVEL METRICS
# ===========================================================================
def add_line_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Per-order-line derived measures. All formula-driven."""
    df = df.copy()

    # Cost is exact, not assumed: profit is real, so cost = revenue - profit.
    df["cost"] = df["revenue"] - df["profit"]

    # List (pre-discount) revenue. Verified relationship, see module docstring.
    # discount never reaches 1.0 (max observed 0.85) so this cannot divide by zero.
    df["list_revenue"] = df["revenue"] / (1.0 - df["discount"])
    df["discount_amount"] = df["list_revenue"] - df["revenue"]

    # Per-unit economics.
    df["unit_price_net"] = df["revenue"] / df["quantity"]
    df["unit_price_list"] = df["list_revenue"] / df["quantity"]
    df["unit_cost"] = df["cost"] / df["quantity"]

    # Margin. Guarded against division by zero even though revenue > 0 holds in
    # this extract - the guard keeps the module safe if the source ever changes.
    df["profit_margin_pct"] = np.where(
        df["revenue"] > 0, df["profit"] / df["revenue"] * 100.0, np.nan)

    # Explicitly-labelled scenario column (see docstring decision 2). Never used
    # as a headline figure.
    df["profit_after_shipping"] = df["profit"] - df["shipping_cost"]

    df["is_loss_making"] = (df["profit"] < 0).astype("int8")
    df["ship_lag_days"] = (df["ship_date"] - df["order_date"]).dt.days

    df["discount_band"] = pd.cut(
        df["discount"], bins=DISCOUNT_BINS, labels=DISCOUNT_LABELS, right=True)

    return df


def add_date_parts(df: pd.DataFrame) -> pd.DataFrame:
    """Calendar fields for trend and seasonality analysis."""
    df = df.copy()
    d = df["order_date"]
    df["order_year"] = d.dt.year.astype("int16")
    df["order_month"] = d.dt.month.astype("int8")
    df["order_quarter"] = d.dt.quarter.astype("int8")
    df["order_ym"] = d.dt.to_period("M").astype("string")
    df["order_month_start"] = d.dt.to_period("M").dt.to_timestamp()
    df["order_month_name"] = d.dt.month_name().astype("string")
    df["order_dow"] = d.dt.day_name().astype("string")
    return df


# ===========================================================================
# ORDER LEVEL
# ===========================================================================
def build_order_table(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse order lines to one row per real order (composite key)."""
    orders = (
        df.groupby("order_key", observed=True)
        .agg(
            order_id=("order_id", "first"),
            customer_key=("customer_key", "first"),
            customer_segment=("customer_segment", "first"),
            order_date=("order_date", "min"),
            ship_date=("ship_date", "max"),
            market=("market", "first"),
            region=("region", "first"),
            country=("country", "first"),
            n_lines=("order_line_id", "size"),
            quantity=("quantity", "sum"),
            order_value=("revenue", "sum"),
            list_value=("list_revenue", "sum"),
            discount_amount=("discount_amount", "sum"),
            cost=("cost", "sum"),
            profit=("profit", "sum"),
            shipping_cost=("shipping_cost", "sum"),
            return_flag=("return_flag", "max"),
            returns_measured=("returns_measured", "max"),
            ship_lag_days=("ship_lag_days", "max"),
        )
        .reset_index()
    )
    orders["order_margin_pct"] = np.where(
        orders["order_value"] > 0, orders["profit"] / orders["order_value"] * 100.0, np.nan)
    orders["effective_discount_pct"] = np.where(
        orders["list_value"] > 0, orders["discount_amount"] / orders["list_value"] * 100.0, np.nan)
    orders["order_ym"] = orders["order_date"].dt.to_period("M").astype("string")
    orders["order_year"] = orders["order_date"].dt.year.astype("int16")
    return orders


# ===========================================================================
# CUSTOMER LEVEL
# ===========================================================================
def build_customer_metrics(orders: pd.DataFrame, snapshot: pd.Timestamp) -> pd.DataFrame:
    """Customer lifetime metrics, measured against the dataset snapshot date."""
    cust = (
        orders.groupby("customer_key", observed=True)
        .agg(
            customer_segment=("customer_segment", "first"),
            primary_market=("market", lambda s: s.mode().iat[0]),
            primary_country=("country", lambda s: s.mode().iat[0]),
            first_order_date=("order_date", "min"),
            last_order_date=("order_date", "max"),
            order_frequency=("order_key", "nunique"),
            total_lines=("n_lines", "sum"),
            total_quantity=("quantity", "sum"),
            lifetime_revenue=("order_value", "sum"),
            lifetime_cost=("cost", "sum"),
            lifetime_profit=("profit", "sum"),
            lifetime_discount=("discount_amount", "sum"),
            lifetime_shipping=("shipping_cost", "sum"),
            returned_orders=("return_flag", "sum"),
            measured_orders=("returns_measured", "sum"),
        )
        .reset_index()
    )

    # "Customer lifetime value" here is HISTORICAL realised value - the revenue
    # actually booked - not a predicted future value. Named to avoid overclaiming.
    cust["clv_historical_revenue"] = cust["lifetime_revenue"]
    cust["clv_historical_profit"] = cust["lifetime_profit"]

    cust["avg_order_value"] = cust["lifetime_revenue"] / cust["order_frequency"]
    cust["avg_order_profit"] = cust["lifetime_profit"] / cust["order_frequency"]
    cust["profit_margin_pct"] = np.where(
        cust["lifetime_revenue"] > 0,
        cust["lifetime_profit"] / cust["lifetime_revenue"] * 100.0, np.nan)

    cust["days_since_last_purchase"] = (snapshot - cust["last_order_date"]).dt.days
    cust["tenure_days_observed"] = (cust["last_order_date"] - cust["first_order_date"]).dt.days
    cust["is_repeat_customer"] = (cust["order_frequency"] > 1).astype("int8")

    # Return rate is only meaningful where returns were actually recorded.
    cust["return_rate_pct"] = np.where(
        cust["measured_orders"] > 0,
        cust["returned_orders"] / cust["measured_orders"] * 100.0, np.nan)

    # Purchase cadence: only defined for customers with more than one order.
    cust["avg_days_between_orders"] = np.where(
        cust["order_frequency"] > 1,
        cust["tenure_days_observed"] / (cust["order_frequency"] - 1), np.nan)

    cust["cohort_month"] = cust["first_order_date"].dt.to_period("M").astype("string")
    return cust


# ===========================================================================
# MONTHLY KPIs
# ===========================================================================
def build_monthly_kpis(lines: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    """Month-level KPI series with growth rates computed, not hardcoded."""
    monthly = (
        lines.groupby("order_ym", observed=True)
        .agg(
            revenue=("revenue", "sum"),
            cost=("cost", "sum"),
            profit=("profit", "sum"),
            discount_amount=("discount_amount", "sum"),
            shipping_cost=("shipping_cost", "sum"),
            quantity=("quantity", "sum"),
            lines=("order_line_id", "size"),
        )
        .reset_index()
        .sort_values("order_ym")
    )

    order_monthly = (
        orders.groupby("order_ym", observed=True)
        .agg(
            orders=("order_key", "nunique"),
            customers=("customer_key", "nunique"),
            returned_orders=("return_flag", "sum"),
            measured_orders=("returns_measured", "sum"),
        )
        .reset_index()
    )
    monthly = monthly.merge(order_monthly, on="order_ym", how="left")

    monthly["profit_margin_pct"] = monthly["profit"] / monthly["revenue"] * 100.0
    monthly["avg_order_value"] = monthly["revenue"] / monthly["orders"]
    monthly["return_rate_pct"] = np.where(
        monthly["measured_orders"] > 0,
        monthly["returned_orders"] / monthly["measured_orders"] * 100.0, np.nan)

    # Month-on-month and year-on-year growth. YoY uses a 12-month lag on an
    # unbroken monthly series - verified below before use.
    monthly["revenue_mom_pct"] = monthly["revenue"].pct_change() * 100.0
    monthly["revenue_yoy_pct"] = monthly["revenue"].pct_change(periods=12) * 100.0
    monthly["profit_mom_pct"] = monthly["profit"].pct_change() * 100.0
    monthly["profit_yoy_pct"] = monthly["profit"].pct_change(periods=12) * 100.0
    return monthly


# ===========================================================================
# MAIN
# ===========================================================================
def main() -> None:
    lines = load_clean()
    lines = add_line_metrics(lines)
    lines = add_date_parts(lines)

    snapshot = lines["order_date"].max()
    orders = build_order_table(lines)
    customers = build_customer_metrics(orders, snapshot)
    monthly = build_monthly_kpis(lines, orders)

    # The YoY column is only valid on a gapless monthly series.
    periods = pd.PeriodIndex(monthly["order_ym"], freq="M")
    expected = pd.period_range(periods.min(), periods.max(), freq="M")
    if len(periods) != len(expected) or not (periods.sort_values() == expected).all():
        raise AssertionError("monthly series has gaps; the 12-month YoY lag would be wrong")

    # Reconciliation: aggregation must not create or destroy money.
    assert abs(orders["order_value"].sum() - lines["revenue"].sum()) < 0.01
    assert abs(customers["lifetime_revenue"].sum() - lines["revenue"].sum()) < 0.01
    assert abs(monthly["revenue"].sum() - lines["revenue"].sum()) < 0.01
    assert orders["order_key"].is_unique
    assert customers["customer_key"].is_unique

    lines.to_csv(PROCESSED / "orders_features.csv", index=False, encoding="utf-8")
    orders.to_csv(PROCESSED / "orders_agg.csv", index=False, encoding="utf-8")
    customers.to_csv(PROCESSED / "customer_metrics.csv", index=False, encoding="utf-8")
    monthly.to_csv(PROCESSED / "monthly_kpis.csv", index=False, encoding="utf-8")

    print("FEATURE ENGINEERING COMPLETE")
    print(f"  snapshot date        : {snapshot.date()}")
    print(f"  order lines          : {len(lines):,} x {lines.shape[1]} cols")
    print(f"  orders               : {len(orders):,}")
    print(f"  customers            : {len(customers):,}")
    print(f"  months               : {len(monthly):,} "
          f"({monthly['order_ym'].iat[0]} to {monthly['order_ym'].iat[-1]})")
    print()
    print(f"  total revenue        : {lines['revenue'].sum():,.2f}")
    print(f"  total cost           : {lines['cost'].sum():,.2f}")
    print(f"  total profit         : {lines['profit'].sum():,.2f}")
    print(f"  profit margin        : {lines['profit'].sum() / lines['revenue'].sum():.2%}")
    print(f"  total list revenue   : {lines['list_revenue'].sum():,.2f}")
    print(f"  total discount given : {lines['discount_amount'].sum():,.2f}"
          f"  ({lines['discount_amount'].sum() / lines['list_revenue'].sum():.2%} of list)")
    print(f"  total shipping cost  : {lines['shipping_cost'].sum():,.2f}"
          f"  ({lines['shipping_cost'].sum() / lines['revenue'].sum():.2%} of revenue)")
    print(f"  avg order value      : {orders['order_value'].mean():,.2f}")
    print(f"  repeat customer rate : {customers['is_repeat_customer'].mean():.2%}")
    print(f"  loss-making lines    : {lines['is_loss_making'].sum():,} "
          f"({lines['is_loss_making'].mean():.2%})")


if __name__ == "__main__":
    main()
