"""
E-COMMERCE ANALYTICS  |  RFM SEGMENTATION & COHORT RETENTION
============================================================

INPUT   data/processed/customer_metrics.csv
        data/processed/orders_agg.csv
OUTPUT  data/processed/rfm_segments.csv     customer-level RFM scores + segment
        data/processed/cohort_retention.csv cohort x period retention matrix
        data/processed/cohort_counts.csv    the same matrix as raw headcounts
        reports/segmentation_facts.json     machine-readable facts

READ THIS BEFORE TRUSTING ANY SEGMENT LABEL
-------------------------------------------
Global Superstore is not an acquisition funnel. It is a CLOSED PANEL of 795
customers observed for 48 months, and that changes what these labels mean:

  * Every customer ordered at least 15 times (median 32, max 47). There are
    ZERO one-time customers, so "repeat purchase rate" is 100% by construction
    and carries no information.
  * All 795 customers placed their first order during 2011. Not one new
    customer appears in 2012, 2013 or 2014, so "new vs returning" is
    degenerate outside year one and the "New Customers" RFM segment is
    necessarily empty.
  * Median dormancy at the snapshot is 16 days and only ONE customer has been
    inactive for more than 180 days. "Lost" in this dataset therefore means
    tens of days, not the quarters or years the label normally implies.

RFM quintiles are relative by construction, so scoring still separates the base
cleanly - but a segment name is a position within THIS panel, not a claim about
real-world churn. Every label below is emitted alongside the actual recency,
frequency and monetary ranges that produced it, and `report_degeneracy()`
quantifies exactly which spec metrics are uninformative here. Naming a segment
"Lost" without that context would be the single most misleading thing this
project could do.

Run: python src/rfm_analysis.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)

QUINTILES = 5

# A customer is "new" if their FIRST purchase is recent - that is the only
# defensible definition. Using low relative frequency as a proxy for "new" (a
# common shortcut) would label 91 customers here as new when every one of them
# was acquired in 2011 and has placed 17-31 orders since. On this closed panel
# the rule therefore correctly matches nobody.
NEW_CUSTOMER_MAX_TENURE_DAYS = 90


# ===========================================================================
# RFM SCORING
# ===========================================================================
def score_rfm(customers: pd.DataFrame) -> pd.DataFrame:
    """Quintile RFM scores.

    Recency is inverted: fewer days since the last purchase is better, so the
    most recent quintile scores 5. Frequency and monetary score 5 at the top.
    `rank(method="first")` breaks ties deterministically - without it qcut can
    fail on the ties that a narrow distribution like this produces.
    """
    df = customers.copy()

    df["r_score"] = pd.qcut(
        df["days_since_last_purchase"].rank(method="first", ascending=True),
        QUINTILES, labels=[5, 4, 3, 2, 1]).astype(int)
    df["f_score"] = pd.qcut(
        df["order_frequency"].rank(method="first", ascending=True),
        QUINTILES, labels=[1, 2, 3, 4, 5]).astype(int)
    df["m_score"] = pd.qcut(
        df["lifetime_revenue"].rank(method="first", ascending=True),
        QUINTILES, labels=[1, 2, 3, 4, 5]).astype(int)

    df["rfm_cell"] = (df["r_score"].astype(str) + df["f_score"].astype(str)
                      + df["m_score"].astype(str))
    df["rfm_sum"] = df["r_score"] + df["f_score"] + df["m_score"]
    # Frequency and monetary together describe "value"; recency describes
    # "engagement". The standard 2-axis reading of RFM.
    df["fm_score"] = (df["f_score"] + df["m_score"]) / 2.0
    return df


def assign_segment(row: pd.Series) -> str:
    """Map an (R, FM) position to the segment names the brief asks for.

    "New Customers" is gated on ACQUISITION recency, not on low frequency. That
    distinction matters: on this panel a frequency-based rule labels 91
    long-standing customers (17-31 orders each, all acquired in 2011) as "new",
    which is simply false. Tenure-gating makes the rule return zero here, which
    is the truth. The rule is retained rather than deleted so the taxonomy still
    matches the brief and the empty result is visible.
    """
    r, fm, f = row["r_score"], row["fm_score"], row["f_score"]
    tenure = row["days_since_first_purchase"]

    if tenure <= NEW_CUSTOMER_MAX_TENURE_DAYS:
        return "New Customers"
    if r >= 4 and fm >= 4:
        return "Champions"
    if r >= 3 and fm >= 3:
        return "Loyal Customers"
    if r >= 3 and fm < 3:
        return "Potential Loyalists"
    if r == 2:
        return "At Risk"
    return "Lost Customers"


SEGMENT_ORDER = [
    "Champions",
    "Loyal Customers",
    "Potential Loyalists",
    "New Customers",
    "At Risk",
    "Lost Customers",
]

# Action per segment. Written as business instructions, not restatements of the
# score, because a segment with no recommendation attached is decoration.
SEGMENT_ACTIONS = {
    "Champions": (
        "Protect. Highest value and most recently active. Give early access to new "
        "ranges and priority fulfilment; do NOT spend discount here - they already "
        "buy at the best margins."),
    "Loyal Customers": (
        "Grow basket size. Consistent buyers with room to move up. Cross-sell "
        "adjacent sub-categories and bundle the low-margin items they already buy."),
    "Potential Loyalists": (
        "Convert to loyal. Recently active but spending below their cohort. Targeted "
        "category offers and a second-order incentive are justified here."),
    "New Customers": (
        "Onboard. Recent first purchases with shallow history - focus on the second "
        "order, which is the strongest predictor of long-term value."),
    "At Risk": (
        "Reactivate now. Previously valuable, engagement slipping. Time-boxed "
        "win-back offer plus a service check - review whether returns or late "
        "shipments preceded the drop-off."),
    "Lost Customers": (
        "Reactivate cheaply or release. Longest dormancy in the panel. Use low-cost "
        "channels only; do not fund deep discounts to chase them."),
}

# Carried into rfm_segments.csv so the caveat travels with the data. A segment
# name lifted out of this file and pasted into a slide is exactly how a relative
# quintile label turns into a false claim about churn.
SEGMENT_CAVEATS = {
    "Champions": "Relative label: top recency and value quintiles within this 795-customer panel.",
    "Loyal Customers": "Relative label: upper-middle recency and value within this panel.",
    "Potential Loyalists": (
        "Relative label: recent but below-panel-average value. Not 'new' - see New Customers."),
    "New Customers": (
        f"Requires first purchase within {NEW_CUSTOMER_MAX_TENURE_DAYS} days of the snapshot. "
        "Every customer here was acquired in 2011, so this segment is legitimately EMPTY."),
    "At Risk": (
        "Relative label. Median dormancy is only ~28 days; this is the second-lowest "
        "recency quintile of a highly active panel, NOT evidence of churn."),
    "Lost Customers": (
        "Relative label, and the most easily misread. Dormancy runs 36-428 days with a "
        "median near 49 - only 1 customer in the whole panel exceeds 180 days. These "
        "customers are not lost in any real sense; they are simply the least recent quintile."),
}


def build_segments(customers: pd.DataFrame) -> pd.DataFrame:
    df = score_rfm(customers)

    # Tenure at the snapshot. The snapshot is the last order date observed
    # anywhere in the panel, not today - see feature_engineering's note on recency.
    snapshot = customers["last_order_date"].max()
    df["days_since_first_purchase"] = (snapshot - df["first_order_date"]).dt.days

    df["segment"] = df.apply(assign_segment, axis=1)
    df["segment_action"] = df["segment"].map(SEGMENT_ACTIONS)
    df["label_caveat"] = df["segment"].map(SEGMENT_CAVEATS)
    return df


def summarise_segments(rfm: pd.DataFrame) -> pd.DataFrame:
    """Segment profile with the ACTUAL R/F/M ranges behind each label."""
    summary = (
        rfm.groupby("segment", observed=True)
        .agg(
            customers=("customer_key", "nunique"),
            revenue=("lifetime_revenue", "sum"),
            profit=("lifetime_profit", "sum"),
            avg_revenue=("lifetime_revenue", "mean"),
            avg_orders=("order_frequency", "mean"),
            avg_aov=("avg_order_value", "mean"),
            recency_min=("days_since_last_purchase", "min"),
            recency_median=("days_since_last_purchase", "median"),
            recency_max=("days_since_last_purchase", "max"),
            freq_min=("order_frequency", "min"),
            freq_max=("order_frequency", "max"),
            monetary_min=("lifetime_revenue", "min"),
            monetary_max=("lifetime_revenue", "max"),
            unprofitable=("lifetime_profit", lambda s: int((s < 0).sum())),
        )
        .reindex(SEGMENT_ORDER)
    )
    summary["customers"] = summary["customers"].fillna(0).astype(int)
    summary["pct_customers"] = summary["customers"] / summary["customers"].sum() * 100
    summary["pct_revenue"] = summary["revenue"] / summary["revenue"].sum() * 100
    summary["margin_pct"] = summary["profit"] / summary["revenue"] * 100
    summary["action"] = [SEGMENT_ACTIONS[s] for s in summary.index]
    summary["label_caveat"] = [SEGMENT_CAVEATS[s] for s in summary.index]
    return summary.reset_index()


# ===========================================================================
# COHORT RETENTION
# ===========================================================================
def build_cohorts(orders: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Monthly acquisition cohorts and their retention curves.

    period_index is whole months elapsed since the customer's first order, so
    period 0 is the acquisition month and retention there is 100% by definition.
    """
    df = orders.copy()
    df["order_period"] = df["order_date"].dt.to_period("M")
    first = df.groupby("customer_key")["order_period"].min().rename("cohort")
    df = df.join(first, on="customer_key")
    df["period_index"] = (
        (df["order_period"].dt.year - df["cohort"].dt.year) * 12
        + (df["order_period"].dt.month - df["cohort"].dt.month)
    )

    counts = (
        df.groupby(["cohort", "period_index"])["customer_key"].nunique()
        .unstack(fill_value=0).sort_index()
    )
    counts.index = counts.index.astype(str)

    size = counts[0].replace(0, np.nan)
    retention = counts.div(size, axis=0) * 100.0
    return retention.round(2), counts


