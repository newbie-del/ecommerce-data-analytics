-- ===========================================================================
--  E-COMMERCE ANALYTICS  |  SALES ANALYSIS
-- ===========================================================================
--  Business questions answered here:
--    S1  What is total revenue, cost, profit and margin?
--    S2  How does revenue trend month by month?
--    S3  What is month-on-month growth?
--    S4  What is year-on-year growth, by month and by year?
--    S5  Which categories generate revenue vs profit?
--    S6  Which sub-categories generate revenue vs profit?
--    S7  Which regions and markets perform best?
--    S8  How much revenue is given away as discount, and what does it buy?
--    S9  Is there a seasonal pattern?
--
--  Run after 00_schema.sql and after fact_order_lines is populated.
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- S1. Headline totals.
--
-- COUNT(DISTINCT order_key), not order_id: see the GRAIN note in 00_schema.sql.
-- Using order_id understates the order count by 719 and inflates AOV by 2.9%.
-- NULLIF guards the division even though revenue is never zero here.
-- ---------------------------------------------------------------------------
SELECT
    COUNT(*)                                        AS order_lines,
    COUNT(DISTINCT order_key)                       AS orders,
    COUNT(DISTINCT customer_key)                    AS customers,
    COUNT(DISTINCT product_id)                      AS products,
    SUM(quantity)                                   AS units,
    ROUND(SUM(revenue), 2)                          AS revenue,
    ROUND(SUM(cost), 2)                             AS cost,
    ROUND(SUM(profit), 2)                           AS profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2)      AS margin_pct,
    ROUND(SUM(revenue) / NULLIF(COUNT(DISTINCT order_key), 0), 2) AS avg_order_value,
    ROUND(SUM(discount_amount), 2)                  AS discount_given,
    ROUND(SUM(shipping_cost), 2)                    AS shipping_cost
FROM fact_order_lines;


