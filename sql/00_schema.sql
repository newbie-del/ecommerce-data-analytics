-- ===========================================================================
--  E-COMMERCE ANALYTICS  |  00 - SCHEMA
-- ===========================================================================
--  Analytical model for the cleaned Global Superstore data.
--
--  PORTABILITY NOTE - why this SQL has no date functions
--  -----------------------------------------------------
--  Every calendar part the analysis needs (order_year, order_month, order_ym)
--  and every date difference (ship_lag_days) is precomputed as a column by
--  src/feature_engineering.py. That is a deliberate modelling choice, not
--  laziness: it keeps all four analysis files free of DATEDIFF / DATE_FORMAT /
--  strftime / julianday, so the identical text runs unmodified on MySQL 8.0,
--  PostgreSQL, SQLite and DuckDB. It also means the SQL and the Python compute
--  month buckets from one shared definition instead of two that can drift.
--
--  EXECUTION STATUS - this SQL is verified, not merely written
--  ----------------------------------------------------------
--  Every statement in every file here is executed by src/verify_claims.py
--  against SQLite, and the headline aggregates are asserted equal to the pandas
--  pipeline's own numbers. So the SQL layer is an INDEPENDENT reproduction of
--  the Python results, not an untested transcript of them.
--
--  MySQL 8.0 is installed on the build machine but no credentials were
--  available, so it was not the execution engine. To run these files there:
--
--     mysql -u <user> -p < sql/00_schema.sql
--     -- then load the CSVs (see LOADING below), then:
--     mysql -u <user> -p ecommerce_analytics < sql/sales_analysis.sql
--     mysql -u <user> -p ecommerce_analytics < sql/product_analysis.sql
--     mysql -u <user> -p ecommerce_analytics < sql/customer_analysis.sql
--     mysql -u <user> -p ecommerce_analytics < sql/operations_analysis.sql
--
--  GRAIN
--  -----
--  fact_order_lines : one row per order line  (51,290)
--                     primary key order_line_id (the raw Row ID)
--
--  Two composite keys carried from the cleaning layer, both essential:
--    order_key    = order_id + customer_id + order_date. Plain order_id is
--                   REUSED - 659 ids appear against two different customers on
--                   two different dates - so counting DISTINCT order_id gives
--                   25,035 orders where 25,754 exist.
--    customer_key = the resolved person. Every one of the 795 customer names
--                   carries TWO customer_ids (one for APAC/EU/LATAM/US, one for
--                   Africa/EMEA), so COUNT(DISTINCT customer_id) returns 1,590
--                   customers where 795 people exist.
--  Using the raw ids instead of these keys is the single easiest way to get
--  every customer and order metric in this project wrong.
-- ===========================================================================

DROP TABLE IF EXISTS fact_order_lines;
DROP TABLE IF EXISTS dim_returns_coverage;

-- ---------------------------------------------------------------------------
-- The fact table. Types are deliberately generic (INTEGER / REAL / VARCHAR /
-- DATE) because every target engine accepts them.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_order_lines (
    order_line_id      INTEGER      NOT NULL,
    order_id           VARCHAR(20)  NOT NULL,
    order_key          VARCHAR(64)  NOT NULL,   -- composite; see GRAIN above
    order_date         DATE         NOT NULL,
    ship_date          DATE         NOT NULL,
    ship_mode          VARCHAR(20)  NOT NULL,

    customer_id        VARCHAR(20)  NOT NULL,   -- raw, NOT unique per person
    customer_key       VARCHAR(80)  NOT NULL,   -- resolved person
    customer_name      VARCHAR(80)  NOT NULL,
    customer_segment   VARCHAR(20)  NOT NULL,

    city               VARCHAR(80),
    state              VARCHAR(80),
    country            VARCHAR(80)  NOT NULL,
    market             VARCHAR(20)  NOT NULL,
    region             VARCHAR(30)  NOT NULL,

    product_id         VARCHAR(30)  NOT NULL,
    product_label      VARCHAR(200) NOT NULL,   -- canonical name for the id
    category           VARCHAR(30)  NOT NULL,
    sub_category       VARCHAR(30)  NOT NULL,
    brand              VARCHAR(60),             -- DERIVED from product name

    quantity           INTEGER      NOT NULL,
    revenue            REAL         NOT NULL,   -- NET of discount (verified)
    list_revenue       REAL         NOT NULL,   -- revenue / (1 - discount)
    discount           REAL         NOT NULL,   -- 0.000 - 0.850, 3dp
    discount_amount    REAL         NOT NULL,
    cost               REAL         NOT NULL,   -- revenue - profit, exact
    profit             REAL         NOT NULL,
    profit_margin_pct  REAL,
    shipping_cost      REAL         NOT NULL,

    order_priority     VARCHAR(20)  NOT NULL,
    return_flag        INTEGER      NOT NULL,   -- 1 = order was returned
    returns_measured   INTEGER      NOT NULL,   -- 0 = market has NO return data
    ship_lag_days      INTEGER      NOT NULL,   -- order to SHIP, not delivery
    is_loss_making     INTEGER      NOT NULL,
    discount_band      VARCHAR(20)  NOT NULL,

    order_year         INTEGER      NOT NULL,
    order_month        INTEGER      NOT NULL,
    order_ym           VARCHAR(7)   NOT NULL,   -- 'YYYY-MM'

    PRIMARY KEY (order_line_id)
);

