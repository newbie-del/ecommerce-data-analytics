# Business Insights — Global Superstore, 2011–2014

**Prepared from:** 51,290 order lines · 25,754 orders · 795 customers · 147 countries ·
January 2011 – December 2014
**Source:** the real Tableau *Global Superstore* extract (see `PROJECT_PROVENANCE.txt`)
**Verification:** every figure in this report is asserted by `src/verify_claims.py`
— 178 checks, 0 failures

---

## Executive summary

The business grew revenue **90%** in four years, from \$2.26M to \$4.30M, with growth
*accelerating* (18.5% → 27.2% → 26.3%). Profit margin, however, never left the
**11.0%–12.0%** band. Growth is being bought rather than earned.

The reason is specific and fixable. **Discounting is destroying margin without buying
any volume.** \$2.36M — 15.8% of list revenue — was given away over four years. The
rank correlation between discount and units sold is **+0.018**; effectively zero.
Meanwhile, of order lines sold at full price **0.0% lose money**, and of lines
discounted above 50%, **100% lose money**.

Three conventional retail conclusions are **not supported** by this data, and acting
on them would waste effort:

- There is no loss-making region or market to exit — all 13 regions and all 7 markets
  are profitable.
- There is no top-20% of customers to protect — they hold 30% of revenue, not 80%.
- There is no returns hotspot to root-cause — every sub-category sits in a narrow
  6.3%–9.1% band.

The single recoverable sum is the discount give-away. Everything else is second order.

---

## 1. Growth is real; unit economics are not improving

| Year | Revenue | Profit | Margin | Growth |
|---|---:|---:|---:|---:|
| 2011 | \$2,259,451 | \$248,941 | 11.02% | — |
| 2012 | \$2,677,439 | \$307,415 | 11.48% | +18.5% |
| 2013 | \$3,405,746 | \$406,935 | 11.95% | +27.2% |
| 2014 | \$4,299,866 | \$504,166 | 11.73% | +26.3% |

Revenue nearly doubled and every single one of the 48 months was profitable. But
margin moved less than one percentage point across four years of near-doubling scale.
Whatever is constraining profitability is structural, not cyclical — it scaled
proportionally with the business.

Revenue is seasonal: a pronounced November–December peak and a February trough.
December was the annual peak in 2011, 2012 and 2013 — but **November** in 2014, so
capacity planning should not assume December is always the maximum.

---

## 2. The discount problem — the central finding

**\$2,363,988 (15.75% of list revenue) was given away as discount.**

What it bought, by band:

| Discount band | Lines | Avg units/line | Revenue | Profit | Margin | Lines losing money |
|---|---:|---:|---:|---:|---:|---:|
| 0% (none) | 29,009 | 3.40 | \$6,992,411 | \$1,770,695 | **+25.3%** | **0.0%** |
| 1–10% | 4,679 | 3.76 | \$1,962,619 | \$338,189 | +17.2% | 19.3% |
| 11–20% | 6,274 | 3.73 | \$1,757,261 | \$173,255 | +9.9% | 23.3% |
| 21–30% | 967 | 3.81 | \$382,555 | −\$21,156 | **−5.5%** | 62.2% |
| 31–50% | 6,189 | 3.72 | \$1,176,031 | −\$380,945 | −32.4% | 87.4% |
| 51%+ | 4,172 | **2.84** | \$371,625 | −\$412,582 | **−111.0%** | **100.0%** |

Three things to take from this table:

1. **Volume does not respond.** Units per line are flat between 3.40 and 3.81 from
   0% to 50% discount. Above 50% they *fall* to 2.84 — the deepest discounts are
   attached to the *smallest* baskets. Confirmed independently by Spearman
   correlation: ρ(discount, quantity) = **+0.018**, ρ(discount, margin) = **−0.67**.

2. **The crossover is between 11–20% and 21–30%.** Below it the business makes money;
   above it, it does not. This is a threshold, not a gradient.

3. **The loss is entirely a discount phenomenon.** 0.0% of full-price lines lose
   money; 100% of lines above 50% do. The 24.5% of all order lines that are
   unprofitable (12,544 lines, −\$920,646) are not a random tail — they are the
   discounted ones.

**Everything above the 20% band together carries \$1,930,211 of revenue and
−\$814,682 of profit.**

---

## 3. Products: 1,380 of them are scaling a loss

Classifying all 10,292 products against median product revenue:

| Quadrant | Products | Revenue | Profit | Margin | Avg discount |
|---|---:|---:|---:|---:|---:|
| High revenue / High profit | 3,766 | \$8,660,218 | \$1,844,902 | +21.3% | 10.7% |
| **High revenue / LOW profit** | **1,380** | **\$3,037,191** | **−\$461,720** | **−15.2%** | **23.0%** |
| Low revenue / High margin | 3,595 | \$690,157 | \$166,853 | +24.2% | 10.1% |
| Low revenue / Low profit | 1,551 | \$254,937 | −\$82,577 | −32.4% | 35.5% |

