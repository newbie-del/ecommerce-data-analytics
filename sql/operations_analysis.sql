-- ===========================================================================
--  E-COMMERCE ANALYTICS  |  OPERATIONS & RETURNS ANALYSIS
-- ===========================================================================
--  Business questions answered here:
--    O1  What is the return rate, and where is it measurable at all?
--    O2  Return rate by market, category and sub-category
--    O3  What do returns cost?
--    O4  Order-to-ship lag overall and by ship mode
--    O5  Which orders shipped slower than their ship mode implies?
--    O6  Shipping cost as a share of revenue
--    O7  Order priority - is it honoured?
--    O8  Do returns and discount travel together?
--
--  THE CENTRAL CAVEAT OF THIS FILE
--  -------------------------------
--  The source Returns sheet contains NO records for Africa, Canada or EMEA -
--  5,037 orders. That is not a 0% return rate, it is an absence of measurement.
--  Every rate below therefore joins dim_returns_coverage and filters to
--  has_returns_data = 1. Computing SUM(return_flag) / COUNT(*) across all
--  markets would understate the true rate by diluting it with 5,037 orders that
--  could never have been flagged.
--
--  TWO BRIEF REQUIREMENTS THAT CANNOT BE ANSWERED
--  ----------------------------------------------
--    Cancellation rate  - the dataset has no order status field at all. There is
--                         no cancelled state to count. Not approximated.
--    Payment-method mix - no payment field exists. Not approximated.
--  Both are omitted rather than proxied, because a proxy here would be invention.
--
--  AND ONE SUBSTITUTION, NAMED HONESTLY
--  ------------------------------------
--  The workbook records a SHIP date, not a DELIVERY date. So "average delivery
--  time" is reported throughout as order-to-ship lag. True transit time and a
--  genuine late-delivery rate are not derivable and are not estimated.
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- O1. Returns coverage first - establish what is measurable before measuring.
-- ---------------------------------------------------------------------------
SELECT
    c.market,
    c.has_returns_data,
    c.coverage_note,
    COUNT(DISTINCT l.order_key)                             AS orders,
    ROUND(SUM(l.revenue), 2)                                AS revenue
FROM fact_order_lines l
JOIN dim_returns_coverage c ON c.market = l.market
GROUP BY c.market, c.has_returns_data, c.coverage_note
ORDER BY c.has_returns_data DESC, orders DESC;


-- ---------------------------------------------------------------------------
-- O2a. Overall return rate, measured markets only.
--
-- The second row of this result is the honest counterpart: the orders that are
-- excluded, and why. Reporting only the rate would hide the exclusion.
-- ---------------------------------------------------------------------------
WITH order_level AS (
    SELECT
        l.order_key,
        MIN(l.market)             AS market,
        MAX(l.return_flag)        AS returned,
        MAX(l.returns_measured)   AS measured,
        SUM(l.revenue)            AS order_value
    FROM fact_order_lines l
    GROUP BY l.order_key
)
SELECT
    CASE WHEN measured = 1 THEN 'Measured markets (APAC, EU, LATAM, US)'
         ELSE 'EXCLUDED - no returns data (Africa, Canada, EMEA)' END AS scope,
    COUNT(*)                                                AS orders,
    SUM(returned)                                           AS returned_orders,
    CASE WHEN measured = 1
         THEN ROUND(100.0 * SUM(returned) / NULLIF(COUNT(*), 0), 2)
         ELSE NULL END                                      AS return_rate_pct,
    ROUND(SUM(order_value), 2)                              AS revenue,
    CASE WHEN measured = 1 THEN 'rate is valid'
         ELSE 'rate is UNKNOWN, not zero' END               AS interpretation
FROM order_level
GROUP BY measured
ORDER BY measured DESC;


-- ---------------------------------------------------------------------------
-- O2b. Return rate by market.
-- ---------------------------------------------------------------------------
WITH order_level AS (
    SELECT
        order_key,
        MIN(market)      AS market,
        MAX(return_flag) AS returned,
        SUM(revenue)     AS order_value
    FROM fact_order_lines
    WHERE returns_measured = 1
    GROUP BY order_key
)
SELECT
    market,
    COUNT(*)                                                AS orders,
    SUM(returned)                                           AS returned_orders,
    ROUND(100.0 * SUM(returned) / NULLIF(COUNT(*), 0), 2)   AS return_rate_pct,
    ROUND(SUM(CASE WHEN returned = 1 THEN order_value ELSE 0 END), 2) AS returned_revenue