-- ---------------------------------------------------------------------------
-- S2 + S3. Monthly revenue with month-on-month growth.
--
-- LAG over an ordered month series gives the prior month without a self-join.
-- The series is gapless (48 consecutive months, asserted in Python), which is
-- what makes a positional lag safe here - on a series with holes, LAG(1) would
-- silently compare non-adjacent months.
-- ---------------------------------------------------------------------------
WITH monthly AS (
    SELECT
        order_ym,
        COUNT(DISTINCT order_key)   AS orders,
        COUNT(DISTINCT customer_key) AS active_customers,
        SUM(quantity)               AS units,
        SUM(revenue)                AS revenue,
        SUM(profit)                 AS profit
    FROM fact_order_lines
    GROUP BY order_ym
)
SELECT
    order_ym,
    orders,
    active_customers,
    units,
    ROUND(revenue, 2)                                       AS revenue,
    ROUND(profit, 2)                                        AS profit,
    ROUND(100.0 * profit / NULLIF(revenue, 0), 2)           AS margin_pct,
    ROUND(LAG(revenue) OVER (ORDER BY order_ym), 2)         AS prev_month_revenue,
    ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY order_ym))
          / NULLIF(LAG(revenue) OVER (ORDER BY order_ym), 0), 2) AS revenue_mom_pct,
    ROUND(AVG(revenue) OVER (ORDER BY order_ym
              ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS revenue_3mo_avg
FROM monthly
ORDER BY order_ym;


-- ---------------------------------------------------------------------------
-- S4a. Year-on-year growth at month level.
--
-- LAG(..., 12) is the 12-month lag. Again only valid because the series has no
-- gaps; the first 12 months correctly return NULL rather than a wrong number.
-- ---------------------------------------------------------------------------
WITH monthly AS (
    SELECT order_ym, SUM(revenue) AS revenue, SUM(profit) AS profit
    FROM fact_order_lines
    GROUP BY order_ym
)
SELECT
    order_ym,
    ROUND(revenue, 2)                                            AS revenue,
    ROUND(LAG(revenue, 12) OVER (ORDER BY order_ym), 2)          AS revenue_same_month_prior_year,
    ROUND(100.0 * (revenue - LAG(revenue, 12) OVER (ORDER BY order_ym))
          / NULLIF(LAG(revenue, 12) OVER (ORDER BY order_ym), 0), 2) AS revenue_yoy_pct,
    ROUND(100.0 * (profit - LAG(profit, 12) OVER (ORDER BY order_ym))
          / NULLIF(LAG(profit, 12) OVER (ORDER BY order_ym), 0), 2)  AS profit_yoy_pct
FROM monthly
ORDER BY order_ym;


-- ---------------------------------------------------------------------------
-- S4b. Annual summary - the growth-versus-margin story in one result set.
--
-- This is the key sales finding: revenue nearly doubles while margin_pct stays
-- inside a one-point band, so growth is being bought rather than earned.
-- ---------------------------------------------------------------------------
WITH yearly AS (
    SELECT
        order_year,
        COUNT(DISTINCT order_key) AS orders,
        COUNT(DISTINCT customer_key) AS customers,
        SUM(quantity)  AS units,
        SUM(revenue)   AS revenue,
        SUM(profit)    AS profit,
        SUM(discount_amount) AS discount_given
    FROM fact_order_lines
    GROUP BY order_year
)
SELECT
    order_year,
    orders,
    customers,
    units,
    ROUND(revenue, 2)                                     AS revenue,
    ROUND(profit, 2)                                      AS profit,
    ROUND(100.0 * profit / NULLIF(revenue, 0), 2)         AS margin_pct,
    ROUND(revenue / NULLIF(orders, 0), 2)                 AS avg_order_value,
    ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY order_year))
          / NULLIF(LAG(revenue) OVER (ORDER BY order_year), 0), 2) AS revenue_growth_pct,
    ROUND(100.0 * (profit - LAG(profit) OVER (ORDER BY order_year))
          / NULLIF(LAG(profit) OVER (ORDER BY order_year), 0), 2)  AS profit_growth_pct,
    ROUND(100.0 * discount_given / NULLIF(revenue + discount_given, 0), 2) AS discount_pct_of_list
FROM yearly
ORDER BY order_year;


-- ---------------------------------------------------------------------------
-- S5. Category performance, with each category's share of revenue and profit.
--
-- The two shares are shown side by side deliberately: a category whose profit
-- share trails its revenue share is diluting the business, which is invisible
-- if you rank on revenue alone.
-- ---------------------------------------------------------------------------
SELECT
    category,
    COUNT(*)                                                AS order_lines,
    SUM(quantity)                                           AS units,
    ROUND(SUM(revenue), 2)                                  AS revenue,
    ROUND(SUM(profit), 2)                                   AS profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct,
    ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 2) AS pct_of_revenue,
    ROUND(100.0 * SUM(profit)  / SUM(SUM(profit))  OVER (), 2) AS pct_of_profit,
    ROUND(AVG(discount), 4)                                 AS avg_discount,
    SUM(is_loss_making)                                     AS loss_making_lines
FROM fact_order_lines
GROUP BY category
ORDER BY revenue DESC;


-- ---------------------------------------------------------------------------
-- S6. Sub-category performance, ranked worst-profit first.
--
-- Answers "which sub-categories destroy value?" - on this dataset exactly one
-- does (Tables). Ranking ascending puts it at the top rather than burying it.
-- ---------------------------------------------------------------------------
SELECT
    category,
    sub_category,
    COUNT(*)                                                AS order_lines,
    ROUND(SUM(revenue), 2)                                  AS revenue,
    ROUND(SUM(profit), 2)                                   AS profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct,
    ROUND(AVG(discount), 4)                                 AS avg_discount,
    ROUND(100.0 * SUM(is_loss_making) / COUNT(*), 2)        AS pct_lines_losing_money,
    CASE WHEN SUM(profit) < 0 THEN 'DESTROYS VALUE' ELSE 'profitable' END AS verdict