# ===========================================================================
# DEGENERACY REPORT
# ===========================================================================
def report_degeneracy(customers: pd.DataFrame, rfm: pd.DataFrame) -> dict:
    """Quantify which spec-requested customer metrics are uninformative here.

    Every entry is a metric the brief asks for that this dataset cannot make
    meaningful. Surfacing them as numbers keeps the README honest instead of
    quietly shipping a flat chart.
    """
    one_time = int((customers["order_frequency"] == 1).sum())
    cohort_years = customers["first_order_date"].dt.year
    facts = {
        "customers": int(len(customers)),
        "one_time_customers": one_time,
        "repeat_purchase_rate_pct": float(
            (customers["order_frequency"] > 1).mean() * 100),
        "min_order_frequency": int(customers["order_frequency"].min()),
        "median_order_frequency": float(customers["order_frequency"].median()),
        "max_order_frequency": int(customers["order_frequency"].max()),
        "acquisition_years": {int(y): int(n) for y, n in cohort_years.value_counts().items()},
        "customers_acquired_after_2011": int((cohort_years > 2011).sum()),
        "distinct_cohort_months": int(customers["cohort_month"].nunique()),
        "median_days_since_last_purchase": float(
            customers["days_since_last_purchase"].median()),
        "customers_dormant_over_180d": int(
            (customers["days_since_last_purchase"] > 180).sum()),
        "top10pct_revenue_share": float(
            customers["lifetime_revenue"].nlargest(max(1, int(len(customers) * 0.10))).sum()
            / customers["lifetime_revenue"].sum() * 100),
        "top20pct_revenue_share": float(
            customers["lifetime_revenue"].nlargest(max(1, int(len(customers) * 0.20))).sum()
            / customers["lifetime_revenue"].sum() * 100),
        "unprofitable_customers": int((customers["lifetime_profit"] < 0).sum()),
        "empty_segments": [s for s in SEGMENT_ORDER
                           if int((rfm["segment"] == s).sum()) == 0],
        "segment_counts": {s: int((rfm["segment"] == s).sum()) for s in SEGMENT_ORDER},
    }
    facts["degenerate_metrics"] = {
        "repeat_purchase_rate": (
            f"100% - all {facts['customers']} customers ordered at least "
            f"{facts['min_order_frequency']} times. No variation to analyse."),
        "one_time_customers": (
            f"{one_time} exist. The spec's one-time vs repeat split cannot be drawn."),
        "new_vs_returning": (
            f"{facts['customers_acquired_after_2011']} customers acquired after 2011. "
            "From 2012 onward the base is 100% returning, 0% new."),
        "pareto_80_20": (
            f"Top 20% of customers hold {facts['top20pct_revenue_share']:.1f}% of revenue, "
            "not ~80%. Revenue is close to evenly spread, so 'focus on the top 20%' is "
            "not supported by this data."),
        "churn_and_lost": (
            f"Only {facts['customers_dormant_over_180d']} customer(s) dormant beyond 180 days "
            f"(median {facts['median_days_since_last_purchase']:.0f} days). Churn analysis has "
            "almost no signal; 'Lost' is a relative label, not real attrition."),
    }
    return facts


