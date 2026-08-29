# Dashboard Specification

Four pages, built on the star schema in `data/` and the measures in `measures.dax`.
Every visual below names the business question it answers; anything that would only
decorate the page is absent by design.

---

## Model

```
                        dim_date (1,468 rows)
                       /                    \
        order_date_key                      ship_date_key
          (active)                           (INACTIVE)
                       \                    /
                         fact_sales (51,290)
                        /       |         \
           dim_customer      dim_product   dim_geography (3,819)
              (795)            (10,292)          |
                                          dim_returns_coverage (7)
```

Two date relationships is the point of the star schema: one active on
`order_date_key`, one **inactive** on `ship_date_key`, activated by
`USERELATIONSHIP` inside the fulfilment measures. Without that, ship-date and
order-date analysis cannot coexist in one model.

`dim_returns_coverage` hangs off `dim_geography[market]` for one reason: it carries
`has_returns_data`, which stops any visual reporting a 0% return rate for Africa,
Canada or EMEA — markets where returns were never recorded.

**Setup steps that are easy to miss and break the model if skipped:**

1. Mark `dim_date` as the date table (`Table tools > Mark as date table`, using
   `dim_date[date]`). Time intelligence silently misbehaves otherwise.
2. Set `dim_date[year_month_label]` to sort by `year_month_sort`, and
   `dim_date[day_of_week]` by `day_of_week_sort`. Otherwise "Apr 2011" sorts
   alphabetically before "Jan 2011".
3. Set the `fact_sales[ship_date_key] → dim_date[date_key]` relationship to
   **inactive**.
4. Add a second inactive relationship
   `dim_customer[first_order_date_key] → dim_date[date_key]` for the
   `New Customers` measure.
5. Hide every `*_key` column from report view. They are plumbing.

---

## Page 1 — Executive Overview

**Question: how is the business performing, and is growth healthy?**

### KPI row

| Card | Measure | Format | Note |
|---|---|---|---|
| Total Revenue | `Total Revenue` | $#,0,,"M" | |
| Total Profit | `Total Profit` | $#,0,,"M" | |
| Profit Margin | `Profit Margin %` | 0.0% | Conditional colour via `Margin Health` |
| Total Orders | `Total Orders` | #,0 | Counts `order_key`, not `order_id` |
| Total Customers | `Total Customers` | #,0 | Counts `customer_key`, not `customer_id` |
| Avg Order Value | `Average Order Value` | $#,0 | |
| Median Order Value | `Median Order Value` | $#,0 | **Shown beside AOV deliberately** — the mean is 2.44× the median, so AOV alone overstates a typical order by 144% |
| Return Rate | `Return Rate % (safe)` | 0.0% | Blank, never 0%, where unmeasured |

### Visuals

| # | Visual | Fields | Question |
|---|---|---|---|
| 1.1 | Line + column combo | Axis `dim_date[year_month_label]`; column `Total Revenue`; line `Revenue 3M Rolling Avg` | Is revenue trending up or is it noise? |
| 1.2 | Line chart | Axis `year_month_label`; values `Total Profit`, `Profit Margin %` (secondary axis) | Is margin improving as revenue grows? *(It is not — flat 11–12%.)* |
| 1.3 | Clustered bar | Axis `dim_product[category]`; values `Total Revenue`, `Total Profit` | Which categories earn, not just sell? |
| 1.4 | Map or bar | `dim_geography[market]`; values `Total Revenue`, `Profit Margin %` | Which markets perform best? |
| 1.5 | Bar (top N = 10) | `dim_product[product_label]`; value `Total Revenue` | What are the biggest sellers? |
| 1.6 | Column | Axis `dim_date[year]`; values `Total Revenue`, `Revenue YoY %` | Is growth accelerating? |
| 1.7 | Card (text) | `Dataset Caveat` | Puts the dataset's limits on the page, not in a footnote |

### Slicers (all pages, synced)

