-- ===========================================================================
--  E-COMMERCE ANALYTICS  |  CUSTOMER ANALYSIS
-- ===========================================================================
--  Business questions answered here:
--    C1  Top customers by revenue and by profit
--    C2  Repeat vs one-time customers
--    C3  Average customer order value and purchase frequency
--    C4  RFM scoring and segmentation, computed independently in SQL
--    C5  Segment profile with the actual ranges behind each label
--    C6  Acquisition cohorts and retention
--    C7  Unprofitable customers
--    C8  Customers whose spend is falling year on year
--
--  TWO THINGS THIS FILE DOES DELIBERATELY
--  --------------------------------------
--  1. It groups on customer_key, never customer_id. Every one of the 795 people
--     in this dataset has TWO customer_ids, so COUNT(DISTINCT customer_id)
--     returns 1,590 and every per-customer average is then wrong by half.
--
--  2. It computes RFM from scratch rather than reading rfm_segments.csv, so the
--     SQL layer is an independent reproduction of src/rfm_analysis.py. Note that
--     NTILE and pandas qcut break ties differently, so segment counts may differ
--     by a customer or two at quintile boundaries; the aggregate totals agree
--     exactly. That is expected, and better acknowledged than papered over.
--
--  RECENCY WITHOUT DATE FUNCTIONS
--  ------------------------------
--  Ranking customers by MAX(order_date) descending is monotonically identical to
--  ranking by days-since-last-purchase, so the quintiles are the same while the
--  SQL stays portable. Exact day counts live in data/processed/rfm_segments.csv.
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- C1a. Top 15 customers by revenue.
-- ---------------------------------------------------------------------------
SELECT
    customer_key,
    MIN(customer_name)                                      AS customer_name,
    MIN(customer_segment)                                   AS segment,
    COUNT(DISTINCT customer_id)                             AS raw_ids_merged,
    COUNT(DISTINCT order_key)                               AS orders,
    SUM(quantity)                                           AS units,
    ROUND(SUM(revenue), 2)                                  AS lifetime_revenue,
    ROUND(SUM(profit), 2)                                   AS lifetime_profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct,
    ROUND(SUM(revenue) / NULLIF(COUNT(DISTINCT order_key), 0), 2) AS avg_order_value
FROM fact_order_lines
GROUP BY customer_key
ORDER BY lifetime_revenue DESC
LIMIT 15;


-- ---------------------------------------------------------------------------
-- C1b. Top 15 by profit. Compare with C1a: revenue leaders are not the profit
-- leaders, because the discount they attract differs.
-- ---------------------------------------------------------------------------
SELECT
    customer_key,
    MIN(customer_segment)                                   AS segment,
    COUNT(DISTINCT order_key)                               AS orders,
    ROUND(SUM(revenue), 2)                                  AS lifetime_revenue,
    ROUND(SUM(profit), 2)                                   AS lifetime_profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct,
    ROUND(AVG(discount), 4)                                 AS avg_discount
FROM fact_order_lines
GROUP BY customer_key
ORDER BY lifetime_profit DESC
LIMIT 15;


-- ---------------------------------------------------------------------------
-- C2. Repeat vs one-time customers.
--
-- On this dataset the answer is degenerate and that is the finding: there are
-- ZERO one-time customers. Every customer placed at least 15 orders, so
-- "repeat purchase rate" is 100% and carries no information. The query is kept
-- because the brief asks for it, and the empty bucket is the honest answer.
-- ---------------------------------------------------------------------------
WITH per_customer AS (
    SELECT customer_key,
           COUNT(DISTINCT order_key) AS orders,
           SUM(revenue)              AS revenue
    FROM fact_order_lines
    GROUP BY customer_key
)
SELECT
    CASE WHEN orders = 1 THEN 'One-time (1 order)'
         WHEN orders BETWEEN 2 AND 9   THEN 'Occasional (2-9)'
         WHEN orders BETWEEN 10 AND 29 THEN 'Regular (10-29)'
         ELSE 'Frequent (30+)' END                          AS customer_type,
    COUNT(*)                                                AS customers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)      AS pct_of_customers,
    ROUND(SUM(revenue), 2)                                  AS revenue,
    ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 2) AS pct_of_revenue,
    MIN(orders)                                             AS min_orders,
    MAX(orders)                                             AS max_orders
FROM per_customer
GROUP BY customer_type
ORDER BY min_orders;


-- ---------------------------------------------------------------------------
-- C3. Purchase frequency and order value distribution across the base.
-- ---------------------------------------------------------------------------
WITH per_customer AS (
    SELECT
        customer_key,
        MIN(customer_segment)     AS segment,
        COUNT(DISTINCT order_key) AS orders,
        SUM(revenue)              AS revenue,
        SUM(profit)               AS profit
    FROM fact_order_lines
    GROUP BY customer_key
)
SELECT
    segment,
    COUNT(*)                                                AS customers,
    ROUND(AVG(orders), 2)                                   AS avg_orders_per_customer,
    MIN(orders)                                             AS min_orders,
    MAX(orders)                                             AS max_orders,
    ROUND(AVG(revenue), 2)                                  AS avg_lifetime_revenue,
    ROUND(AVG(revenue / NULLIF(orders, 0)), 2)              AS avg_order_value,
    ROUND(SUM(revenue), 2)                                  AS total_revenue,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct
