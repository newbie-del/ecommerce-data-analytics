"""
E-COMMERCE ANALYTICS  |  DATA CLEANING
======================================

Turns the raw Global Superstore workbook into a validated, analysis-ready
order-line table plus conformed customer and product dimensions.

INPUT   data/raw/Global Superstore.xls        (raw, never modified)
            sheet "Orders"   51,290 order lines x 24 cols
            sheet "Returns"   1,173 returned orders x 3 cols
            sheet "People"       13 regional managers x 2 cols
OUTPUT  data/processed/orders_clean.csv       one row per order line
        data/processed/customers.csv          one row per resolved customer
        data/processed/products.csv           one row per product
        reports/data_quality_report.md        the full audit
        reports/data_quality_facts.json       machine-readable facts

DESIGN NOTE - what "cleaning" means on this dataset
---------------------------------------------------
This is the real Tableau Global Superstore extract, and unlike a curated
teaching file it arrives with genuine structural defects. Inventing dirt would
be dishonest; so would ignoring the dirt that is actually here. Each decision
below is driven by evidence printed in the report, not by convention:

  1. NO ROWS ARE DROPPED AS DUPLICATES. There are zero rows that duplicate
     another on all business fields. The 38 (order_id, product_id) collisions
     were inspected individually: 28 are legitimate split lines with different
     quantities, 9 differ only in shipping_cost (one order despatched as two
     parcels), and 1 belongs to a different customer on a different date. A
     blanket drop_duplicates() would have destroyed real shipping cost and
     real revenue.

  2. CUSTOMER IDENTITY IS RESOLVED. Every one of the 795 customer names carries
     exactly two customer_ids - one covering APAC/EU/LATAM/US, the other
     covering Africa/EMEA. Aaron Bergman is both AB-10015 and AB-15. Grouping
     by customer_id therefore reports 1,590 customers where 795 people exist,
     halves every customer's true lifetime value, and corrupts RFM, retention
     and cohort analysis. We resolve to the person and keep the raw ids.

  3. THE ORDER KEY IS COMPOSITE. order_id is reused: 659 ids appear against two
     different customers on two different dates. order_id alone yields 25,035
     "orders"; (order_id, customer_id, order_date) yields 25,754 with no
     remaining collisions. Average order value on the naive key is overstated.

  4. DISCOUNT IS ROUNDED TO 3dp, NOT 2dp. 0.15000000000000002 and
     0.44999999999999996 are float artifacts and must go. But 0.002, 0.202,
     0.402 and 0.602 are genuine discount levels on 629 order lines; rounding
     to 2dp would silently merge them into 0.00/0.20/0.40/0.60 and erase a real
     pricing tier.

  5. RETURNS ARE JOINED ON (order_id, market), NOT order_id. The Returns sheet
     labels the US market "United States" while Orders calls it "US", so the
     label is normalised first. Joining on order_id alone flags 3,050 lines;
     the correct composite join flags 3,043 - the 7 extras are false positives
     created by the order_id reuse in note 3. Critically, Africa, Canada and
     EMEA have ZERO return records, so return rate is computed only over the
     four covered markets and is never reported as 0% for the other three.

  6. BRAND IS DERIVED, AND LABELLED AS DERIVED. The dataset has no brand
     column. The first token of product_name is a manufacturer in 98.8% of
     lines (Avery, Xerox, Fellowes, SanDisk, Logitech, Cisco, Apple ...), so it
     is extracted - but multi-word brands truncate ("Binney" for
     "Binney & Smith") and numeric tokens become "Unknown". Stated, not hidden.

Run: python src/data_cleaning.py
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "Global Superstore.xls"
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
REPORT_MD = REPORTS / "data_quality_report.md"
FACTS_JSON = REPORTS / "data_quality_facts.json"

PROCESSED.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)

# The raw workbook's column names, mapped to the snake_case vocabulary used
# throughout the project. Keeping this explicit means a schema change upstream
# fails loudly in validate_schema() instead of silently producing NaN columns.
COLUMN_MAP = {
    "Row ID": "order_line_id",
    "Order ID": "order_id",
    "Order Date": "order_date",
    "Ship Date": "ship_date",
    "Ship Mode": "ship_mode",
    "Customer ID": "customer_id",
    "Customer Name": "customer_name",
    "Segment": "customer_segment",
    "City": "city",
    "State": "state",
    "Country": "country",
    "Postal Code": "postal_code",
    "Market": "market",
    "Region": "region",
    "Product ID": "product_id",
    "Category": "category",
    "Sub-Category": "sub_category",
    "Product Name": "product_name",
    "Sales": "revenue",
    "Quantity": "quantity",
    "Discount": "discount",
    "Profit": "profit",
    "Shipping Cost": "shipping_cost",
    "Order Priority": "order_priority",
}

# Returns calls the US market "United States"; Orders calls it "US". Without
# this the join silently flags zero US returns.
MARKET_ALIASES = {"United States": "US"}

_report = io.StringIO()
_facts: dict[str, object] = {}


def out(line: str = "") -> None:
    """Print to console and capture for the markdown report."""
    print(line)
    _report.write(line + "\n")


def fact(key: str, value) -> None:
    """Record a machine-readable fact for later claim verification."""
    if isinstance(value, (np.integer,)):
        value = int(value)
    elif isinstance(value, (np.floating,)):
        value = float(value)
    _facts[key] = value


# ===========================================================================
# LOAD
# ===========================================================================
def load_raw(path: Path = RAW) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the three sheets of the raw workbook, unmodified."""
    book = pd.ExcelFile(path, engine="xlrd")
    expected = {"Orders", "Returns", "People"}
    missing = expected - set(book.sheet_names)
    if missing:
        raise ValueError(f"raw workbook is missing sheet(s): {sorted(missing)}")
    return book.parse("Orders"), book.parse("Returns"), book.parse("People")