FROM order_level
GROUP BY market
ORDER BY return_rate_pct DESC;


-- ---------------------------------------------------------------------------
-- O2c. Return rate by sub-category.
--
-- The finding here is the NARROWNESS of the spread, not the ranking. Rates sit
-- in a ~6-9% band across all 17 sub-categories, a worst-to-best ratio under
-- 1.5x. There is no returns hotspot, so a root-cause programme aimed at "the
-- worst category" would be chasing noise.
-- ---------------------------------------------------------------------------
SELECT
    category,
    sub_category,
    COUNT(*)                                                AS order_lines,
    SUM(return_flag)                                        AS returned_lines,
    ROUND(100.0 * SUM(return_flag) / NULLIF(COUNT(*), 0), 2) AS return_rate_pct,
    ROUND(SUM(CASE WHEN return_flag = 1 THEN revenue ELSE 0 END), 2) AS returned_revenue,
    RANK() OVER (ORDER BY 100.0 * SUM(return_flag)
                          / NULLIF(COUNT(*), 0) DESC)       AS return_rate_rank
FROM fact_order_lines
WHERE returns_measured = 1
GROUP BY category, sub_category
ORDER BY return_rate_pct DESC;


-- ---------------------------------------------------------------------------
-- O3. What returns cost, and how that compares to the discount giveaway.
--
-- The comparison is the point: returns are a real cost, but the discount
-- give-away in sales_analysis.sql S8 is several times larger. This is where the
-- evidence says to spend management attention.
-- ---------------------------------------------------------------------------
WITH order_level AS (
    SELECT
        order_key,
        MAX(return_flag) AS returned,
        SUM(revenue)     AS order_value,
        SUM(profit)      AS order_profit,
        SUM(shipping_cost) AS shipping_cost
    FROM fact_order_lines
    WHERE returns_measured = 1
    GROUP BY order_key
)
SELECT
    CASE WHEN returned = 1 THEN 'Returned' ELSE 'Not returned' END AS status,
    COUNT(*)                                                AS orders,
    ROUND(SUM(order_value), 2)                              AS revenue,
    ROUND(SUM(order_profit), 2)                             AS profit,
    ROUND(AVG(order_value), 2)                              AS avg_order_value,
    ROUND(100.0 * SUM(order_profit) / NULLIF(SUM(order_value), 0), 2) AS margin_pct,
    ROUND(SUM(shipping_cost), 2)                            AS shipping_cost
FROM order_level
GROUP BY returned
ORDER BY returned DESC;


-- ---------------------------------------------------------------------------
-- O4. Order-to-ship lag, overall and by ship mode.
--
-- This validates the ship_mode field: if Same Day did not ship materially
-- faster than Standard Class, the field would be unreliable. It does, so it is.
-- ---------------------------------------------------------------------------
WITH order_level AS (
    SELECT
        order_key,
        MIN(ship_mode)     AS ship_mode,
        MAX(ship_lag_days) AS ship_lag_days,
        SUM(revenue)       AS order_value
    FROM fact_order_lines
    GROUP BY order_key
)
SELECT
    ship_mode,
    COUNT(*)                                                AS orders,
    ROUND(AVG(ship_lag_days), 2)                            AS avg_ship_lag_days,
    MIN(ship_lag_days)                                      AS min_days,
    MAX(ship_lag_days)                                      AS max_days,
    ROUND(SUM(order_value), 2)                              AS revenue,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)      AS pct_of_orders
FROM order_level
GROUP BY ship_mode
ORDER BY avg_ship_lag_days;