`dim_date[date]` (between), `dim_product[category]`, `dim_product[sub_category]`,
`dim_geography[market]`, `dim_geography[region]`, `dim_customer[customer_segment]`,
`dim_customer[segment]` (RFM), `fact_sales[discount_band]`, `fact_sales[ship_mode]`.

> The brief also asked for an **Order Status** filter. There is no order status
> field in this dataset, so that slicer is **omitted** rather than faked.
> `order_priority` is a priority, not a status, and is offered separately.

---

## Page 2 — Sales & Product Analysis

**Question: where does profit actually come from, and what is discounting costing?**

### KPI row

`Total Revenue` · `Total Profit` · `Profit Margin %` · `Total Units` ·
`Discount Given` · `Discount % of List` · `Loss-Making Line %`

### Visuals

| # | Visual | Fields | Question |
|---|---|---|---|
| 2.1 | Clustered bar | `sub_category`; `Total Revenue`, `Total Profit`, sorted by profit ascending | Which sub-categories destroy value? *(Exactly one: Tables.)* |
| 2.2 | **Scatter** | X `Total Revenue`, Y `Profit Margin %`, size `Total Units`, legend `dim_product[profit_quadrant]`, details `product_label` | **The most important visual in the report** — the high-revenue / loss-making quadrant |
| 2.3 | Bar | `discount_band`; `Profit Margin %` | Where does margin turn negative? *(Between 11–20% and 21–30%.)* |
| 2.4 | Bar | `discount_band`; `Units per Order` | Does discounting buy volume? *(No — flat, then falls.)* |
| 2.5 | Bar | `discount_band`; `Loss-Making Line %` | 0% at full price → 100% above 50% discount |
| 2.6 | Table | `product_label`, `sub_category`, `Total Revenue`, `Total Profit`, `Profit Margin %`, `Average Discount %`, filtered to `profit_quadrant = "2 High revenue / LOW profit"` | The specific products to reprice or delist |
| 2.7 | Bar (top/bottom 10) | `product_label`; `Total Profit` | Best and worst products by profit |
| 2.8 | Line | `year_month_label`; `Total Revenue` by `category` | Category trends over time |

Set 2.3, 2.4 and 2.5 side by side. Read together they are the whole discount
argument: margin collapses, volume does not respond, and the loss rate goes from
zero to total.

---

## Page 3 — Customer Analytics

**Question: who is valuable, who is disengaging, and is revenue concentrated?**

### KPI row

`Total Customers` · `Repeat Customers` · `One-Time Customers` ·
`Repeat Purchase Rate %` · `Revenue per Customer` · `Orders per Customer` ·
`Unprofitable Customers` · `Top 20% Customer Revenue Share %`

> Three of these are **deliberately degenerate on this dataset**, and showing them
> is the honest choice: `One-Time Customers` = 0, `Repeat Purchase Rate %` = 100%,
> and `New Customers` = 0 in every year after 2011. All 795 customers were acquired
> in 2011 and each placed 15–47 orders. A dashboard that hid these would imply the
> metrics were meaningful.

### Visuals

| # | Visual | Fields | Question |
|---|---|---|---|
| 3.1 | Bar | `dim_customer[segment]`; `Total Customers` | How does the base split by RFM? |
| 3.2 | Clustered bar | `segment`; `% of customers` vs `% of revenue` | Which segments punch above their weight? |
| 3.3 | Scatter | X `dim_customer[days_since_last_purchase]`, Y `lifetime_revenue`, legend `segment` | Recency versus value |
| 3.4 | Histogram | `dim_customer[lifetime_revenue]` binned | Is the value distribution long-tailed? *(No — near-symmetric.)* |
| 3.5 | Line | Cumulative % customers vs cumulative % revenue, with a 45° reference line | **Does the 80/20 rule hold?** *(No — Gini 0.18, top 20% hold 30%.)* |
| 3.6 | Matrix heatmap | Rows `cohort_month`, columns `Months Since Acquisition`, values `Cohort Retention %` | Does retention decay? *(No.)* |
| 3.7 | Table | `customer_name`, `segment`, `order_frequency`, `lifetime_revenue`, `lifetime_profit`, `segment_action` | Who to act on, and what to do |
| 3.8 | Card (text) | `dim_customer[label_caveat]` for the selected segment | Stops "Lost Customers" being read as churn — median dormancy is 49 days |