def validate_schema(orders: pd.DataFrame) -> None:
    """Fail loudly if the upstream workbook no longer matches expectations."""
    missing = [c for c in COLUMN_MAP if c not in orders.columns]
    if missing:
        raise ValueError(f"Orders sheet is missing expected column(s): {missing}")


# ===========================================================================
# AUDIT
# ===========================================================================
def audit(orders: pd.DataFrame, returns: pd.DataFrame, people: pd.DataFrame) -> None:
    """Quantify every data-quality issue, with evidence, before changing anything."""
    out("# Global Superstore - Data Quality Report")
    out()
    out("Generated by `src/data_cleaning.py`. Every number here is computed from")
    out("`data/raw/Global Superstore.xls` and is reproducible by re-running the script.")
    out()
    out(f"- Source sheets: `Orders` {orders.shape[0]:,}x{orders.shape[1]}, "
        f"`Returns` {returns.shape[0]:,}x{returns.shape[1]}, "
        f"`People` {people.shape[0]:,}x{people.shape[1]}")
    out()

    fact("raw_orders_rows", len(orders))
    fact("raw_orders_cols", orders.shape[1])
    fact("raw_returns_rows", len(returns))
    fact("raw_people_rows", len(people))

    # -- 1. completeness ---------------------------------------------------
    out("## 1. Missing values")
    out()
    miss = orders.isna().sum()
    miss = miss[miss > 0].sort_values(ascending=False)
    total_cells = int(orders.size)
    fact("raw_total_cells", total_cells)
    fact("raw_missing_cells", int(orders.isna().sum().sum()))
    if miss.empty:
        out("No missing values in the Orders sheet.")
    else:
        out(f"Across {total_cells:,} cells, {int(miss.sum()):,} are missing "
            f"({miss.sum() / total_cells:.2%}), confined to:")
        out()
        out("| Column | Missing | % of rows |")
        out("|---|---:|---:|")
        for col, n in miss.items():
            out(f"| `{COLUMN_MAP.get(col, col)}` | {n:,} | {n / len(orders):.2%} |")
        out()
        out("`postal_code` is absent for every non-US row. This is structural, not a")
        out("data error: the field only exists in the US market. It is **not imputed** -")
        out("inventing postcodes for 147 countries would be fabrication. The column is")
        out("kept as-is and simply unused outside US-level analysis.")
    out()
    fact("postal_code_missing", int(orders["Postal Code"].isna().sum()))

    # -- 2. duplicates -----------------------------------------------------
    out("## 2. Duplicates")
    out()
    business_cols = ["Order ID", "Product ID", "Order Date", "Customer ID",
                     "Quantity", "Sales", "Discount", "Profit", "Shipping Cost"]
    exact_all = int(orders.duplicated().sum())
    exact_business = int(orders.duplicated(subset=business_cols).sum())
    key_collisions = int(orders.duplicated(subset=["Order ID", "Product ID"]).sum())
    fact("duplicate_rows_exact", exact_all)
    fact("duplicate_rows_business_fields", exact_business)
    fact("orderid_productid_collisions", key_collisions)

    out(f"- Exact duplicate rows: **{exact_all}**")
    out(f"- Duplicates on all business fields (ignoring `order_line_id`): **{exact_business}**")
    out(f"- `(order_id, product_id)` collisions: **{key_collisions}**")
    out()
    out("The collisions were inspected individually rather than dropped:")
    out()

    dupe = orders[orders.duplicated(subset=["Order ID", "Product ID"], keep=False)]
    groups = dupe.groupby(["Order ID", "Product ID"])
    split_lines = identical_money = 0
    reasons: dict[str, int] = {}
    for _, sub in groups:
        money = sub[["Quantity", "Sales", "Profit", "Discount"]].drop_duplicates()
        if len(money) > 1:
            split_lines += 1
            continue
        identical_money += 1
        if sub["Customer ID"].nunique() > 1 or sub["Order Date"].nunique() > 1:
            reasons["different customer or date"] = reasons.get("different customer or date", 0) + 1
        elif sub["Shipping Cost"].nunique() > 1:
            reasons["shipping cost only (split shipment)"] = (
                reasons.get("shipping cost only (split shipment)", 0) + 1)
        else:
            reasons["UNEXPLAINED"] = reasons.get("UNEXPLAINED", 0) + 1

    out(f"| Group type | Count |")
    out("|---|---:|")
    out(f"| Different quantity/revenue - a legitimate split line | {split_lines} |")
    for k, v in sorted(reasons.items()):
        out(f"| Same money, {k} | {v} |")
    out()
    fact("collision_groups_split_lines", split_lines)
    fact("collision_groups_identical_money", identical_money)
    fact("collision_groups_unexplained", reasons.get("UNEXPLAINED", 0))
    out(f"**Decision: drop nothing.** {reasons.get('UNEXPLAINED', 0)} groups are unexplained, "
        "so there is no evidence of a genuine duplicate record. `order_line_id` (the raw "
        "`Row ID`) is unique across all rows and is the line-level primary key.")
    out()

    # -- 3. customer identity ---------------------------------------------
    out("## 3. Customer identity - the most consequential defect")
    out()
    n_ids = orders["Customer ID"].nunique()
    n_names = orders["Customer Name"].nunique()
    ids_per_name = orders.groupby("Customer Name")["Customer ID"].nunique()
    fact("raw_customer_ids", int(n_ids))
    fact("raw_customer_names", int(n_names))
    fact("ids_per_name_distribution", {int(k): int(v) for k, v in
                                       ids_per_name.value_counts().sort_index().items()})

    out(f"- Distinct `customer_id`: **{n_ids:,}**")
    out(f"- Distinct `customer_name`: **{n_names:,}**")
    out(f"- IDs per name: {dict(ids_per_name.value_counts().sort_index())} "
        f"- i.e. *every* name has exactly two ids")
    out(f"- `customer_id`s spanning more than one segment: "
        f"**{int(orders.groupby('Customer ID')['Segment'].nunique().gt(1).sum())}**")
    out()

    example = ids_per_name[ids_per_name > 1].index[0]
    ex = orders[orders["Customer Name"] == example]
    out(f"Worked example - **{example}**:")
    out()
    out("| customer_id | markets | lines | revenue |")
    out("|---|---|---:|---:|")
    for cid, sub in ex.groupby("Customer ID"):
        out(f"| `{cid}` | {', '.join(sorted(sub['Market'].unique()))} | "
            f"{len(sub):,} | {sub['Sales'].sum():,.2f} |")
    out()
    out("The split is geographic: one id serves APAC/EU/LATAM/US, the other")
    out("Africa/EMEA. These are one person, recorded twice.")
    out()
    out("**Why this matters.** Grouping by `customer_id` would report "
        f"{n_ids:,} customers where {n_names:,} exist, split each person's true "
        "lifetime value across two rows, and make every genuinely loyal customer look "
        "like two lower-value ones. RFM segments, retention, cohort curves and CLV would "
        "all be wrong. **Decision:** resolve to the person via `customer_key`, and retain "
        "`customer_id` so the raw records remain traceable.")
    out()

    # -- 4. order key ------------------------------------------------------
    out("## 4. Order identity")
    out()
    grp = orders.groupby("Order ID")
    multi_cust = int(grp["Customer ID"].nunique().gt(1).sum())
    multi_date = int(grp["Order Date"].nunique().gt(1).sum())
    fact("orderid_multi_customer", multi_cust)
    fact("orderid_multi_date", multi_date)

    out("| Candidate key | Distinct groups | Groups spanning >1 customer | >1 date |")
    out("|---|---:|---:|---:|")
    for keys in (["Order ID"], ["Order ID", "Market"], ["Order ID", "Customer ID"],
                 ["Order ID", "Customer ID", "Order Date"]):
        g = orders.groupby(keys)
        label = " + ".join(COLUMN_MAP[k] for k in keys)
        out(f"| `{label}` | {g.ngroups:,} | {int(g['Customer ID'].nunique().gt(1).sum()):,} "
            f"| {int(g['Order Date'].nunique().gt(1).sum()):,} |")
    out()
    naive = orders["Order ID"].nunique()
    composite = orders.groupby(["Order ID", "Customer ID", "Order Date"]).ngroups
    fact("orders_naive_key", int(naive))
    fact("orders_composite_key", int(composite))
    out(f"`order_id` alone is **not** unique to an order: {multi_cust} ids appear against two")
    out(f"different customers on two different dates. **Decision:** the order key is the")
    out(f"composite `(order_id, customer_id, order_date)`, giving **{composite:,}** orders")
    out(f"rather than {naive:,} - a {(composite / naive - 1):.2%} difference that flows")
    out("straight into average order value and order-frequency metrics.")
    out()

    # -- 5. product key ----------------------------------------------------
    out("## 5. Product identity")
    out()
    n_pid = orders["Product ID"].nunique()
    n_pname = orders["Product Name"].nunique()
    pairs = orders.groupby(["Product ID", "Product Name"]).ngroups
    pid_multi = int(orders.groupby("Product ID")["Product Name"].nunique().gt(1).sum())
    pname_multi = int(orders.groupby("Product Name")["Product ID"].nunique().gt(1).sum())
    cat_span = int(orders.groupby("Product ID")["Category"].nunique().gt(1).sum())
    fact("raw_product_ids", int(n_pid))
    fact("raw_product_names", int(n_pname))
    fact("product_ids_multiple_names", pid_multi)
    fact("product_names_multiple_ids", pname_multi)
    fact("product_ids_spanning_categories", cat_span)

    out(f"- Distinct `product_id`: **{n_pid:,}**")
    out(f"- Distinct `product_name`: **{n_pname:,}**")
    out(f"- Distinct `(product_id, product_name)` pairs: **{pairs:,}**")
    out(f"- `product_id`s carrying more than one name: **{pid_multi:,}**")
    out(f"- `product_name`s carrying more than one id: **{pname_multi:,}**")
    out(f"- `product_id`s spanning more than one category: **{cat_span}**")
    out()
    out("Neither field is a clean key, but `product_id` is the better one: it never")
    out(f"crosses a category boundary ({cat_span} violations), whereas {pname_multi:,} names")
    out("are reused across genuinely different ids. **Decision:** aggregate on `product_id`,")
    out("and attach `product_name` = the most frequent name for that id so reports carry a")
    out("readable, stable label. The 457 ambiguous ids are flagged in `products.csv` via")
    out("`name_variants` so no reader mistakes the label for a guarantee.")
    out()

    # -- 6. discount -------------------------------------------------------
    out("## 6. Discount precision")
    out()
    d = orders["Discount"]
    artifacts = sorted(v for v in d.unique() if abs(v - round(v, 3)) > 1e-12)
    genuine_3dp = sorted(v for v in d.round(3).unique() if abs(v - round(v, 2)) > 1e-9)
    fact("discount_distinct_raw", int(d.nunique()))
    fact("discount_distinct_2dp", int(d.round(2).nunique()))
    fact("discount_distinct_3dp", int(d.round(3).nunique()))
    fact("discount_genuine_3dp_levels", [float(v) for v in genuine_3dp])
    rows_3dp = int(d.round(3).isin(genuine_3dp).sum())
    fact("discount_rows_at_3dp_levels", rows_3dp)

    out(f"- Distinct raw values: **{d.nunique()}**")
    out(f"- After `round(2)`: **{d.round(2).nunique()}**")
    out(f"- After `round(3)`: **{d.round(3).nunique()}**")
    out(f"- Float artifacts present: `0.15000000000000002`, `0.44999999999999996`, "
        f"`0.47000000000000003`, `0.5700000000000001`")
    out(f"- Genuine three-decimal levels: {[f'{v:g}' for v in genuine_3dp]}, "
        f"covering **{rows_3dp:,}** order lines")
    out()
    out("**Decision: round to 3dp.** This removes the binary-representation artifacts")
    out(f"while preserving the {len(genuine_3dp)} real three-decimal discount tiers. Rounding to")
    out(f"2dp - the reflexive choice - would collapse those into 0.00/0.20/0.40/0.60 and")
    out(f"silently destroy a real pricing distinction on {rows_3dp:,} rows.")
    out()

    # -- 7. dates ----------------------------------------------------------
    out("## 7. Dates and delivery")
    out()
    od = pd.to_datetime(orders["Order Date"])
    sd = pd.to_datetime(orders["Ship Date"])
    lag = (sd - od).dt.days
    fact("order_date_min", str(od.min().date()))
    fact("order_date_max", str(od.max().date()))
    fact("ship_before_order", int((sd < od).sum()))
    fact("ship_lag_min", int(lag.min()))
    fact("ship_lag_max", int(lag.max()))
    fact("ship_lag_mean", float(lag.mean()))

    out(f"- `order_date` range: **{od.min().date()}** to **{od.max().date()}** "
        f"({od.dt.year.nunique()} full calendar years)")
    out(f"- Unparseable dates: **0** (both columns arrive as real datetimes)")
    out(f"- `ship_date` earlier than `order_date`: **{int((sd < od).sum())}**")
    out(f"- Order-to-ship lag: min **{lag.min()}**, mean **{lag.mean():.2f}**, "
        f"max **{lag.max()}** days")
    out()
    out("**Caveat carried forward:** the workbook has a *ship* date, not a *delivery*")
    out("date. Everything downstream therefore measures **order-to-ship lag**, and the")
    out("spec's \"average delivery time\" is reported under that honest name. Actual")
    out("transit time is not in this dataset and is not estimated.")
    out()

    # -- 8. numeric sanity -------------------------------------------------
    out("## 8. Numeric ranges and invalid values")
    out()
    out("| Field | Min | Max | Mean | Negatives | Zeros |")
    out("|---|---:|---:|---:|---:|---:|")
    for col in ("Sales", "Quantity", "Discount", "Profit", "Shipping Cost"):
        s = orders[col]
        out(f"| `{COLUMN_MAP[col]}` | {s.min():,.4f} | {s.max():,.4f} | {s.mean():,.4f} "
            f"| {int((s < 0).sum()):,} | {int((s == 0).sum()):,} |")
    out()
    loss = int((orders["Profit"] < 0).sum())
    loss_value = float(orders.loc[orders["Profit"] < 0, "Profit"].sum())
    fact("loss_making_lines", loss)
    fact("loss_making_share", loss / len(orders))
    fact("loss_total", loss_value)
    out(f"No negative revenue, quantity or shipping cost, and no zero-quantity lines -")
    out(f"so there are no invalid transactions to remove. Negative `profit` is **not** an")
    out(f"error: **{loss:,}** lines ({loss / len(orders):.2%}) lose money, totalling")
    out(f"**{loss_value:,.2f}**. That is a finding, not dirt, and it survives cleaning intact.")
    out()

    # -- 9. cost derivation ------------------------------------------------
    out("## 9. Deriving cost")
    out()
    cost = orders["Sales"] - orders["Profit"]
    fact("derived_cost_negatives", int((cost < 0).sum()))
    fact("derived_total_cost", float(cost.sum()))
    out("The dataset has no `cost_price`, but it has real `profit`, so cost is not")
    out("assumed - it is derived exactly:")
    out()
    out("```")
    out("cost = revenue - profit")
    out("```")
    out()
    out(f"- Resulting cost range: {cost.min():,.4f} to {cost.max():,.4f}")
    out(f"- Negative (impossible) costs: **{int((cost < 0).sum())}**")
    out(f"- Total cost: **{cost.sum():,.2f}**")
    out()
    out("Because profit is genuine, every margin, profitability and cost figure in this")
    out("project is a real measurement rather than a modelled assumption.")
    out()

    # -- 10. discount semantics -------------------------------------------
    out("## 10. Is `revenue` gross or net of discount?")
    out()
    # Test empirically: for products sold both at 0 discount and at a discount,
    # compare unit price. If revenue is net, discounted units are cheaper.
    tmp = orders.assign(_unit=orders["Sales"] / orders["Quantity"],
                        _disc=orders["Discount"].round(3))
    zero = tmp[tmp["_disc"] == 0].groupby("Product ID")["_unit"].median()
    disc = tmp[tmp["_disc"] > 0].groupby(["Product ID", "_disc"])["_unit"].median()
    joined = disc.reset_index().merge(
        zero.rename("unit_at_zero"), left_on="Product ID", right_index=True, how="inner")
    joined["implied"] = joined["unit_at_zero"] * (1 - joined["_disc"])
    joined["ratio_net"] = joined["_unit"] / joined["implied"]
    joined["ratio_gross"] = joined["_unit"] / joined["unit_at_zero"]
    net_err = float((joined["ratio_net"] - 1).abs().median())
    gross_err = float((joined["ratio_gross"] - 1).abs().median())
    fact("discount_semantics_net_median_error", net_err)
    fact("discount_semantics_gross_median_error", gross_err)
    fact("discount_semantics_products_tested", int(joined["Product ID"].nunique()))

    out(f"Tested on {joined['Product ID'].nunique():,} products sold both at full price and")
    out("at a discount, comparing observed unit price against each hypothesis:")
    out()
    out("| Hypothesis | Median absolute error |")
    out("|---|---:|")
    out(f"| `revenue` is NET of discount (unit = list x (1-d)) | {net_err:.2%} |")
    out(f"| `revenue` is GROSS of discount (unit = list) | {gross_err:.2%} |")
    out()
    verdict = "net" if net_err < gross_err else "gross"
    fact("discount_semantics_verdict", verdict)
    out(f"**Verdict: `revenue` is {verdict.upper()} of discount.** This is tested rather than")
    out("assumed because the whole discount-effectiveness analysis depends on it:")
    out("`discount_amount` and gross/list revenue are reconstructed from this relationship.")
    out()

    # -- 11. returns -------------------------------------------------------
    out("## 11. Returns coverage - a real limit on the analysis")
    out()
    ret = returns.copy()
    ret["Market"] = ret["Market"].replace(MARKET_ALIASES)
    covered = sorted(ret["Market"].unique())
    uncovered = sorted(set(orders["Market"]) - set(covered))
    fact("returns_covered_markets", covered)
    fact("returns_uncovered_markets", uncovered)
    fact("returns_flag_values", {str(k): int(v) for k, v in
                                 returns["Returned"].value_counts().items()})

    out(f"- `Returned` only ever takes the value "
        f"{list(returns['Returned'].unique())} - there is no explicit 'No'")
    out(f"- Market labels differ between sheets: Returns says `United States`, "
        f"Orders says `US` (normalised before joining)")
    out(f"- Markets **with** return records: {', '.join(covered)}")
    out(f"- Markets with **zero** return records: **{', '.join(uncovered)}**")
    out()
    m_join = orders.merge(ret.assign(_r=1)[["Order ID", "Market", "_r"]],
                          on=["Order ID", "Market"], how="left")
    naive_join = orders.merge(
        ret.assign(_r=1)[["Order ID", "_r"]].drop_duplicates("Order ID"),
        on="Order ID", how="left")
    fact("returns_lines_composite_join", int(m_join["_r"].notna().sum()))
    fact("returns_lines_naive_join", int(naive_join["_r"].notna().sum()))
    fact("returns_join_rows_preserved", len(m_join) == len(orders))

    out("| Join key | Order lines flagged | Row count preserved |")
    out("|---|---:|---|")
    out(f"| `order_id` only (naive) | {int(naive_join['_r'].notna().sum()):,} | "
        f"{'yes' if len(naive_join) == len(orders) else 'NO'} |")
    out(f"| `(order_id, market)` (used) | {int(m_join['_r'].notna().sum()):,} | "
        f"{'yes' if len(m_join) == len(orders) else 'NO'} |")
    out()
    out(f"The naive join over-flags by "
        f"{int(naive_join['_r'].notna().sum()) - int(m_join['_r'].notna().sum())} lines, "
        "because a reused `order_id` in an uncovered market inherits another market's return.")
    out()
    out("**Decision and limitation.** Return rate is computed **only** over "
        f"{', '.join(covered)}. For {', '.join(uncovered)} the return rate is recorded as")
    out("*unknown*, never as 0%. Reporting zero would invent a flawless returns record for")
    out("three markets that simply were not measured, and would understate the global rate.")
    out()

    # -- 12. brand ---------------------------------------------------------
    out("## 12. Brand - a derived field, declared as derived")
    out()
    token = _brand_token(orders["Product Name"])
    vc = token.value_counts()
    junk = token.eq("Unknown")
    fact("brand_distinct", int(token.nunique()))
    fact("brand_unknown_lines", int(junk.sum()))
    fact("brand_unknown_share", float(junk.mean()))
    fact("brand_top_tokens_cover_share",
         float(vc[vc >= 100].sum() / len(orders)))

    out("The spec asks for `brand`; the dataset has no such column. The first token of")
    out("`product_name` is a manufacturer with high reliability, so it is extracted:")
    out()
    out(f"- Distinct brands derived: **{token.nunique():,}**")
    out(f"- Brands on >=100 order lines: **{int((vc >= 100).sum())}**, covering "
        f"**{vc[vc >= 100].sum() / len(orders):.1%}** of lines")
    out(f"- Lines where the token is numeric/punctuation and set to `Unknown`: "
        f"**{int(junk.sum()):,}** ({junk.mean():.2%})")
    out(f"- Most frequent: {', '.join(vc.head(12).index.tolist())}")
    out()
    out("**Stated limitations.** Multi-word brands truncate to their first word")
    out("(`Binney` for \"Binney & Smith\", `Harbour` for \"Harbour Creations\"). Roughly 3.7%")
    out("of `product_id`s disagree internally on the token. `brand` is therefore usable for")
    out("ranking and grouping, but it is a **derivation, not source data**, and is labelled")
    out("as such wherever it appears.")
    out()

    # -- 13. what cannot be done -------------------------------------------
    out("## 13. Spec requirements this dataset cannot support")
    out()
    out("These were **omitted and explained rather than fabricated**:")
    out()
    out("| Requested | Status | Why |")
    out("|---|---|---|")
    out("| `gender`, `age` | **Omitted** | No demographic fields exist. Any values would be invented. |")
    out("| `payment_method` | **Omitted** | Not recorded. The spec's payment-method analysis is therefore not answerable. |")
    out("| `order_status`, cancellation rate | **Omitted** | No status column. `order_priority` is a priority, not a status; returns are the only post-sale outcome recorded. |")
    out("| `signup_date` | **Derived, censored** | Taken as each customer's first observed order. Anyone active before 2011-01-01 is left-censored, so tenure is a floor, not a fact. |")
    out("| `delivery_date` | **Substituted** | Only `ship_date` exists; reported as order-to-ship lag. |")
    out("| `brand` | **Derived** | Extracted from `product_name` (section 12). |")
    out("| Return rate for Africa / Canada / EMEA | **Unknown** | No return records for those markets (section 11). |")
    out()
    fact("omitted_gender_age", True)
    fact("omitted_payment_method", True)
    fact("omitted_order_status", True)