# ===========================================================================
# MAIN
# ===========================================================================
def main() -> None:
    customers = pd.read_csv(
        PROCESSED / "customer_metrics.csv",
        parse_dates=["first_order_date", "last_order_date"], encoding="utf-8")
    orders = pd.read_csv(
        PROCESSED / "orders_agg.csv", parse_dates=["order_date"], encoding="utf-8")

    rfm = build_segments(customers)
    summary = summarise_segments(rfm)
    retention, counts = build_cohorts(orders)
    facts = report_degeneracy(customers, rfm)

    # Sanity: scoring must not lose or duplicate customers.
    assert len(rfm) == len(customers), "RFM scoring changed the customer count"
    assert rfm["customer_key"].is_unique
    assert int(summary["customers"].sum()) == len(customers), "segments must partition the base"
    assert (retention[0].dropna().round(0) == 100).all(), "period 0 retention must be 100%"

    rfm.to_csv(PROCESSED / "rfm_segments.csv", index=False, encoding="utf-8")
    summary.to_csv(PROCESSED / "rfm_segment_summary.csv", index=False, encoding="utf-8")
    retention.to_csv(PROCESSED / "cohort_retention.csv", encoding="utf-8")
    counts.to_csv(PROCESSED / "cohort_counts.csv", encoding="utf-8")
    (REPORTS / "segmentation_facts.json").write_text(
        json.dumps(facts, indent=2, default=str), encoding="utf-8")

    print("RFM SEGMENTATION")
    print("=" * 74)
    cols = ["segment", "customers", "pct_customers", "pct_revenue", "avg_revenue",
            "avg_orders", "recency_median", "margin_pct"]
    print(summary[cols].to_string(index=False, float_format=lambda v: f"{v:,.1f}"))

    print("\nACTUAL RANGES BEHIND EACH LABEL")
    print("=" * 74)
    for _, r in summary.iterrows():
        if r["customers"] == 0:
            print(f"  {r['segment']:<22} EMPTY - no customer matched this rule")
            continue
        print(f"  {r['segment']:<22} recency {r['recency_min']:.0f}-{r['recency_max']:.0f}d | "
              f"orders {r['freq_min']:.0f}-{r['freq_max']:.0f} | "
              f"revenue {r['monetary_min']:,.0f}-{r['monetary_max']:,.0f}")

    print("\nCOHORT RETENTION (%)  first 8 cohorts x first 13 periods")
    print("=" * 74)
    print(retention.iloc[:8, :13].to_string(float_format=lambda v: f"{v:5.1f}"))

    print("\nDEGENERATE METRICS - reported, not hidden")
    print("=" * 74)
    for k, v in facts["degenerate_metrics"].items():
        print(f"  {k}:\n      {v}")

    print(f"\nempty segments: {facts['empty_segments'] or 'none'}")
    print(f"wrote rfm_segments.csv, rfm_segment_summary.csv, cohort_retention.csv, "
          f"cohort_counts.csv")
    print(f"wrote reports/segmentation_facts.json")


if __name__ == "__main__":
    main()