FROM per_customer
GROUP BY segment
ORDER BY total_revenue DESC;


-- ---------------------------------------------------------------------------
-- C4. RFM scoring, computed in SQL.
--
-- R: NTILE over MAX(order_date) DESC, then inverted so 5 = most recent.
-- F: NTILE over order count, 5 = most frequent.
-- M: NTILE over lifetime revenue, 5 = highest spend.
--
-- The "New Customers" rule is gated on FIRST purchase date, not on low
-- frequency. That matters: a frequency-based rule labels ~91 customers here as
-- "new" who were all acquired in 2011 with 17-31 orders each. Tenure-gating
-- correctly returns zero, and the empty segment is the truthful result.
-- ---------------------------------------------------------------------------
WITH per_customer AS (
    SELECT
        customer_key,
        MIN(customer_segment)      AS segment,
        MIN(order_date)            AS first_order_date,
        MAX(order_date)            AS last_order_date,
        COUNT(DISTINCT order_key)  AS frequency,
        SUM(revenue)               AS monetary,
        SUM(profit)                AS profit
    FROM fact_order_lines
    GROUP BY customer_key
),
bounds AS (
    SELECT MAX(last_order_date) AS snapshot_date FROM per_customer
),
scored AS (
    SELECT
        c.*,
        6 - NTILE(5) OVER (ORDER BY c.last_order_date DESC) AS r_score,
        NTILE(5) OVER (ORDER BY c.frequency ASC)            AS f_score,
        NTILE(5) OVER (ORDER BY c.monetary  ASC)            AS m_score
    FROM per_customer c
),
segmented AS (
    SELECT
        s.*,
        b.snapshot_date,
        (s.f_score + s.m_score) / 2.0 AS fm_score,
        CASE
            -- Tenure gate first: only a genuinely recent acquisition is "new".
            WHEN s.first_order_date >= '2014-10-02'                       THEN 'New Customers'
            WHEN s.r_score >= 4 AND (s.f_score + s.m_score) / 2.0 >= 4    THEN 'Champions'
            WHEN s.r_score >= 3 AND (s.f_score + s.m_score) / 2.0 >= 3    THEN 'Loyal Customers'
            WHEN s.r_score >= 3                                          THEN 'Potential Loyalists'
            WHEN s.r_score = 2                                           THEN 'At Risk'
            ELSE 'Lost Customers'
        END AS segment_name
    FROM scored s
    CROSS JOIN bounds b
)
SELECT
    customer_key,
    segment,
    first_order_date,
    last_order_date,
    frequency,
    ROUND(monetary, 2) AS monetary,
    r_score,
    f_score,
    m_score,
    (r_score + f_score + m_score) AS rfm_sum,
    segment_name
FROM segmented
ORDER BY monetary DESC
LIMIT 25;


-- ---------------------------------------------------------------------------
-- C5. Segment profile - size, value, and the ACTUAL ranges behind each label.
--
-- The min/max columns are not padding. "Lost Customers" here spans a last-order
-- date only months before the snapshot, not years; publishing the label without
-- its range is how a relative quintile turns into a false churn claim.
-- ---------------------------------------------------------------------------
WITH per_customer AS (
    SELECT
        customer_key,
        MIN(order_date)           AS first_order_date,
        MAX(order_date)           AS last_order_date,
        COUNT(DISTINCT order_key) AS frequency,
        SUM(revenue)              AS monetary,
        SUM(profit)               AS profit
    FROM fact_order_lines
    GROUP BY customer_key
),
scored AS (
    SELECT
        c.*,
        6 - NTILE(5) OVER (ORDER BY c.last_order_date DESC) AS r_score,
        NTILE(5) OVER (ORDER BY c.frequency ASC)            AS f_score,
        NTILE(5) OVER (ORDER BY c.monetary  ASC)            AS m_score
    FROM per_customer c
),
segmented AS (
    SELECT
        s.*,
        CASE
            WHEN s.first_order_date >= '2014-10-02'                       THEN 'New Customers'
            WHEN s.r_score >= 4 AND (s.f_score + s.m_score) / 2.0 >= 4    THEN 'Champions'
            WHEN s.r_score >= 3 AND (s.f_score + s.m_score) / 2.0 >= 3    THEN 'Loyal Customers'
            WHEN s.r_score >= 3                                          THEN 'Potential Loyalists'
            WHEN s.r_score = 2                                           THEN 'At Risk'
            ELSE 'Lost Customers'
        END AS segment_name
    FROM scored s
)
SELECT
    segment_name,
    COUNT(*)                                                   AS customers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)         AS pct_of_customers,
    ROUND(SUM(monetary), 2)                                    AS revenue,
    ROUND(100.0 * SUM(monetary) / SUM(SUM(monetary)) OVER (), 2) AS pct_of_revenue,
    ROUND(AVG(monetary), 2)                                    AS avg_revenue,
    ROUND(AVG(frequency), 1)                                   AS avg_orders,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(monetary), 0), 2)   AS margin_pct,
    MIN(last_order_date)                                       AS earliest_last_order,
    MAX(last_order_date)                                       AS latest_last_order,
    MIN(frequency)                                             AS min_orders,
    MAX(frequency)                                             AS max_orders,
    SUM(CASE WHEN profit < 0 THEN 1 ELSE 0 END)                AS unprofitable_customers