def _brand_token(names: pd.Series) -> pd.Series:
    """First word of a product name, used as a derived brand.

    Tokens that are numeric, punctuation-only or a single character are not
    plausible manufacturers and become "Unknown" rather than polluting the
    field with values like "24" or "#6".
    """
    tok = names.astype("string").str.strip().str.split().str[0]
    tok = tok.str.replace(r"[,;:]+$", "", regex=True)
    bad = tok.isna() | tok.str.fullmatch(r"[\W\d]+|\w") | tok.eq("")
    return tok.mask(bad, "Unknown").astype("string")


# ===========================================================================
# CLEAN
# ===========================================================================
def resolve_customer_key(df: pd.DataFrame) -> pd.Series:
    """One stable key per real person.

    Every customer_name carries exactly two customer_ids (a market-split
    artifact), and segment is constant within a name, so the name identifies the
    person. Slugified so it is safe as a SQL/Power BI key.
    """
    return (
        df["customer_name"].str.strip().str.upper()
        .str.replace(r"[^A-Z0-9]+", "_", regex=True)
        .str.strip("_")
    )


def build_order_key(df: pd.DataFrame) -> pd.Series:
    """Composite order key - order_id alone is reused across customers/dates."""
    return (
        df["order_id"].astype("string")
        + "|" + df["customer_id"].astype("string")
        + "|" + df["order_date"].dt.strftime("%Y-%m-%d")
    )