The dangerous quadrant carries **24.0% of all revenue** while destroying \$462K of
profit. Its average discount is **2.15×** that of the healthy high-revenue quadrant
(23.0% vs 10.7%) — the same discount story, now visible at product level.

**An important distinction for the action:** a product that loses money overall but is
profitable on its full-price lines is a *pricing-policy* failure, not a bad product.
Those should have discount withdrawn, not be delisted. `sql/product_analysis.sql`
query P8 isolates exactly that set.

Only **one sub-category destroys value outright**: **Tables**, at −\$64,083 on
\$757,042 of revenue (−8.5% margin).

---

## 4. Geography: nothing to exit, but margins vary 13×

**All 13 regions and all 7 markets are profitable.** There is no footprint decision
to make here. The variation is in margin quality:

| Weakest by margin | Revenue | Profit | Margin |
|---|---:|---:|---:|
| Southeast Asia | \$884,423 | \$17,852 | **2.02%** |
| EMEA | \$806,161 | \$43,898 | 5.45% |
| South | \$1,600,907 | \$140,356 | 8.77% |
| LATAM (market) | \$2,164,605 | \$221,643 | 10.24% |

Compare Canada: the **smallest** absolute profit (\$17,817) but the **highest** margin
(26.62%). Ranking regions by absolute profit would have flagged the single healthiest
region as the weakest — which is why `sql/sales_analysis.sql` query S7b ranks by
margin and shows both ranks side by side.

Southeast Asia at 2.02% is the priority: substantial revenue, almost no profit.

---

## 5. Customers: the 80/20 rule does not hold

| Metric | Value |
|---|---|
| Customers | 795 |
| Gini coefficient | **0.180** |
| Top 10% share of revenue | 16.5% |
| Top 20% share of revenue | **30.0%** (not ~80%) |
| Lifetime revenue range | \$3,892 – \$40,488 (≈10×) |
| Net unprofitable customers | **67** (8.4%) |

Revenue is close to evenly spread. There is no whale segment to defend, so the
standard "identify and protect your top 20%" strategy has nothing to attach to here.
Value must come from product and discount economics, which reach every customer at
once.

The **67 unprofitable customers** are the exception worth acting on individually —
they generate real revenue but absorb enough discount and shipping to cost more than
they contribute. The action is commercial terms (minimum order values, shipping
recovery, discount withdrawal), not retention marketing.

### What this dataset cannot tell us about customers

This is a **closed 795-customer panel**, not an acquisition funnel, and four
requested metrics are structurally uninformative as a result:

| Metric | Value here | Why it carries no information |
|---|---|---|
| One-time customers | **0** | Every customer placed 15–47 orders (median 32) |
| Repeat purchase rate | **100%** | Follows directly from the above |
| New vs returning | **0 new after 2011** | All 795 customers were acquired during 2011 |
| Churn / "Lost" customers | **1 customer** dormant >180 days | Median dormancy is 16 days; there is no churn signal to model |

These are reported rather than hidden. A dashboard showing "100% repeat purchase
rate" as an achievement would be misleading; it is an artefact of how the dataset was
assembled.

**RFM segments are therefore relative positions within this panel, not churn
states.** "Lost Customers" here means a median of 49 days since last order. The
segment labels ship with their actual ranges attached (`data/processed/rfm_segments.csv`,
column `label_caveat`) for exactly this reason.

| Segment | Customers | % of revenue | Avg orders | Median dormancy |
|---|---:|---:|---:|---:|
| Champions | 116 | 19.6% | 37.6 | 5 days |
| Loyal Customers | 168 | 23.6% | 34.7 | 12 days |
| Potential Loyalists | 193 | 18.1% | 28.3 | 9 days |
| New Customers | **0** | — | — | — |
| At Risk | 159 | 20.0% | 32.8 | 28 days |
| Lost Customers | 159 | 18.7% | 30.8 | 49 days |

---

## 6. Retention does not decay — and that is a finding about the data

Across 47 post-acquisition months the retention trend is **−0.21 percentage points per
month with p = 0.09** — not significant at the 5% level. Mean retention is **43.8%**,
against a Poisson expectation of **~49%** derived from the average purchase rate of
0.67 orders per month.

Those figures agreeing in magnitude is the point: the cohort grid is measuring **how
often customers happen to buy in a given month**, not whether they survive. With ~32
orders spread over 48 months, a customer orders roughly every six weeks, so any
single month is a coin-flip regardless of loyalty.

**Cohort retention is the wrong instrument for this dataset.** Presenting a flat
heatmap as evidence of excellent retention would be a misreading, and presenting a
decay curve would require inventing one.