FROM fact_order_lines
GROUP BY category, sub_category
ORDER BY profit ASC;


-- ---------------------------------------------------------------------------
-- S7a. Market performance.
-- ---------------------------------------------------------------------------
SELECT
    market,
    COUNT(DISTINCT order_key)                               AS orders,
    COUNT(DISTINCT customer_key)                            AS customers,
    COUNT(DISTINCT country)                                 AS countries,
    ROUND(SUM(revenue), 2)                                  AS revenue,
    ROUND(SUM(profit), 2)                                   AS profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct,
    ROUND(SUM(revenue) / NULLIF(COUNT(DISTINCT order_key), 0), 2) AS avg_order_value,
    ROUND(100.0 * SUM(shipping_cost) / NULLIF(SUM(revenue), 0), 2) AS shipping_pct_of_revenue,
    ROUND(AVG(discount), 4)                                 AS avg_discount
FROM fact_order_lines
GROUP BY market
ORDER BY revenue DESC;


-- ---------------------------------------------------------------------------
-- S7b. Region performance, ranked by margin rather than absolute profit.
--
-- Ranking by margin is the point: Canada has the SMALLEST absolute profit but
-- the HIGHEST margin, so an absolute-profit ranking would flag the healthiest
-- region as the weakest. The thin-margin regions are the ones to act on.
-- ---------------------------------------------------------------------------
SELECT
    market,
    region,
    COUNT(DISTINCT order_key)                               AS orders,
    ROUND(SUM(revenue), 2)                                  AS revenue,
    ROUND(SUM(profit), 2)                                   AS profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct,
    RANK() OVER (ORDER BY SUM(revenue) DESC)                AS revenue_rank,
    RANK() OVER (ORDER BY 100.0 * SUM(profit)
                          / NULLIF(SUM(revenue), 0) DESC)   AS margin_rank
FROM fact_order_lines
GROUP BY market, region
ORDER BY margin_pct ASC;


-- ---------------------------------------------------------------------------
-- S8. The discount question: does discounting buy volume?
--
-- The decisive columns are avg_units_per_line and pct_lines_losing_money read
-- together. Units stay flat from 0% to 50% and then FALL, while the loss rate
-- goes from 0% to 100%. Revenue bought: none. Margin surrendered: all of it.
-- ---------------------------------------------------------------------------
SELECT
    discount_band,
    COUNT(*)                                                AS order_lines,
    ROUND(AVG(quantity), 3)                                 AS avg_units_per_line,
    ROUND(SUM(revenue), 2)                                  AS revenue,
    ROUND(SUM(list_revenue), 2)                             AS list_revenue,
    ROUND(SUM(discount_amount), 2)                          AS discount_given,
    ROUND(SUM(profit), 2)                                   AS profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct,
    ROUND(100.0 * SUM(is_loss_making) / COUNT(*), 2)        AS pct_lines_losing_money
FROM fact_order_lines
GROUP BY discount_band
ORDER BY MIN(discount);


-- ---------------------------------------------------------------------------
-- S9. Seasonality - calendar month pooled across all four years.
--
-- Pooling years separates a genuine seasonal shape from one freak month. The
-- result: a Nov-Dec peak and a February trough. Note the annual peak is
-- December in 2011-2013 but November in 2014, so "December is always the peak"
-- would have been wrong.
-- ---------------------------------------------------------------------------
SELECT
    order_month,
    COUNT(DISTINCT order_key)                               AS orders,
    ROUND(SUM(revenue), 2)                                  AS revenue,
    ROUND(SUM(profit), 2)                                   AS profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct,
    ROUND(SUM(revenue) / 4.0, 2)                            AS avg_revenue_per_year
FROM fact_order_lines
GROUP BY order_month
ORDER BY order_month;
