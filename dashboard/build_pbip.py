"""
E-COMMERCE ANALYTICS  |  POWER BI PROJECT (PBIP) BUILD
======================================================

Generates a real, openable Power BI Project: a TMDL semantic model plus a PBIR
report with four pages.

OUTPUT  dashboard/EcommerceAnalytics.pbip
        dashboard/EcommerceAnalytics.SemanticModel/   (TMDL model)
        dashboard/EcommerceAnalytics.Report/          (PBIR report, 4 pages)

WHY GENERATE IT RATHER THAN HAND-WRITE IT
-----------------------------------------
Every column definition is derived from the actual CSV in dashboard/data/, so
the model's data types cannot drift from the data. Every measure is defined once
here and emitted to both the TMDL and to measures.dax, so the documentation and
the model cannot disagree. And the whole thing is reproducible: delete the
folders, re-run, get an identical project.

TARGET VERSION
--------------
Authored against Power BI Desktop 2.155.756.0 (26.06), which is the version
installed on this machine and the one it was tested against. PBIP/TMDL/PBIR are
version-sensitive formats; on a much older Desktop these files may not open.

Run: python dashboard/build_pbip.py
"""

from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = HERE / "data"
NAME = "EcommerceAnalytics"
MODEL_DIR = HERE / f"{NAME}.SemanticModel"
REPORT_DIR = HERE / f"{NAME}.Report"

TAB = "\t"

# Deterministic ids, so re-running produces an identical project rather than a
# diff full of fresh GUIDs.
NS = uuid.UUID("6f1c8a2e-9d34-4b7a-8c51-1e2b3d4f5a60")


def det_id(seed: str) -> str:
    return str(uuid.uuid5(NS, seed))


def short_id(seed: str) -> str:
    return uuid.uuid5(NS, seed).hex[:20]


# ===========================================================================
# TYPE MAPPING
# ===========================================================================
# Columns whose text is an ISO date and must become a real date in the model.
DATE_COLUMNS = {
    ("dim_date", "date"),
    ("dim_customer", "first_order_date"),
    ("dim_customer", "last_order_date"),
}


def tmdl_type(table: str, col: str, dtype) -> tuple[str, str, str]:
    """Return (tmdl_dataType, m_type, summarizeBy)."""
    if (table, col) in DATE_COLUMNS:
        return "dateTime", "type date", "none"
    kind = dtype.kind if hasattr(dtype, "kind") else "O"
    if kind == "i":
        return "int64", "Int64.Type", "none"
    if kind == "f":
        return "double", "type number", "none"
    if kind == "b":
        return "boolean", "type logical", "none"
    return "string", "type text", "none"


# Columns that are model plumbing and should be hidden from report view.
HIDDEN_COLUMNS = {
    ("fact_sales", "order_date_key"), ("fact_sales", "ship_date_key"),
    ("fact_sales", "customer_key"), ("fact_sales", "product_key"),
    ("fact_sales", "geography_key"), ("fact_sales", "order_line_id"),
    ("dim_date", "date_key"), ("dim_date", "year_month_sort"),
    ("dim_date", "day_of_week_sort"),
    ("dim_customer", "customer_key"), ("dim_customer", "first_order_date_key"),
    ("dim_product", "product_id"),
    ("dim_geography", "geography_key"),
}

# Explicit sort-by pairs. Without these, "Jan 2011" sorts before "Feb 2011"
# alphabetically and every time series is silently scrambled.
SORT_BY = {
    ("dim_date", "year_month_label"): "year_month_sort",
    ("dim_date", "month_name"): "month",
    ("dim_date", "month_short"): "month",
    ("dim_date", "day_of_week"): "day_of_week_sort",
}

FORMAT_STRINGS = {
    ("fact_sales", "revenue"): '"$"#,0.00',
    ("fact_sales", "profit"): '"$"#,0.00',
    ("fact_sales", "cost"): '"$"#,0.00',
    ("fact_sales", "list_revenue"): '"$"#,0.00',
    ("fact_sales", "discount_amount"): '"$"#,0.00',
    ("fact_sales", "shipping_cost"): '"$"#,0.00',
    ("fact_sales", "discount"): "0.0%",
    ("dim_customer", "lifetime_revenue"): '"$"#,0',
    ("dim_customer", "lifetime_profit"): '"$"#,0',
    ("dim_customer", "avg_order_value"): '"$"#,0',
    ("dim_product", "lifetime_revenue"): '"$"#,0',
    ("dim_product", "lifetime_profit"): '"$"#,0',
    ("dim_date", "date"): "yyyy-mm-dd",
    ("dim_customer", "first_order_date"): "yyyy-mm-dd",
    ("dim_customer", "last_order_date"): "yyyy-mm-dd",
}