FROM segmented
GROUP BY segment_name
ORDER BY revenue DESC;


-- ---------------------------------------------------------------------------
-- C6. Acquisition cohorts and retention.
--
-- The month offset is computed from the precomputed integer year and month
-- columns - (year*12 + month) arithmetic - so no engine-specific date function
-- is needed.
--
-- Read the result knowing what it measures: all 795 customers were acquired in
-- 2011 and each orders roughly every six weeks, so this grid shows the
-- PROBABILITY OF PURCHASING in a given month, not survival. It does not decay.
-- ---------------------------------------------------------------------------
WITH first_order AS (
    SELECT
        customer_key,
        MIN(order_year * 12 + order_month) AS cohort_index,
        MIN(order_ym)                      AS cohort_month
    FROM fact_order_lines
    GROUP BY customer_key
),
activity AS (
    SELECT DISTINCT
        f.cohort_month,
        f.customer_key,
        (l.order_year * 12 + l.order_month) - f.cohort_index AS period_index
    FROM fact_order_lines l
    JOIN first_order f ON f.customer_key = l.customer_key
),
cohort_size AS (
    SELECT cohort_month, COUNT(DISTINCT customer_key) AS cohort_customers
    FROM activity
    WHERE period_index = 0
    GROUP BY cohort_month
)
SELECT
    a.cohort_month,
    s.cohort_customers,
    a.period_index                                                AS months_since_acquisition,
    COUNT(DISTINCT a.customer_key)                                AS active_customers,
    ROUND(100.0 * COUNT(DISTINCT a.customer_key)
          / NULLIF(s.cohort_customers, 0), 2)                     AS retention_pct
FROM activity a
JOIN cohort_size s ON s.cohort_month = a.cohort_month
WHERE a.period_index <= 12
GROUP BY a.cohort_month, s.cohort_customers, a.period_index
ORDER BY a.cohort_month, a.period_index;


-- ---------------------------------------------------------------------------
-- C7. Unprofitable customers - real revenue, negative profit.
--
-- These absorb enough discount and shipping to cost more than they contribute.
-- The action is commercial terms, not churn prevention.
-- ---------------------------------------------------------------------------
SELECT
    customer_key,
    MIN(customer_segment)                                   AS segment,
    MIN(market)                                             AS primary_market,
    COUNT(DISTINCT order_key)                               AS orders,
    ROUND(SUM(revenue), 2)                                  AS lifetime_revenue,
    ROUND(SUM(profit), 2)                                   AS lifetime_profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct,
    ROUND(AVG(discount), 4)                                 AS avg_discount,
    ROUND(SUM(shipping_cost), 2)                            AS shipping_cost,
    SUM(is_loss_making)                                     AS loss_making_lines
FROM fact_order_lines
GROUP BY customer_key
HAVING SUM(profit) < 0
ORDER BY lifetime_profit ASC;


-- ---------------------------------------------------------------------------
-- C8. Customers whose spend is declining - the closest this dataset gets to a
-- churn-risk signal.
--
-- Compares each customer's final observed year against their previous year.
-- This is a genuine behavioural signal, unlike the RFM "Lost" label, because it
-- measures a change in spend rather than a position in a quintile.
-- ---------------------------------------------------------------------------
WITH by_year AS (
    SELECT customer_key, order_year, SUM(revenue) AS revenue
    FROM fact_order_lines
    GROUP BY customer_key, order_year
),
with_prior AS (
    SELECT
        customer_key,
        order_year,
        revenue,
        LAG(revenue) OVER (PARTITION BY customer_key ORDER BY order_year) AS prior_year_revenue
    FROM by_year
)
SELECT
    customer_key,
    order_year                                              AS latest_year,
    ROUND(prior_year_revenue, 2)                            AS prior_year_revenue,
    ROUND(revenue, 2)                                       AS latest_year_revenue,
    ROUND(revenue - prior_year_revenue, 2)                  AS change,
    ROUND(100.0 * (revenue - prior_year_revenue)
          / NULLIF(prior_year_revenue, 0), 2)               AS change_pct
FROM with_prior
WHERE order_year = 2014
  AND prior_year_revenue IS NOT NULL
  AND revenue < prior_year_revenue * 0.5     -- spend at least halved
ORDER BY change ASC
LIMIT 25;