-- ---------------------------------------------------------------------------
-- Returns coverage. This table exists to make a LIMITATION impossible to miss:
-- the source Returns sheet records nothing for Africa, Canada or EMEA. Without
-- it, a WHERE return_flag = 0 reads as "not returned" when the truth is "never
-- measured", and the global return rate is understated by a third of markets.
-- Every return metric in operations_analysis.sql joins through here.
-- ---------------------------------------------------------------------------
CREATE TABLE dim_returns_coverage (
    market            VARCHAR(20) NOT NULL,
    has_returns_data  INTEGER     NOT NULL,
    coverage_note     VARCHAR(120) NOT NULL,
    PRIMARY KEY (market)
);

INSERT INTO dim_returns_coverage (market, has_returns_data, coverage_note) VALUES
    ('APAC',   1, 'Returns recorded'),
    ('EU',     1, 'Returns recorded'),
    ('LATAM',  1, 'Returns recorded'),
    ('US',     1, 'Returns recorded (source sheet labels this market United States)'),
    ('Africa', 0, 'NO return records - return rate is unknown, not zero'),
    ('Canada', 0, 'NO return records - return rate is unknown, not zero'),
    ('EMEA',   0, 'NO return records - return rate is unknown, not zero');

-- ---------------------------------------------------------------------------
-- Indexes for the grouping columns the analysis files actually filter on.
-- ---------------------------------------------------------------------------
CREATE INDEX idx_fol_order_key    ON fact_order_lines (order_key);
CREATE INDEX idx_fol_customer_key ON fact_order_lines (customer_key);
CREATE INDEX idx_fol_product      ON fact_order_lines (product_id);
CREATE INDEX idx_fol_ym           ON fact_order_lines (order_ym);
CREATE INDEX idx_fol_year         ON fact_order_lines (order_year);
CREATE INDEX idx_fol_market       ON fact_order_lines (market);
CREATE INDEX idx_fol_category     ON fact_order_lines (category, sub_category);
CREATE INDEX idx_fol_returns      ON fact_order_lines (returns_measured, return_flag);

-- ===========================================================================
--  LOADING
-- ===========================================================================
--  src/verify_claims.py loads data/processed/orders_features.csv through pandas,
--  which is how the automated verification runs.
--
--  To load into MySQL 8.0 instead, start the client with --local-infile=1 and
--  run the statement below. It is left commented because LOAD DATA is the one
--  piece of this schema that is NOT portable, and an uncommented MySQL-only
--  statement would break execution on every other engine.
--
--  LOAD DATA LOCAL INFILE 'data/processed/orders_features.csv'
--      INTO TABLE fact_order_lines
--      FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
--      LINES TERMINATED BY '\n'
--      IGNORE 1 LINES
--      (order_line_id, order_id, order_date, ship_date, ship_mode, customer_id,
--       customer_name, customer_segment, city, state, country, @postal_code,
--       market, region, product_id, category, sub_category, @product_name,
--       revenue, quantity, discount, profit, shipping_cost, order_priority,
--       customer_key, order_key, brand, product_label, return_flag,
--       returns_measured, cost, list_revenue, discount_amount, @unit_price_net,
--       @unit_price_list, @unit_cost, profit_margin_pct, @profit_after_shipping,
--       is_loss_making, ship_lag_days, discount_band, order_year, order_month,
--       @order_quarter, order_ym, @order_month_start, @order_month_name,
--       @order_dow);
-- ===========================================================================