# ===========================================================================
# MEASURES  -  single source of truth for both the model and measures.dax
# ===========================================================================
# (name, folder, formatString, dax, description)
MEASURES: list[tuple[str, str, str, str, str]] = [
    # ---- core volume and value -------------------------------------------
    ("Total Revenue", "01 Core", '"$"#,0',
     "SUM ( fact_sales[revenue] )",
     "Net revenue, already net of discount. Verified: reports/data_quality_report.md s10."),
    ("Total Cost", "01 Core", '"$"#,0',
     "SUM ( fact_sales[cost] )",
     "Derived exactly as revenue - profit. Not a modelled assumption."),
    ("Total Profit", "01 Core", '"$"#,0',
     "SUM ( fact_sales[profit] )", "Real profit from the source data."),
    ("Total Units", "01 Core", "#,0", "SUM ( fact_sales[quantity] )", "Units sold."),
    ("Order Lines", "01 Core", "#,0", "COUNTROWS ( fact_sales )", "Order-line count."),
    ("Total Orders", "01 Core", "#,0",
     "DISTINCTCOUNT ( fact_sales[order_key] )",
     "Counts the COMPOSITE order key. Counting order_id instead returns 25,035 "
     "because order_id is reused across customers and dates. Expected: 25,754."),
    ("Total Customers", "01 Core", "#,0",
     "DISTINCTCOUNT ( fact_sales[customer_key] )",
     "Counts the RESOLVED person. Counting a raw customer_id returns 1,590 "
     "because every person has two ids. Expected: 795."),
    ("Total Products", "01 Core", "#,0",
     "DISTINCTCOUNT ( fact_sales[product_key] )", "Distinct products."),

    # ---- profitability ---------------------------------------------------
    ("Profit Margin %", "02 Profitability", "0.0%",
     "DIVIDE ( [Total Profit], [Total Revenue] )", "Profit over revenue. Expected 11.61%."),
    ("Total List Revenue", "02 Profitability", '"$"#,0',
     "SUM ( fact_sales[list_revenue] )", "Pre-discount revenue: revenue / (1 - discount)."),
    ("Discount Given", "02 Profitability", '"$"#,0',
     "SUM ( fact_sales[discount_amount] )", "Total discount surrendered. Expected $2,363,988."),
    ("Discount % of List", "02 Profitability", "0.0%",
     "DIVIDE ( [Discount Given], [Total List Revenue] )", "Expected 15.75%."),
    ("Average Discount %", "02 Profitability", "0.0%",
     "AVERAGE ( fact_sales[discount] )", "Mean line-level discount."),
    ("Loss-Making Lines", "02 Profitability", "#,0",
     "SUM ( fact_sales[is_loss_making] )", "Lines with negative profit. Expected 12,544."),
    ("Loss-Making Line %", "02 Profitability", "0.0%",
     "DIVIDE ( [Loss-Making Lines], [Order Lines] )", "Expected 24.46%."),
    ("Total Loss", "02 Profitability", '"$"#,0',
     "CALCULATE ( [Total Profit], KEEPFILTERS ( fact_sales[is_loss_making] = 1 ) )",
     "Sum of negative profit. Expected -$920,646."),
    ("Total Shipping Cost", "02 Profitability", '"$"#,0',
     "SUM ( fact_sales[shipping_cost] )", "Reported SEPARATELY, never netted into profit."),
    ("Shipping % of Revenue", "02 Profitability", "0.0%",
     "DIVIDE ( [Total Shipping Cost], [Total Revenue] )", "Expected 10.70%."),
    ("Profit After Shipping (scenario)", "02 Profitability", '"$"#,0',
     "[Total Profit] - [Total Shipping Cost]",
     "SCENARIO ONLY. Whether shipping is already inside profit cannot be determined "
     "from this extract. Do not use on a KPI card."),

    # ---- order and customer value ----------------------------------------
    ("Average Order Value", "03 Order value", '"$"#,0',
     "DIVIDE ( [Total Revenue], [Total Orders] )", "Expected $490.89."),
    ("Median Order Value", "03 Order value", '"$"#,0',
     "MEDIANX ( VALUES ( fact_sales[order_key] ), CALCULATE ( [Total Revenue] ) )",
     "Expected $201.30. Show this NEXT TO average - the mean is 2.44x the median, "
     "so AOV alone overstates a typical order by 144%."),
    ("Average Order Profit", "03 Order value", '"$"#,0',
     "DIVIDE ( [Total Profit], [Total Orders] )", "Mean profit per order."),
    ("Units per Order", "03 Order value", "0.00",
     "DIVIDE ( [Total Units], [Total Orders] )", "Basket size per ORDER."),
    ("Units per Line", "03 Order value", "0.00",
     "DIVIDE ( [Total Units], [Order Lines] )",
     "Units per ORDER LINE - the figure the discount analysis uses. Flat at "
     "3.40-3.81 from 0% to 50% discount, then FALLS to 2.84 above 50%. Use this, "
     "not Units per Order, on any discount-versus-volume visual, so the dashboard "
     "matches the notebook."),
    ("Lines per Order", "03 Order value", "0.00",
     "DIVIDE ( [Order Lines], [Total Orders] )", "Distinct products per order."),
    ("Orders per Customer", "03 Order value", "0.0",
     "DIVIDE ( [Total Orders], [Total Customers] )", "Expected ~32.4."),
    ("Revenue per Customer", "03 Order value", '"$"#,0',
     "DIVIDE ( [Total Revenue], [Total Customers] )", "Historical realised value."),

    # ---- returns, coverage aware -----------------------------------------
    ("Measured Orders", "04 Returns", "#,0",
     "CALCULATE ( [Total Orders], KEEPFILTERS ( fact_sales[returns_measured] = 1 ) )",
     "Orders in markets where returns were actually recorded. The ONLY valid "
     "denominator for a return rate here. Expected 20,717."),
    ("Unmeasured Orders", "04 Returns", "#,0",
     "CALCULATE ( [Total Orders], KEEPFILTERS ( fact_sales[returns_measured] = 0 ) )",
     "Orders in Africa/Canada/EMEA, which have NO return records. Expected 5,037."),
    ("Returned Orders", "04 Returns", "#,0",
     "CALCULATE ( [Total Orders], KEEPFILTERS ( fact_sales[return_flag] = 1 ), "
     "KEEPFILTERS ( fact_sales[returns_measured] = 1 ) )",
     "Expected 1,203."),
    ("Return Rate %", "04 Returns", "0.0%",
     "DIVIDE ( [Returned Orders], [Measured Orders] )", "Expected 5.81%."),
    ("Return Rate % (safe)", "04 Returns", "0.0%",
     "IF ( [Measured Orders] > 0, DIVIDE ( [Returned Orders], [Measured Orders] ) )",
     "USE THIS IN ANY VISUAL SLICED BY MARKET. Returns BLANK - not 0% - where no "
     "market in context has returns data, so Africa/Canada/EMEA render as a gap "
     "instead of a perfect returns record they never earned."),
    ("Returned Revenue", "04 Returns", '"$"#,0',
     "CALCULATE ( [Total Revenue], KEEPFILTERS ( fact_sales[return_flag] = 1 ), "
     "KEEPFILTERS ( fact_sales[returns_measured] = 1 ) )",
     "Expected $818,044."),

    # ---- time intelligence ------------------------------------------------
    ("Revenue PY", "05 Time", '"$"#,0',
     "CALCULATE ( [Total Revenue], SAMEPERIODLASTYEAR ( dim_date[date] ) )",
     "Requires dim_date marked as the model date table."),
    ("Revenue YoY %", "05 Time", "+0.0%;-0.0%",
     "VAR Prior = [Revenue PY]\nRETURN IF ( NOT ISBLANK ( Prior ), "
     "DIVIDE ( [Total Revenue] - Prior, Prior ) )",
     "Year-on-year growth. 2012 +18.5%, 2013 +27.2%, 2014 +26.3%."),
    ("Profit PY", "05 Time", '"$"#,0',
     "CALCULATE ( [Total Profit], SAMEPERIODLASTYEAR ( dim_date[date] ) )", "Prior-year profit."),
    ("Profit YoY %", "05 Time", "+0.0%;-0.0%",
     "VAR Prior = [Profit PY]\nRETURN IF ( NOT ISBLANK ( Prior ), "
     "DIVIDE ( [Total Profit] - Prior, Prior ) )", "Year-on-year profit growth."),
    ("Revenue MoM %", "05 Time", "+0.0%;-0.0%",
     "VAR Prior = CALCULATE ( [Total Revenue], DATEADD ( dim_date[date], -1, MONTH ) )\n"
     "RETURN IF ( NOT ISBLANK ( Prior ), DIVIDE ( [Total Revenue] - Prior, Prior ) )",
     "Month-on-month growth."),
    ("Revenue YTD", "05 Time", '"$"#,0',
     "TOTALYTD ( [Total Revenue], dim_date[date] )", "Year to date."),
    ("Revenue 3M Rolling Avg", "05 Time", '"$"#,0',
     "AVERAGEX ( DATESINPERIOD ( dim_date[date], MAX ( dim_date[date] ), -3, MONTH ), "
     "CALCULATE ( [Total Revenue] ) )",
     "Smooths the monthly series, which is dominated by a Nov-Dec peak."),
    ("Revenue Shipped (by ship date)", "05 Time", '"$"#,0',
     "CALCULATE ( [Total Revenue], "
     "USERELATIONSHIP ( fact_sales[ship_date_key], dim_date[date_key] ) )",
     "Uses the INACTIVE ship-date relationship. This is why dim_date has two "
     "relationships to the fact table."),

    # ---- fulfilment -------------------------------------------------------
    ("Avg Ship Lag Days", "06 Fulfilment", "0.00",
     "AVERAGEX ( VALUES ( fact_sales[order_key] ), "
     "CALCULATE ( MAX ( fact_sales[ship_lag_days] ) ) )",
     "ORDER-TO-SHIP lag. The dataset has NO delivery date, so this is not delivery "
     "time and there is no genuine late-delivery rate."),
    ("Max Ship Lag Days", "06 Fulfilment", "#,0",
     "MAX ( fact_sales[ship_lag_days] )", "Expected 7."),

    # ---- customer behaviour ----------------------------------------------
    ("Repeat Customers", "07 Customers", "#,0",
     "COALESCE ( COUNTROWS ( FILTER ( VALUES ( dim_customer[customer_key] ), "
     "[Total Orders] > 1 ) ), 0 )",
     "Expected 795 - every customer is a repeat customer."),
    ("One-Time Customers", "07 Customers", "#,0",
     "COALESCE ( COUNTROWS ( FILTER ( VALUES ( dim_customer[customer_key] ), "
     "[Total Orders] = 1 ) ), 0 )",
     "DEGENERATE: expected 0. COALESCE forces a literal 0 rather than BLANK, so the "
     "card reads '0' instead of '(Blank)' - the point is that zero one-time "
     "customers exist, and a blank card fails to say that."),
    ("Repeat Purchase Rate %", "07 Customers", "0.0%",
     "DIVIDE ( [Repeat Customers], [Total Customers] )",
     "DEGENERATE: expected 100% by construction. Carries no information here."),
    ("Avg Recency Days", "07 Customers", "0.0",
     "AVERAGE ( dim_customer[days_since_last_purchase] )",
     "Mean days since last purchase. Exists as a MEASURE because a scatter chart "
     "cannot put a raw column on an axis without an explicit aggregation."),
    ("Avg Customer Revenue", "07 Customers", '"$"#,0',
     "AVERAGE ( dim_customer[lifetime_revenue] )",
     "Mean lifetime revenue per customer, for the recency-vs-value scatter."),
    ("New Customers", "07 Customers", "#,0",
     "CALCULATE ( DISTINCTCOUNT ( dim_customer[customer_key] ), "
     "USERELATIONSHIP ( dim_customer[first_order_date_key], dim_date[date_key] ) )",
     "Customers whose FIRST order is in context - the correct definition of new. "
     "Non-zero only in 2011: the panel is closed after year one."),
    ("Unprofitable Customers", "07 Customers", "#,0",
     "CALCULATE ( DISTINCTCOUNT ( dim_customer[customer_key] ), "
     "KEEPFILTERS ( dim_customer[is_unprofitable] = 1 ) )",
     "Expected 67. Real revenue, negative lifetime profit."),
    ("Top 20% Customer Revenue Share %", "07 Customers", "0.0%",
     "VAR TotalRev = [Total Revenue]\n"
     "VAR N = ROUNDUP ( DISTINCTCOUNT ( dim_customer[customer_key] ) * 0.2, 0 )\n"
     "VAR TopCustomers =\n"
     "    TOPN ( N, VALUES ( dim_customer[customer_key] ), [Total Revenue], DESC )\n"
     "VAR TopRev = SUMX ( TopCustomers, [Total Revenue] )\n"
     "RETURN DIVIDE ( TopRev, TotalRev )",
     "Expected ~30%, NOT ~80%. The Pareto assumption fails on this dataset "
     "(Gini 0.18), so there is no top tier to protect."),

    # ---- cohort -----------------------------------------------------------
    # NOTE: cohort retention lives on fact_cohort_retention (see COHORT_MEASURES).
    # An earlier attempt to compute it from dim_customer returned 100% in every
    # cell, because at annual grain every customer in this closed panel buys every
    # year - technically true, analytically useless.

    # ---- narrative cards --------------------------------------------------
    ("Returns Coverage Note", "09 Notes", "",
     'VAR Unmeasured = [Unmeasured Orders]\n'
     'RETURN IF ( Unmeasured > 0,\n'
     '    "Return rate excludes " & FORMAT ( Unmeasured, "#,0" ) &\n'
     '    " orders in markets with no returns data (Africa, Canada, EMEA)",\n'
     '    "All orders in scope have returns data" )',
     "Put this on the Operations page so the coverage gap cannot be missed."),
    ("Dataset Caveat", "09 Notes", "",
     '"795-customer closed panel, all acquired 2011. No one-time customers, '
     'no demographics, no payment method, no order status. '
     'Returns unmeasured in Africa/Canada/EMEA."',
     "Puts the dataset's limits on the report rather than in a footnote."),
]