**3.6 must carry a subtitle**: *"All cohorts acquired 2011. Because customers order
roughly every six weeks, this shows the probability of purchasing in a month, not
survival. It does not decay (trend −0.21pp/month, p = 0.09)."* Without it, a reader
will interpret a flat heatmap as excellent retention rather than as the wrong tool
for this data.

---

## Page 4 — Operations & Returns

**Question: where do returns and fulfilment delays cluster?**

### KPI row

`Return Rate % (safe)` · `Returned Orders` · `Returned Revenue` ·
`Avg Ship Lag Days` · `Total Shipping Cost` · `Shipping % of Revenue` ·
`Unmeasured Orders`

### Visuals

| # | Visual | Fields | Question |
|---|---|---|---|
| 4.1 | **Card (text), top of page** | `Returns Coverage Note` | Names the 5,037 excluded orders before any rate is read |
| 4.2 | Bar | `market`; `Return Rate % (safe)` | Return rate by market — unmeasured markets render blank |
| 4.3 | Bar | `sub_category`; `Return Rate % (safe)` | **Set the X axis to start at 0%**, so the narrow 6.3–9.1% spread is visible as narrow. An auto-scaled axis manufactures a dramatic ranking out of a 1.44× spread and invents a hotspot that does not exist |
| 4.4 | Bar | `ship_mode`; `Avg Ship Lag Days` | Does ship mode deliver what it promises? *(Yes: 0.04 / 2.19 / 3.22 / 5.00 days.)* |
| 4.5 | Column | `ship_lag_days`; `Total Orders` | Distribution of fulfilment speed (0–7 days) |
| 4.6 | Bar | `market`; `Shipping % of Revenue` | Where is shipping disproportionate? |
| 4.7 | Bar | `discount_band`; `Return Rate % (safe)` | Do discounted orders come back more? |
| 4.8 | Table | `order_priority`; `Total Orders`, `Avg Ship Lag Days`, `Return Rate % (safe)` | Is priority honoured? |

### Omitted from this page, and why

| Brief asked for | Status |
|---|---|
| Cancellation rate | **Omitted** — no order status field exists; there is no cancelled state to count |
| Payment-method analysis | **Omitted** — no payment field exists |
| Return reasons | **Omitted** — the Returns sheet records only *whether* an order was returned, never why |
| Average delivery time | **Substituted** — reported as order-to-ship lag; no delivery date exists |
| Late-delivery rate | **Substituted** — measured against each ship mode's own average, an internal benchmark and explicitly not an SLA |

---

## Design rules

Applying the brief's section 16 requirements:

- **Type**: Segoe UI. 28pt page titles, 12pt visual titles, 10pt labels. KPI card
  values 32pt semibold.
- **Colour**: one accent (`#1F4E79` navy), one secondary (`#2E8B8B` teal), one
  negative (`#C0563F` red) reserved *exclusively* for loss and returns. Neutral
  greys elsewhere. Never colour by category for its own sake.
- **Number formats**: currency `$#,0` (`$#,0,,"M"` on cards), percentages one
  decimal, counts `#,0`. Consistent on every page.
- **Grid**: 12-column, 8px gutters. KPI row 100px tall across the top; visuals in
  two rows beneath.
- **Banned**: 3D, gauges, donuts more than one ring deep, decorative images,
  background images, drop shadows, animated transitions.
- **Axes**: always start value axes at zero for bar charts. Visual 4.3 exists
  specifically because a non-zero axis would misrepresent a narrow spread.
- **Every chart has a title stating its finding**, not just its fields — "Margin
  collapses above 20% discount", not "Profit Margin % by discount_band".

### Release Candidate`r`nThe dashboard specification was finalized for the final presentation package.