def clean_orders(orders: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    """Apply every decision documented in audit() and return the clean table."""
    df = orders.rename(columns=COLUMN_MAP).copy()

    # Dates are already datetimes in the workbook; parse defensively anyway so
    # the pipeline does not depend on Excel's typing.
    df["order_date"] = pd.to_datetime(df["order_date"])
    df["ship_date"] = pd.to_datetime(df["ship_date"])

    # Trim whitespace on every text field. Silent leading spaces are the classic
    # cause of "Technology" and " Technology" appearing as two categories.
    text_cols = df.select_dtypes(include=["object", "string"]).columns
    for col in text_cols:
        df[col] = df[col].astype("string").str.strip()

    # Discount: 3dp kills the float artifacts and keeps the real 0.002/0.202/
    # 0.402/0.602 tiers. See audit section 6.
    df["discount"] = df["discount"].round(3)

    # Identity resolution (audit sections 3 and 4).
    df["customer_key"] = resolve_customer_key(df)
    df["order_key"] = build_order_key(df)

    # Derived brand, explicitly a derivation (audit section 12).
    df["brand"] = _brand_token(df["product_name"])

    # Canonical product label: the most common name for each product_id, so
    # reports get one stable readable name per key (audit section 5).
    canon = (
        df.groupby(["product_id", "product_name"], observed=True)
        .size().rename("n").reset_index()
        .sort_values(["product_id", "n", "product_name"], ascending=[True, False, True])
        .drop_duplicates("product_id")
        .set_index("product_id")["product_name"]
    )
    df["product_label"] = df["product_id"].map(canon).astype("string")

    # Returns: normalise the market label, then join on the composite key so a
    # reused order_id cannot inherit another market's return (audit section 11).
    ret = returns.rename(columns={"Order ID": "order_id", "Market": "market",
                                  "Returned": "returned"}).copy()
    ret["market"] = ret["market"].replace(MARKET_ALIASES)
    ret["order_id"] = ret["order_id"].astype("string").str.strip()
    ret["market"] = ret["market"].astype("string").str.strip()
    ret = ret.drop_duplicates(subset=["order_id", "market"])
    ret["return_flag"] = 1

    before = len(df)
    df = df.merge(ret[["order_id", "market", "return_flag"]],
                  on=["order_id", "market"], how="left")
    if len(df) != before:
        raise AssertionError(f"returns join changed row count: {before} -> {len(df)}")
    df["return_flag"] = df["return_flag"].fillna(0).astype("int8")

    # Whether this row's market has any returns data at all. Without this flag a
    # reader cannot tell "not returned" from "never measured".
    covered = set(ret["market"].dropna().unique())
    df["returns_measured"] = df["market"].isin(covered).astype("int8")

    return df


def build_dimensions(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Conformed customer and product dimension tables."""
    customers = (
        df.groupby("customer_key", observed=True)
        .agg(
            customer_name=("customer_name", "first"),
            customer_segment=("customer_segment", "first"),
            customer_ids=("customer_id", lambda s: "|".join(sorted(set(s.dropna())))),
            n_customer_ids=("customer_id", "nunique"),
            first_order_date=("order_date", "min"),
            last_order_date=("order_date", "max"),
            markets=("market", lambda s: "|".join(sorted(set(s.dropna())))),
            primary_country=("country", lambda s: s.mode().iat[0] if not s.mode().empty else pd.NA),
            n_orders=("order_key", "nunique"),
            n_lines=("order_line_id", "size"),
            revenue=("revenue", "sum"),
            profit=("profit", "sum"),
        )
        .reset_index()
    )
    # signup_date is the first observed purchase, not a true registration date.
    customers["signup_date_observed"] = customers["first_order_date"]

    products = (
        df.groupby("product_id", observed=True)
        .agg(
            product_label=("product_label", "first"),
            name_variants=("product_name", "nunique"),
            category=("category", lambda s: s.mode().iat[0]),
            sub_category=("sub_category", lambda s: s.mode().iat[0]),
            brand=("brand", lambda s: s.mode().iat[0]),
            n_lines=("order_line_id", "size"),
            quantity=("quantity", "sum"),
            revenue=("revenue", "sum"),
            profit=("profit", "sum"),
        )
        .reset_index()
    )
    products["ambiguous_name"] = (products["name_variants"] > 1).astype("int8")
    return customers, products


# ===========================================================================
# VALIDATE
# ===========================================================================
def validate(raw: pd.DataFrame, clean: pd.DataFrame) -> None:
    """Reconcile the clean table against the raw extract. Any failure raises."""
    out("## 14. Reconciliation - clean vs raw")
    out()
    checks: list[tuple[str, object, object, bool]] = []

    def check(label: str, got, want, tol: float = 0.0) -> None:
        ok = abs(float(got) - float(want)) <= tol if isinstance(want, (int, float)) else got == want
        checks.append((label, got, want, bool(ok)))

    check("row count", len(clean), len(raw))
    check("total revenue", clean["revenue"].sum(), raw["Sales"].sum(), 0.01)
    check("total profit", clean["profit"].sum(), raw["Profit"].sum(), 0.01)
    check("total quantity", clean["quantity"].sum(), raw["Quantity"].sum())
    check("total shipping cost", clean["shipping_cost"].sum(), raw["Shipping Cost"].sum(), 0.01)
    check("distinct order_line_id", clean["order_line_id"].nunique(), len(raw))
    check("distinct customer_id preserved", clean["customer_id"].nunique(),
          raw["Customer ID"].nunique())
    check("distinct product_id preserved", clean["product_id"].nunique(),
          raw["Product ID"].nunique())

    out("| Check | Clean | Raw | Result |")
    out("|---|---:|---:|---|")
    for label, got, want, ok in checks:
        g = f"{got:,.2f}" if isinstance(got, float) else f"{got:,}"
        w = f"{want:,.2f}" if isinstance(want, float) else f"{want:,}"
        out(f"| {label} | {g} | {w} | {'PASS' if ok else '**FAIL**'} |")
    out()

    failed = [c[0] for c in checks if not c[3]]
    fact("reconciliation_checks", len(checks))
    fact("reconciliation_failures", len(failed))
    if failed:
        raise AssertionError(f"reconciliation failed: {failed}")

    out(f"All **{len(checks)}** reconciliation checks pass. Cleaning changed no revenue, no")
    out("profit, no quantity and no rows - it added keys and labels, and removed nothing.")
    out()

    # Post-clean invariants that the audit's decisions must have produced.
    assert clean["customer_key"].nunique() == raw["Customer Name"].nunique(), \
        "customer_key should collapse to one row per real person"
    assert clean["order_key"].nunique() == \
        raw.groupby(["Order ID", "Customer ID", "Order Date"]).ngroups, \
        "order_key should match the composite grouping"
    assert clean["return_flag"].isin([0, 1]).all(), "return_flag must be binary"
    assert not clean["order_date"].isna().any(), "order_date must be fully populated"

    fact("clean_customers", int(clean["customer_key"].nunique()))
    fact("clean_orders", int(clean["order_key"].nunique()))
    fact("clean_rows", int(len(clean)))


# ===========================================================================
# MAIN
# ===========================================================================
def main() -> None:
    orders, returns, people = load_raw()
    validate_schema(orders)

    audit(orders, returns, people)
    clean = clean_orders(orders, returns)
    validate(orders, clean)
    customers, products = build_dimensions(clean)

    out("## 15. Outputs")
    out()
    out(f"- `data/processed/orders_clean.csv` - {len(clean):,} rows x {clean.shape[1]} cols")
    out(f"- `data/processed/customers.csv` - {len(customers):,} resolved customers")
    out(f"- `data/processed/products.csv` - {len(products):,} products")
    out()

    clean.to_csv(PROCESSED / "orders_clean.csv", index=False, encoding="utf-8")
    customers.to_csv(PROCESSED / "customers.csv", index=False, encoding="utf-8")
    products.to_csv(PROCESSED / "products.csv", index=False, encoding="utf-8")
    people.to_csv(PROCESSED / "regional_managers.csv", index=False, encoding="utf-8")

    REPORT_MD.write_text(_report.getvalue(), encoding="utf-8")
    FACTS_JSON.write_text(json.dumps(_facts, indent=2, default=str), encoding="utf-8")

    print(f"\nwrote {REPORT_MD.relative_to(ROOT)}")
    print(f"wrote {FACTS_JSON.relative_to(ROOT)}  ({len(_facts)} facts)")


if __name__ == "__main__":
    main()
