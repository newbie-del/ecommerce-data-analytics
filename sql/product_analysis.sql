-- ===========================================================================
--  E-COMMERCE ANALYTICS  |  PRODUCT ANALYSIS
-- ===========================================================================
--  Business questions answered here:
--    P1  Top 10 products by revenue
--    P2  Top 10 products by profit
--    P3  Lowest-performing products
--    P4  High revenue but LOW margin - the dangerous quadrant
--    P5  The full four-quadrant classification
--    P6  Category and sub-category profitability with rankings
--    P7  Which brands earn their shelf space?
--    P8  Products whose losses are driven by discount specifically
--
--  A NOTE ON THE PRODUCT KEY
--  -------------------------
--  Aggregation is on product_id, never product_name. 1,944 product names are
--  reused across different ids, and 457 ids carry more than one name. product_id
--  is the better key because it never crosses a category boundary, and
--  product_label supplies one canonical readable name per id. Grouping by name
--  would silently merge unrelated SKUs into a single "product".
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- P1. Top 10 by revenue.
-- ---------------------------------------------------------------------------
SELECT
    product_id,
    MIN(product_label)                                      AS product,
    MIN(category)                                           AS category,
    MIN(sub_category)                                       AS sub_category,
    SUM(quantity)                                           AS units,
    ROUND(SUM(revenue), 2)                                  AS revenue,
    ROUND(SUM(profit), 2)                                   AS profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct,
    ROUND(AVG(discount), 4)                                 AS avg_discount
FROM fact_order_lines
GROUP BY product_id
ORDER BY revenue DESC
LIMIT 10;


-- ---------------------------------------------------------------------------
-- P2. Top 10 by profit. Compare against P1 - the lists differ, which is the
-- whole argument for never ranking a range on revenue.
-- ---------------------------------------------------------------------------
SELECT
    product_id,
    MIN(product_label)                                      AS product,
    MIN(sub_category)                                       AS sub_category,
    SUM(quantity)                                           AS units,
    ROUND(SUM(revenue), 2)                                  AS revenue,
    ROUND(SUM(profit), 2)                                   AS profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct
FROM fact_order_lines
GROUP BY product_id
ORDER BY profit DESC
LIMIT 10;


-- ---------------------------------------------------------------------------
-- P3. The 15 worst products by profit - where money actively leaves.
-- ---------------------------------------------------------------------------
SELECT
    product_id,
    MIN(product_label)                                      AS product,
    MIN(sub_category)                                       AS sub_category,
    COUNT(*)                                                AS order_lines,
    SUM(quantity)                                           AS units,
    ROUND(SUM(revenue), 2)                                  AS revenue,
    ROUND(SUM(profit), 2)                                   AS profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct,
    ROUND(AVG(discount), 4)                                 AS avg_discount,
    ROUND(100.0 * SUM(is_loss_making) / COUNT(*), 2)        AS pct_lines_losing_money
FROM fact_order_lines
GROUP BY product_id
ORDER BY profit ASC
LIMIT 15;


-- ---------------------------------------------------------------------------
-- P4. High revenue, LOW profit - the commercially dangerous group.
--
-- "High revenue" is defined against the median product revenue rather than a
-- hardcoded threshold, so the classification survives a change in data volume.
-- These are the products where scaling sales scales the loss.
-- ---------------------------------------------------------------------------
WITH per_product AS (
    SELECT
        product_id,
        MIN(product_label) AS product,
        MIN(category)      AS category,
        MIN(sub_category)  AS sub_category,
        SUM(quantity)      AS units,
        SUM(revenue)       AS revenue,
        SUM(profit)        AS profit,
        AVG(discount)      AS avg_discount
    FROM fact_order_lines
    GROUP BY product_id
),
thresholds AS (
    -- Median revenue via a window position, so no PERCENTILE function is needed.
    --
    -- The predicate uses MULTIPLICATION rather than rn = (n+1)/2 on purpose:
    -- SQLite does integer division there (10293/2 -> 5146) while MySQL returns
    -- 5146.5, which matches no row and silently yields an EMPTY threshold - and
    -- therefore an empty quadrant classification. Comparing rn*2 to n+1/n+2
    -- behaves identically on every engine. For an even row count this selects
    -- the upper of the two middle values.
    SELECT revenue AS median_revenue
    FROM (
        SELECT revenue,
               ROW_NUMBER() OVER (ORDER BY revenue) AS rn,
               COUNT(*) OVER ()                    AS n
        FROM per_product
    ) ranked
    WHERE rn * 2 = n + 1 OR rn * 2 = n + 2
)
SELECT
    p.product_id,
    p.product,
    p.sub_category,
    p.units,
    ROUND(p.revenue, 2)                                     AS revenue,
    ROUND(p.profit, 2)                                      AS profit,
    ROUND(100.0 * p.profit / NULLIF(p.revenue, 0), 2)       AS margin_pct,
    ROUND(p.avg_discount, 4)                                AS avg_discount
FROM per_product p
CROSS JOIN thresholds t
WHERE p.revenue >= t.median_revenue
  AND p.profit <= 0
ORDER BY p.profit ASC
LIMIT 20;