# ===========================================================================
# RELATIONSHIPS
# ===========================================================================
# (name_seed, fromTable, fromColumn, toTable, toColumn, isActive)
RELATIONSHIPS = [
    ("order_date", "fact_sales", "order_date_key", "dim_date", "date_key", True),
    ("ship_date", "fact_sales", "ship_date_key", "dim_date", "date_key", False),
    ("customer", "fact_sales", "customer_key", "dim_customer", "customer_key", True),
    ("product", "fact_sales", "product_key", "dim_product", "product_id", True),
    ("geography", "fact_sales", "geography_key", "dim_geography", "geography_key", True),
    ("cust_first_order", "dim_customer", "first_order_date_key", "dim_date", "date_key", False),
    ("returns_coverage", "dim_geography", "market", "dim_returns_coverage", "market", True),
]

TABLES = ["fact_sales", "dim_date", "dim_customer", "dim_product",
          "dim_geography", "dim_returns_coverage", "fact_cohort_retention"]

# Measures that belong on the standalone cohort table rather than fact_sales.
COHORT_MEASURES: list[tuple[str, str, str, str, str]] = [
    ("Retention %", "08 Cohort", "0.0%",
     "DIVIDE ( AVERAGE ( fact_cohort_retention[retention_pct] ), 100 )",
     "Cohort retention from the precomputed matrix, so the dashboard heatmap and "
     "the notebook heatmap are the SAME numbers rather than two independent "
     "calculations. This table is deliberately UNRELATED to the rest of the model: "
     "it is a fixed historical analysis and page slicers must not distort it. "
     "Read it knowing it measures the probability of purchasing in a month, not "
     "survival - it does not decay (trend -0.21pp/month, p = 0.09)."),
    ("Cohort Customers", "08 Cohort", "#,0",
     "SUM ( fact_cohort_retention[active_customers] )",
     "Active customers in the cohort-period cell."),
]