---

## 7. Operations: no hotspot in either returns or fulfilment

### Returns — 5.81% of orders, uniformly

| Scope | Orders | Return rate |
|---|---:|---:|
| Measured markets (APAC, EU, LATAM, US) | 20,717 | **5.81%** (1,203 orders) |
| Africa, Canada, EMEA | 5,037 | **unknown — not 0%** |

The source Returns sheet has **no records at all** for Africa, Canada and EMEA. Those
5,037 orders are excluded from every rate rather than counted as clean. Including them
would dilute the reported rate from 5.81% to **4.67%** — an understatement of 1.14
percentage points — and invent a flawless returns record for three markets that were
never measured.

Where returns *are* measured, they are strikingly uniform:

- **By market:** 5.44% (APAC) – 6.11% (EU), a spread of just **1.12×**
- **By sub-category:** 6.33% – 9.10% across all 17 — a worst-to-best ratio of
  **1.44×**

**There is no returns hotspot.** A root-cause programme aimed at "the worst category"
would be chasing a 1.44× spread, which is noise. Returns here read as a systemic cost
of trading (\$818,044 of revenue on returned orders), not a product-quality failure
concentrated somewhere.

### Fulfilment — working as designed

Order-to-ship lag runs 0–7 days, and each ship mode behaves exactly as labelled:

| Ship mode | Avg days | Range | Orders |
|---|---:|---|---:|
| Same Day | 0.04 | 0–1 | 1,349 |
| First Class | 2.19 | 1–3 | 3,847 |
| Second Class | 3.22 | 2–5 | 5,146 |
| Standard Class | 5.00 | 4–7 | 15,412 |

Ship lag correlates with essentially nothing, including profitability. Fulfilment is
not a problem in this business, and operational effort spent speeding it up would not
show up in margin.

Shipping costs \$1,352,816 — **10.70% of revenue**, which is material and worth
watching, particularly in the markets where it is disproportionate.

---

## 8. Recommendations

| # | Action | Evidence | Expected effect |
|---|---|---|---|
| 1 | **Cap discounts at 20%.** | Margin +25.3% → −111.0% across the bands; loss rate 0.0% → 100.0% | The largest lever available. Bands above 20% carry \$1.93M revenue at **−\$815K** profit |
| 2 | **Run a controlled discount test first.** Hold discount flat on a random half of one category for a quarter; measure *units*, not revenue. | ρ = +0.018 is observational; causation is not established | Turns a correlation into a decision-grade result before a pricing change goes global |
| 3 | **Split the 1,380 loss-making high-revenue products into two actions:** withdraw discount where full-price lines are profitable; reprice or delist the rest. | 24.0% of revenue, −\$462K profit, 2.15× the discount of healthy peers | Removes the largest product-level loss without cutting viable products |
| 4 | **Fix Tables. Do not exit any region.** Review Southeast Asia (2.02%) and EMEA (5.45%) on margin. | 1 negative sub-category; **0** negative regions or markets | Removes a contained \$64K loss and avoids an unjustified retreat |
| 5 | **Do not build strategy on customer tiering.** | Gini 0.18; top 20% hold 30% | Avoids funding a segmentation this data does not support |
| 6 | **Put the 67 unprofitable customers on commercial review.** | Negative lifetime profit despite real revenue | Converts a known drain toward break-even |
| 7 | **Treat returns as a priced-in cost, not an investigation.** | 1.44× spread across all sub-categories; no market outlier | Prevents a root-cause programme that would find nothing |
| 8 | **Instrument what is missing before the next review:** payment method, order status and cancellations, delivery dates, and returns in Africa/Canada/EMEA. | Four brief questions were unanswerable; 5,037 orders have no returns data | Makes the next cycle answerable rather than caveated |

---

## 9. What this analysis deliberately did not do

Stated because the omissions are as much a part of the result as the findings:

| Not done | Reason |
|---|---|
| Payment-method analysis | No payment field exists in the dataset |
| Cancellation rate | No order status field exists; there is no cancelled state to count |
| Return reasons | The Returns sheet records *whether*, never *why* |
| Delivery time / late-delivery rate | Only a **ship** date exists; reported as order-to-ship lag under that name |
| Return rate for Africa, Canada, EMEA | No return records for those markets — reported as unknown, never as 0% |
| Customer demographics | No gender or age field exists |
| Predictive churn model | One customer is dormant beyond 180 days; there is no usable churn label to train on |
| Shipping netted into profit | Cannot determine from this extract whether shipping is already inside the recorded profit. Reported separately; never double-counted |
| DAX engine validation | Dashboard PBIP and screenshots are built, but the independent source of truth remains the Python/SQL verifier until the opened Power BI model is checked against the expected measures |

Each of these could have been approximated into something that looked complete. None
of them would have been true.