-- ---------------------------------------------------------------------------
-- P5. The full four-quadrant classification, summarised.
--
-- The headline number this produces: the high-revenue / loss-making quadrant
-- carries about a quarter of all revenue while destroying profit, and its
-- average discount is roughly twice that of the healthy high-revenue quadrant.
-- Same discount story as sales_analysis.sql S8, now at product level.
-- ---------------------------------------------------------------------------
WITH per_product AS (
    SELECT
        product_id,
        SUM(revenue)  AS revenue,
        SUM(profit)   AS profit,
        AVG(discount) AS avg_discount
    FROM fact_order_lines
    GROUP BY product_id
),
thresholds AS (
    -- Same multiplication-based median predicate as P4; see the note there.
    SELECT revenue AS median_revenue
    FROM (
        SELECT revenue,
               ROW_NUMBER() OVER (ORDER BY revenue) AS rn,
               COUNT(*) OVER ()                    AS n
        FROM per_product
    ) ranked
    WHERE rn * 2 = n + 1 OR rn * 2 = n + 2
),
classified AS (
    SELECT
        p.*,
        CASE
            WHEN p.revenue >= t.median_revenue AND p.profit > 0
                THEN '1 High revenue / High profit'
            WHEN p.revenue >= t.median_revenue AND p.profit <= 0
                THEN '2 High revenue / LOW profit'
            WHEN p.revenue <  t.median_revenue AND p.profit > 0
                THEN '3 Low revenue / High margin'
            ELSE '4 Low revenue / Low profit'
        END AS quadrant
    FROM per_product p
    CROSS JOIN thresholds t
)
SELECT
    quadrant,
    COUNT(*)                                                AS products,
    ROUND(SUM(revenue), 2)                                  AS revenue,
    ROUND(SUM(profit), 2)                                   AS profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct,
    ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 2) AS pct_of_revenue,
    ROUND(AVG(avg_discount), 4)                             AS avg_discount
FROM classified
GROUP BY quadrant
ORDER BY quadrant;


-- ---------------------------------------------------------------------------
-- P6. Sub-category profitability with dual rankings.
--
-- revenue_rank vs margin_rank exposes the mismatch directly: a sub-category
-- ranked high on revenue and low on margin is where volume is masking weakness.
-- ---------------------------------------------------------------------------
SELECT
    category,
    sub_category,
    COUNT(DISTINCT product_id)                              AS products,
    SUM(quantity)                                           AS units,
    ROUND(SUM(revenue), 2)                                  AS revenue,
    ROUND(SUM(profit), 2)                                   AS profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct,
    RANK() OVER (ORDER BY SUM(revenue) DESC)                AS revenue_rank,
    RANK() OVER (ORDER BY 100.0 * SUM(profit)
                          / NULLIF(SUM(revenue), 0) DESC)   AS margin_rank,
    RANK() OVER (ORDER BY SUM(revenue) DESC)
        - RANK() OVER (ORDER BY 100.0 * SUM(profit)
                                / NULLIF(SUM(revenue), 0) DESC) AS rank_gap
FROM fact_order_lines
GROUP BY category, sub_category
ORDER BY margin_pct ASC;


-- ---------------------------------------------------------------------------
-- P7. Brand performance.
--
-- brand is a DERIVED field (first token of the product name) and is only
-- reliable in aggregate, so this restricts to brands with a meaningful
-- footprint. Brands below the threshold are excluded rather than shown as
-- noisy one-line rows. See reports/data_quality_report.md section 12.
-- ---------------------------------------------------------------------------
SELECT
    brand,
    COUNT(DISTINCT product_id)                              AS products,
    COUNT(*)                                                AS order_lines,
    ROUND(SUM(revenue), 2)                                  AS revenue,
    ROUND(SUM(profit), 2)                                   AS profit,
    ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2) AS margin_pct,
    ROUND(AVG(discount), 4)                                 AS avg_discount
FROM fact_order_lines
WHERE brand <> 'Unknown'
GROUP BY brand
HAVING COUNT(*) >= 100
ORDER BY profit ASC
LIMIT 20;


-- ---------------------------------------------------------------------------
-- P8. Products whose loss is specifically a DISCOUNT problem.
--
-- The test is counterfactual: a product that is loss-making overall but whose
-- undiscounted lines are profitable is a pricing-policy failure, not a bad
-- product. Those are fixable by withdrawing discount rather than delisting -
-- a materially different decision, and the reason this query exists.
-- ---------------------------------------------------------------------------
WITH by_product AS (
    SELECT
        product_id,
        MIN(product_label) AS product,
        MIN(sub_category)  AS sub_category,
        SUM(revenue)       AS revenue,
        SUM(profit)        AS profit,
        SUM(CASE WHEN discount = 0 THEN revenue ELSE 0 END) AS revenue_at_full_price,
        SUM(CASE WHEN discount = 0 THEN profit  ELSE 0 END) AS profit_at_full_price,
        SUM(CASE WHEN discount > 0 THEN profit  ELSE 0 END) AS profit_when_discounted,
        COUNT(CASE WHEN discount = 0 THEN 1 END)            AS lines_full_price,
        COUNT(CASE WHEN discount > 0 THEN 1 END)            AS lines_discounted
    FROM fact_order_lines
    GROUP BY product_id
)
SELECT
    product_id,
    product,
    sub_category,
    ROUND(revenue, 2)                       AS revenue,
    ROUND(profit, 2)                        AS total_profit,
    ROUND(profit_at_full_price, 2)          AS profit_at_full_price,
    ROUND(profit_when_discounted, 2)        AS profit_when_discounted,
    lines_full_price,
    lines_discounted,
    'Profitable at full price - withdraw discount, do not delist' AS recommendation
FROM by_product
WHERE profit < 0                    -- loses money overall
  AND profit_at_full_price > 0      -- but is fine when sold at full price
  AND lines_full_price >= 3         -- enough full-price evidence to trust
ORDER BY profit ASC
LIMIT 20;