# ===========================================================================
# TMDL EMISSION
# ===========================================================================
def m_expression(table: str, df: pd.DataFrame, csv_path: Path) -> str:
    """Power Query M that loads one CSV with explicit types.

    Backslashes are NOT escape characters in M, so the Windows path is written
    literally. Encoding 65001 is UTF-8, which matters for the accented country
    and customer names in this data.
    """
    casts = []
    for col in df.columns:
        _, mtype, _ = tmdl_type(table, col, df[col].dtype)
        casts.append(f'{{"{col}", {mtype}}}')
    cast_list = ", ".join(casts)
    return (
        "let\n"
        f'    Source = Csv.Document(File.Contents("{csv_path}"), '
        f"[Delimiter=\",\", Columns={len(df.columns)}, Encoding=65001, "
        "QuoteStyle=QuoteStyle.Csv]),\n"
        "    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),\n"
        f"    Typed = Table.TransformColumnTypes(Headers, {{{cast_list}}})\n"
        "in\n"
        "    Typed"
    )


def emit_table_tmdl(table: str, df: pd.DataFrame, csv_path: Path,
                    measures: list[tuple] | None = None) -> str:
    lines = [f"table {table}", ""]

    for col in df.columns:
        dt, _, summarize = tmdl_type(table, col, df[col].dtype)
        lines.append(f"{TAB}column {col}")
        lines.append(f"{TAB*2}dataType: {dt}")
        if (table, col) in FORMAT_STRINGS:
            lines.append(f"{TAB*2}formatString: {FORMAT_STRINGS[(table, col)]}")
        if (table, col) in HIDDEN_COLUMNS:
            lines.append(f"{TAB*2}isHidden")
        lines.append(f"{TAB*2}summarizeBy: {summarize}")
        lines.append(f"{TAB*2}sourceColumn: {col}")
        if (table, col) in SORT_BY:
            lines.append(f"{TAB*2}sortByColumn: {SORT_BY[(table, col)]}")
        lines.append("")
        lines.append(f"{TAB*2}annotation SummarizationSetBy = Automatic")
        lines.append("")

    if measures:
        for name, folder, fmt, dax, desc in measures:
            for dline in desc.replace("\n", " ").split(". "):
                d = dline.strip()
                if d:
                    lines.append(f"{TAB}/// {d if d.endswith('.') else d + '.'}")
            lines.append(f"{TAB}measure '{name}' =")
            for dl in dax.split("\n"):
                lines.append(f"{TAB*3}{dl}")
            if fmt:
                lines.append(f"{TAB*2}formatString: {fmt}")
            if folder:
                lines.append(f"{TAB*2}displayFolder: {folder}")
            lines.append("")

    lines.append(f"{TAB}partition {table} = m")
    lines.append(f"{TAB*2}mode: import")
    lines.append(f"{TAB*2}source = ```")
    for ml in m_expression(table, df, csv_path).split("\n"):
        lines.append(f"{TAB*4}{ml}")
    lines.append(f"{TAB*4}```")
    lines.append("")
    lines.append(f"{TAB}annotation PBI_ResultType = Table")
    lines.append("")
    return "\n".join(lines)