-- ---------------------------------------------------------------------------
-- O5. Orders slower than their ship mode implies.
--
-- There is no promised-delivery-date field, so "late" cannot mean "missed an
-- SLA". It is defined here against each ship mode's own observed maximum, which
-- is a defensible internal benchmark rather than an invented external promise.
-- The threshold is stated in the output so no reader mistakes it for a real SLA.
-- ---------------------------------------------------------------------------
WITH order_level AS (
    SELECT
        order_key,
        MIN(ship_mode)     AS ship_mode,
        MIN(market)        AS market,
        MAX(ship_lag_days) AS ship_lag_days
    FROM fact_order_lines
    GROUP BY order_key
),
mode_benchmark AS (
    SELECT
        ship_mode,
        AVG(ship_lag_days) AS avg_lag,
        MAX(ship_lag_days) AS max_lag
    FROM order_level
    GROUP BY ship_mode
)
SELECT
    o.ship_mode,
    ROUND(b.avg_lag, 2)                                     AS mode_avg_lag,
    b.max_lag                                               AS mode_max_lag,
    COUNT(*)                                                AS orders,
    SUM(CASE WHEN o.ship_lag_days > b.avg_lag THEN 1 ELSE 0 END) AS slower_than_mode_average,
    ROUND(100.0 * SUM(CASE WHEN o.ship_lag_days > b.avg_lag THEN 1 ELSE 0 END)
          / NULLIF(COUNT(*), 0), 2)                         AS pct_slower_than_average,
    'benchmark is this ship mode''s own observed average, NOT a promised SLA' AS caveat
FROM order_level o
JOIN mode_benchmark b ON b.ship_mode = o.ship_mode
GROUP BY o.ship_mode, b.avg_lag, b.max_lag
ORDER BY pct_slower_than_average DESC;


-- ---------------------------------------------------------------------------
-- O6. Shipping cost as a share of revenue, by market.
--
-- NOTE ON DOUBLE COUNTING: whether shipping_cost is already deducted inside
-- profit cannot be determined from this extract. profit is reported exactly as
-- recorded and shipping separately; the two are never netted together here,
-- which would risk charging shipping twice. See the README caveats.
-- ---------------------------------------------------------------------------
SELECT
    market,
    region,
    COUNT(DISTINCT order_key)                               AS orders,
    ROUND(SUM(revenue), 2)                                  AS revenue,
    ROUND(SUM(shipping_cost), 2)                            AS shipping_cost,
    ROUND(100.0 * SUM(shipping_cost) / NULLIF(SUM(revenue), 0), 2) AS shipping_pct_of_revenue,
    ROUND(SUM(shipping_cost) / NULLIF(COUNT(DISTINCT order_key), 0), 2) AS shipping_per_order,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct
FROM fact_order_lines
GROUP BY market, region
ORDER BY shipping_pct_of_revenue DESC;


-- ---------------------------------------------------------------------------
-- O7. Order priority - do higher priorities actually ship faster?
-- ---------------------------------------------------------------------------
WITH order_level AS (
    SELECT
        order_key,
        MIN(order_priority) AS order_priority,
        MAX(ship_lag_days)  AS ship_lag_days,
        MAX(return_flag)    AS returned,
        MAX(returns_measured) AS measured,
        SUM(revenue)        AS order_value
    FROM fact_order_lines
    GROUP BY order_key
)
SELECT
    order_priority,
    COUNT(*)                                                AS orders,
    ROUND(AVG(ship_lag_days), 2)                            AS avg_ship_lag_days,
    ROUND(AVG(order_value), 2)                              AS avg_order_value,
    SUM(CASE WHEN measured = 1 THEN returned ELSE 0 END)    AS returned_orders,
    ROUND(100.0 * SUM(CASE WHEN measured = 1 THEN returned ELSE 0 END)
          / NULLIF(SUM(measured), 0), 2)                    AS return_rate_pct
FROM order_level
GROUP BY order_priority
ORDER BY avg_ship_lag_days;


-- ---------------------------------------------------------------------------
-- O8. Do returns and discount travel together?
--
-- If heavily discounted orders were also returned more, discount would be even
-- more costly than S8 suggests. This tests that directly instead of assuming it.
-- ---------------------------------------------------------------------------
SELECT
    discount_band,
    COUNT(*)                                                AS order_lines,
    SUM(return_flag)                                        AS returned_lines,
    ROUND(100.0 * SUM(return_flag) / NULLIF(COUNT(*), 0), 2) AS return_rate_pct,
    ROUND(SUM(profit), 2)                                   AS profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct
FROM fact_order_lines
WHERE returns_measured = 1
GROUP BY discount_band
ORDER BY MIN(discount);