def emit_relationships_tmdl() -> str:
    lines = []
    for seed, ft, fc, tt, tc, active in RELATIONSHIPS:
        lines.append(f"relationship {det_id('rel_' + seed)}")
        if not active:
            lines.append(f"{TAB}isActive: false")
        lines.append(f"{TAB}fromColumn: {ft}.{fc}")
        lines.append(f"{TAB}toColumn: {tt}.{tc}")
        lines.append("")
    return "\n".join(lines)


def emit_model_tmdl() -> str:
    lines = [
        "model Model",
        f"{TAB}culture: en-US",
        f"{TAB}defaultPowerBIDataSourceVersion: powerBI_V3",
        f"{TAB}discourageImplicitMeasures",
        f"{TAB}sourceQueryCulture: en-US",
        f"{TAB}dataAccessOptions",
        f"{TAB*2}legacyRedirects",
        f"{TAB*2}returnErrorValuesAsNull",
        "",
        f"{TAB}annotation PBI_QueryOrder = "
        + json.dumps(TABLES),
        "",
        f"{TAB}annotation PBI_ProTooling = [\"DevMode\"]",
        "",
    ]
    for t in TABLES:
        lines.append(f"ref table {t}")
    lines.append("")
    lines.append("ref cultureInfo en-US")
    lines.append("")
    return "\n".join(lines)


def emit_culture_tmdl() -> str:
    return "\n".join([
        "cultureInfo en-US",
        "",
        f"{TAB}linguisticMetadata = {{\"Version\":\"1.0.0\",\"Language\":\"en-US\"}}",
        f"{TAB*2}contentType: json",
        "",
    ])


# ===========================================================================
# PBIR REPORT EMISSION
# ===========================================================================
def measure_field(name: str, entity: str = "fact_sales") -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": name}}


def column_field(entity: str, name: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": name}}


def projection(field: dict, entity: str, prop: str) -> dict:
    return {"field": field, "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}


def literal(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def visual_json(vid: str, vtype: str, x: int, y: int, w: int, h: int,
                roles: dict, title: str | None = None, z: int = 0,
                objects: dict | None = None,
                sort: tuple[dict, str] | None = None) -> dict:
    """One PBIR visual container.

    `sort` is (field, "Ascending"|"Descending"). Without an explicit sort a bar
    chart falls back to alphabetical order, which buries the finding - e.g. the
    sub-category profit chart is titled "only Tables is negative" but Tables sits
    off-screen unless the bars are sorted by profit.
    """
    query_state = {}
    for role, projections in roles.items():
        query_state[role] = {"projections": projections}

    query: dict = {"queryState": query_state}
    if sort:
        field, direction = sort
        query["sortDefinition"] = {
            "sort": [{"field": field, "direction": direction}],
            "isDefaultSort": True,
        }

    visual: dict = {
        "visualType": vtype,
        "query": query,
        "drillFilterOtherVisuals": True,
    }
    if objects:
        visual["objects"] = objects
    if title is not None:
        visual["visualContainerObjects"] = {
            "title": [{"properties": {
                "show": literal("true"),
                "text": literal(f"'{title}'"),
                "fontSize": literal("11D"),
                "bold": literal("true"),
            }}]
        }
    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/"
                   "definition/visualContainer/1.4.0/schema.json",
        "name": vid,
        "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z},
        "visual": visual,
    }


def kpi_card(seed: str, measure: str, title: str, x: int, y: int,
             w: int = 150, h: int = 95, z: int = 0) -> dict:
    return visual_json(
        short_id(seed), "card", x, y, w, h,
        {"Values": [projection(measure_field(measure), "fact_sales", measure)]},
        title=title, z=z,
        objects={"labels": [{"properties": {"fontSize": literal("20D")}}],
                 "categoryLabels": [{"properties": {"show": literal("false")}}]},
    )


def build_pages() -> list[dict]:
    """Four report pages. Bar/column charts are used ONLY on low-cardinality
    fields; product lists use tables, because a 10,292-category bar chart is
    unreadable and a raw TopN filter in hand-written JSON is fragile."""
    pages = []

    # ------------------------------------------------ Page 1: Executive
    v: list[dict] = []
    kpis = [
        ("Total Revenue", "Total Revenue"), ("Total Profit", "Total Profit"),
        ("Profit Margin %", "Profit Margin"), ("Total Orders", "Orders"),
        ("Total Customers", "Customers"), ("Average Order Value", "Avg Order Value"),
        ("Median Order Value", "Median Order Value"), ("Return Rate % (safe)", "Return Rate"),
    ]
    for i, (m, t) in enumerate(kpis):
        v.append(kpi_card(f"p1kpi{i}", m, t, 8 + i * 158, 8))
    v.append(visual_json(
        short_id("p1trend"), "lineClusteredColumnComboChart", 8, 112, 790, 290,
        {"Category": [projection(column_field("dim_date", "year_month_label"),
                                 "dim_date", "year_month_label")],
         "Y": [projection(measure_field("Total Revenue"), "fact_sales", "Total Revenue")],
         "Y2": [projection(measure_field("Revenue 3M Rolling Avg"), "fact_sales",
                           "Revenue 3M Rolling Avg")]},
        title="Revenue by month with 3-month average - growing, with a Nov-Dec peak", z=1))
    v.append(visual_json(
        short_id("p1margin"), "lineChart", 806, 112, 466, 290,
        {"Category": [projection(column_field("dim_date", "year"), "dim_date", "year")],
         "Y": [projection(measure_field("Profit Margin %"), "fact_sales", "Profit Margin %")]},
        title="Margin never leaves 11-12% while revenue doubles", z=2))
    v.append(visual_json(
        short_id("p1cat"), "clusteredBarChart", 8, 410, 420, 290,
        {"Category": [projection(column_field("dim_product", "category"),
                                 "dim_product", "category")],
         "Y": [projection(measure_field("Total Revenue"), "fact_sales", "Total Revenue"),
               projection(measure_field("Total Profit"), "fact_sales", "Total Profit")]},
        title="Revenue vs profit by category", z=3))
    v.append(visual_json(
        short_id("p1mkt"), "clusteredColumnChart", 436, 410, 420, 290,
        {"Category": [projection(column_field("dim_geography", "market"),
                                 "dim_geography", "market")],
         "Y": [projection(measure_field("Total Revenue"), "fact_sales", "Total Revenue")]},
        title="Revenue by market", z=4,
        sort=(measure_field("Total Revenue"), "Descending")))
    v.append(visual_json(
        short_id("p1sub"), "clusteredBarChart", 864, 410, 408, 290,
        {"Category": [projection(column_field("dim_product", "sub_category"),
                                 "dim_product", "sub_category")],
         "Y": [projection(measure_field("Total Profit"), "fact_sales", "Total Profit")]},
        title="Profit by sub-category - only Tables is negative", z=5,
        sort=(measure_field("Total Profit"), "Ascending")))
    pages.append({"name": "executiveOverview", "display": "Executive Overview", "visuals": v})

    # ------------------------------------------------ Page 2: Sales & Product
    v = []
    for i, (m, t) in enumerate([
        ("Total Revenue", "Revenue"), ("Total Profit", "Profit"),
        ("Profit Margin %", "Margin"), ("Total Units", "Units"),
        ("Discount Given", "Discount Given"), ("Discount % of List", "Discount % of List"),
        ("Loss-Making Line %", "Loss-Making Lines"), ("Total Loss", "Total Loss"),
    ]):
        v.append(kpi_card(f"p2kpi{i}", m, t, 8 + i * 158, 8))
    v.append(visual_json(
        short_id("p2scatter"), "scatterChart", 8, 112, 640, 330,
        {"Category": [projection(column_field("dim_product", "product_label"),
                                 "dim_product", "product_label")],
         "X": [projection(measure_field("Total Revenue"), "fact_sales", "Total Revenue")],
         "Y": [projection(measure_field("Profit Margin %"), "fact_sales", "Profit Margin %")],
         "Series": [projection(column_field("dim_product", "profit_quadrant"),
                               "dim_product", "profit_quadrant")]},
        title="Product quadrants - the red group carries 24% of revenue at a loss", z=1))
    v.append(visual_json(
        short_id("p2dband"), "clusteredColumnChart", 656, 112, 300, 330,
        {"Category": [projection(column_field("fact_sales", "discount_band"),
                                 "fact_sales", "discount_band")],
         "Y": [projection(measure_field("Profit Margin %"), "fact_sales", "Profit Margin %")]},
        title="Margin collapses above 20% discount", z=2))
    v.append(visual_json(
        short_id("p2dunits"), "clusteredColumnChart", 964, 112, 308, 330,
        {"Category": [projection(column_field("fact_sales", "discount_band"),
                                 "fact_sales", "discount_band")],
         "Y": [projection(measure_field("Units per Line"), "fact_sales", "Units per Line")]},
        title="...but units do NOT respond (then fall at 51%+)", z=3))
    v.append(visual_json(
        short_id("p2dloss"), "clusteredColumnChart", 8, 450, 420, 250,
        {"Category": [projection(column_field("fact_sales", "discount_band"),
                                 "fact_sales", "discount_band")],
         "Y": [projection(measure_field("Loss-Making Line %"), "fact_sales",
                          "Loss-Making Line %")]},
        title="0% of full-price lines lose money; 100% above 50% do", z=4))
    v.append(visual_json(
        short_id("p2table"), "tableEx", 436, 450, 836, 250,
        {"Values": [
            projection(column_field("dim_product", "product_label"),
                       "dim_product", "product_label"),
            projection(column_field("dim_product", "sub_category"),
                       "dim_product", "sub_category"),
            projection(column_field("dim_product", "profit_quadrant"),
                       "dim_product", "profit_quadrant"),
            projection(measure_field("Total Revenue"), "fact_sales", "Total Revenue"),
            projection(measure_field("Total Profit"), "fact_sales", "Total Profit"),
            projection(measure_field("Average Discount %"), "fact_sales", "Average Discount %"),
        ]},
        title="Products - sort by Total Profit ascending to find what to reprice", z=5))
    pages.append({"name": "salesProduct", "display": "Sales & Product", "visuals": v})

    # ------------------------------------------------ Page 3: Customers
    v = []
    for i, (m, t) in enumerate([
        ("Total Customers", "Customers"), ("Repeat Customers", "Repeat"),
        ("One-Time Customers", "One-Time (=0)"),
        ("Repeat Purchase Rate %", "Repeat Rate (=100%)"),
        ("Revenue per Customer", "Revenue/Customer"),
        ("Orders per Customer", "Orders/Customer"),
        ("Unprofitable Customers", "Unprofitable"),
        ("Top 20% Customer Revenue Share %", "Top 20% Share (not 80%)"),
    ]):
        v.append(kpi_card(f"p3kpi{i}", m, t, 8 + i * 158, 8))
    v.append(visual_json(
        short_id("p3seg"), "clusteredBarChart", 8, 112, 420, 300,
        {"Category": [projection(column_field("dim_customer", "segment"),
                                 "dim_customer", "segment")],
         "Y": [projection(measure_field("Total Customers"), "fact_sales", "Total Customers")]},
        title="RFM segments - 'New Customers' is legitimately empty", z=1,
        sort=(measure_field("Total Customers"), "Descending")))
    v.append(visual_json(
        short_id("p3segrev"), "clusteredColumnChart", 436, 112, 420, 300,
        {"Category": [projection(column_field("dim_customer", "segment"),
                                 "dim_customer", "segment")],
         "Y": [projection(measure_field("Total Revenue"), "fact_sales", "Total Revenue")]},
        title="Revenue by segment", z=2,
        sort=(measure_field("Total Revenue"), "Descending")))
    # Scatter axes must be MEASURES. Putting dim_customer[days_since_last_purchase]
    # straight on the X axis made Power BI refuse to render with "set a
    # summarization for x- and y-axis", so both axes are explicit aggregations.
    v.append(visual_json(
        short_id("p3scatter"), "scatterChart", 864, 112, 408, 300,
        {"Category": [projection(column_field("dim_customer", "customer_name"),
                                 "dim_customer", "customer_name")],
         "X": [projection(measure_field("Avg Recency Days"), "fact_sales",
                          "Avg Recency Days")],
         "Y": [projection(measure_field("Avg Customer Revenue"), "fact_sales",
                          "Avg Customer Revenue")],
         "Series": [projection(column_field("dim_customer", "segment"),
                               "dim_customer", "segment")]},
        title="Recency vs value, by customer", z=3))
    # Cohort heatmap from the precomputed table: rows = acquisition cohort,
    # columns = MONTHS since acquisition. Computing this from dim_customer gave
    # 100% in every cell, because at annual grain everyone in a closed panel buys
    # every year.
    v.append(visual_json(
        short_id("p3cohort"), "matrix", 8, 420, 780, 280,
        {"Rows": [projection(column_field("fact_cohort_retention", "cohort_month"),
                             "fact_cohort_retention", "cohort_month")],
         "Columns": [projection(column_field("fact_cohort_retention", "period_index"),
                                "fact_cohort_retention", "period_index")],
         "Values": [projection(measure_field("Retention %", "fact_cohort_retention"),
                               "fact_cohort_retention", "Retention %")]},
        title="Cohort retention by months since acquisition - measures purchase "
              "cadence, NOT survival, and does not decay", z=4))
    v.append(visual_json(
        short_id("p3table"), "tableEx", 796, 420, 476, 280,
        {"Values": [
            projection(column_field("dim_customer", "customer_name"),
                       "dim_customer", "customer_name"),
            projection(column_field("dim_customer", "segment"), "dim_customer", "segment"),
            projection(measure_field("Total Revenue"), "fact_sales", "Total Revenue"),
            projection(measure_field("Total Profit"), "fact_sales", "Total Profit"),
        ]},
        title="Customers - sort by profit to find the 67 unprofitable", z=5))
    pages.append({"name": "customerAnalytics", "display": "Customer Analytics", "visuals": v})

    # ------------------------------------------------ Page 4: Operations
    v = []
    for i, (m, t) in enumerate([
        ("Return Rate % (safe)", "Return Rate"), ("Returned Orders", "Returned Orders"),
        ("Returned Revenue", "Returned Revenue"), ("Measured Orders", "Measured Orders"),
        ("Unmeasured Orders", "NO returns data"), ("Avg Ship Lag Days", "Avg Ship Lag"),
        ("Total Shipping Cost", "Shipping Cost"),
        ("Shipping % of Revenue", "Shipping % of Rev"),
    ]):
        v.append(kpi_card(f"p4kpi{i}", m, t, 8 + i * 158, 8))
    v.append(visual_json(
        short_id("p4note"), "card", 8, 112, 1264, 60,
        {"Values": [projection(measure_field("Returns Coverage Note"), "fact_sales",
                               "Returns Coverage Note")]},
        title=None, z=1,
        objects={"labels": [{"properties": {"fontSize": literal("12D")}}]}))
    v.append(visual_json(
        short_id("p4mkt"), "clusteredColumnChart", 8, 180, 420, 260,
        {"Category": [projection(column_field("dim_geography", "market"),
                                 "dim_geography", "market")],
         "Y": [projection(measure_field("Return Rate % (safe)"), "fact_sales",
                          "Return Rate % (safe)")]},
        title="Return rate by market - unmeasured markets render BLANK, not 0%", z=2))
    v.append(visual_json(
        short_id("p4sub"), "clusteredBarChart", 436, 180, 420, 260,
        {"Category": [projection(column_field("dim_product", "sub_category"),
                                 "dim_product", "sub_category")],
         "Y": [projection(measure_field("Return Rate % (safe)"), "fact_sales",
                          "Return Rate % (safe)")]},
        title="Return rate by sub-category - set X axis to start at 0%: "
              "the spread is only 6.3-9.1%", z=3,
        sort=(measure_field("Return Rate % (safe)"), "Descending")))
    v.append(visual_json(
        short_id("p4ship"), "clusteredColumnChart", 864, 180, 408, 260,
        {"Category": [projection(column_field("fact_sales", "ship_mode"),
                                 "fact_sales", "ship_mode")],
         "Y": [projection(measure_field("Avg Ship Lag Days"), "fact_sales",
                          "Avg Ship Lag Days")]},
        title="Ship mode delivers what it promises", z=4))
    v.append(visual_json(
        short_id("p4shipcost"), "clusteredBarChart", 8, 448, 420, 252,
        {"Category": [projection(column_field("dim_geography", "market"),
                                 "dim_geography", "market")],
         "Y": [projection(measure_field("Shipping % of Revenue"), "fact_sales",
                          "Shipping % of Revenue")]},
        title="Shipping as % of revenue by market", z=5))
    v.append(visual_json(
        short_id("p4dret"), "clusteredColumnChart", 436, 448, 420, 252,
        {"Category": [projection(column_field("fact_sales", "discount_band"),
                                 "fact_sales", "discount_band")],
         "Y": [projection(measure_field("Return Rate % (safe)"), "fact_sales",
                          "Return Rate % (safe)")]},
        title="Do discounted orders come back more?", z=6))
    v.append(visual_json(
        short_id("p4prio"), "tableEx", 864, 448, 408, 252,
        {"Values": [
            projection(column_field("fact_sales", "order_priority"),
                       "fact_sales", "order_priority"),
            projection(measure_field("Total Orders"), "fact_sales", "Total Orders"),
            projection(measure_field("Avg Ship Lag Days"), "fact_sales", "Avg Ship Lag Days"),
            projection(measure_field("Return Rate % (safe)"), "fact_sales",
                       "Return Rate % (safe)"),
        ]},
        title="Is order priority honoured?", z=7))
    pages.append({"name": "operationsReturns", "display": "Operations & Returns", "visuals": v})

    return pages


# ===========================================================================
# WRITE
# ===========================================================================
def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, obj: dict) -> None:
    write(path, json.dumps(obj, indent=2) + "\n")


def main() -> None:
    for d in (MODEL_DIR, REPORT_DIR):
        if d.exists():
            shutil.rmtree(d)

    frames = {t: pd.read_csv(DATA / f"{t}.csv", nrows=200) for t in TABLES}

    # ---------------------------------------------------------- .pbip
    # NOTE the schema path: fabric/pbip/pbipProperties/, NOT fabric/item/pbip/.
    # Power BI validates this pattern strictly and rejects the file with
    # "Issues were found" - then silently opens a blank report - if it is wrong.
    write_json(HERE / f"{NAME}.pbip", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/"
                   "pbipProperties/1.0.0/schema.json",
        "version": "1.0",
        "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True},
    })

    # ---------------------------------------------------- semantic model
    write_json(MODEL_DIR / ".platform", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/"
                   "platformProperties/2.0.0/schema.json",
        "metadata": {"type": "SemanticModel", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": det_id("model")},
    })
    write_json(MODEL_DIR / "definition.pbism", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/"
                   "semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2",
        "settings": {},
    })

    defn = MODEL_DIR / "definition"
    write(defn / "database.tmdl", "database\n\tcompatibilityLevel: 1601\n")
    write(defn / "model.tmdl", emit_model_tmdl())
    write(defn / "relationships.tmdl", emit_relationships_tmdl())
    write(defn / "cultures" / "en-US.tmdl", emit_culture_tmdl())

    for t in TABLES:
        csv_abs = (DATA / f"{t}.csv").resolve()
        if t == "fact_sales":
            tbl_measures = MEASURES
        elif t == "fact_cohort_retention":
            tbl_measures = COHORT_MEASURES
        else:
            tbl_measures = None
        write(defn / "tables" / f"{t}.tmdl",
              emit_table_tmdl(t, frames[t], csv_abs, tbl_measures))

    # ----------------------------------------------------------- report
    write_json(REPORT_DIR / ".platform", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/"
                   "platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Report", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": det_id("report")},
    })
    write_json(REPORT_DIR / "definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/"
                   "definitionProperties/1.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}},
    })

    rdef = REPORT_DIR / "definition"
    write_json(rdef / "report.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/"
                   "definition/report/1.0.0/schema.json",
        "themeCollection": {"baseTheme": {"name": "CY24SU10",
                                          "reportVersionAtImport": "5.55",
                                          "type": "SharedResources"}},
        "layoutOptimization": "None",
        "settings": {"useStylableVisualContainerHeader": True,
                     "defaultFilterActionIsDataFilter": True},
    })
    write_json(rdef / "version.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/"
                   "definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0",
    })

    pages = build_pages()
    write_json(rdef / "pages" / "pages.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/"
                   "definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p["name"] for p in pages],
        "activePageName": pages[0]["name"],
    })

    total_visuals = 0
    for p in pages:
        pdir = rdef / "pages" / p["name"]
        write_json(pdir / "page.json", {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/"
                       "definition/page/1.4.0/schema.json",
            "name": p["name"],
            "displayName": p["display"],
            "displayOption": "FitToPage",
            "height": 720,
            "width": 1280,
        })
        for vis in p["visuals"]:
            write_json(pdir / "visuals" / vis["name"] / "visual.json", vis)
            total_visuals += 1

    # ------------------------------------------- regenerate measures.dax
    # Generated from MEASURES so the documentation cannot drift from the model.
    lines = [
        "// ==========================================================================",
        "//  E-COMMERCE ANALYTICS  |  DAX MEASURE LIBRARY",
        "// ==========================================================================",
        "//  GENERATED by dashboard/build_pbip.py - do not edit by hand.",
        "//  The same definitions are emitted into the TMDL semantic model, so this",
        "//  file and the model cannot disagree. Edit MEASURES in build_pbip.py.",
        "//",
        "//  All measures live on the fact_sales table.",
        "// ==========================================================================",
        "",
    ]
    folder = None
    for name, fld, fmt, dax, desc in MEASURES:
        if fld != folder:
            folder = fld
            lines += ["", f"// ---- {folder} " + "-" * (66 - len(folder)), ""]
        for d in desc.split(". "):
            if d.strip():
                lines.append(f"// {d.strip().rstrip('.')}.")
        lines.append(f"{name} =")
        lines += [f"    {dl}" for dl in dax.split("\n")]
        if fmt:
            lines.append(f"// format: {fmt}")
        lines.append("")
    write(HERE / "measures.dax", "\n".join(lines) + "\n")

    print("PBIP PROJECT BUILT")
    print("=" * 68)
    print(f"  {NAME}.pbip")
    print(f"  {NAME}.SemanticModel/   {len(TABLES)} tables, "
          f"{len(MEASURES) + len(COHORT_MEASURES)} measures, "
          f"{len(RELATIONSHIPS)} relationships")
    print(f"  {NAME}.Report/          {len(pages)} pages, {total_visuals} visuals")
    print()
    for t in TABLES:
        print(f"    {t:<24} {frames[t].shape[1]:>2} columns")
    print()
    inactive = [r[0] for r in RELATIONSHIPS if not r[5]]
    print(f"  inactive relationships (by design): {inactive}")
    print(f"  measures.dax regenerated from the same definitions")
    print(f"\n  open with: \"D:\\Power-bi\\powerbi\\bin\\PBIDesktop.exe\" "
          f"\"{(HERE / (NAME + '.pbip'))}\"")


if __name__ == "__main__":
    main()
