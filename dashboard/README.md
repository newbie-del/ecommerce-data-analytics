# Dashboard - build status and instructions

## Status, stated plainly

This folder contains a generated Power BI Project (`.pbip`) with a TMDL semantic model and PBIR report definition.

| Artefact | Status |
|---|---|
| `data/*.csv` - star schema inputs | **Built and verified.** 12/12 referential-integrity checks pass; revenue and profit reconcile exactly to the source |
| `data/model_manifest.json` | **Generated.** Table sizes, six relationships, integrity results |
| `build_star_schema.py` | **Runs.** Regenerates the model inputs from `data/processed/` |
| `build_pbip.py` | **Runs.** Regenerates the `.pbip`, semantic model and report definition |
| `measures.dax` | **Authored.** Measures are emitted from the same source as the semantic model |
| `DASHBOARD_SPEC.md` | **Complete.** Every page, visual, field and design rule |
| `EcommerceAnalytics.pbip` | **Generated** |
| `EcommerceAnalytics.SemanticModel/` | **Generated** |
| `EcommerceAnalytics.Report/` | **Generated** |
| Dashboard screenshots | **Exported** to `reports/figures/dashboard_*.png` |

## Open the dashboard

1. Open Power BI Desktop.
2. Open `dashboard/EcommerceAnalytics.pbip`.
3. Refresh the model if prompted.
4. Check the measures below before trusting the report.

The generated project targets Power BI Desktop 2.155.756.0, as noted in `build_pbip.py`. PBIP/TMDL/PBIR formats are version-sensitive, so older Power BI Desktop versions may need an update.

## Rebuild

```bash
python dashboard/build_star_schema.py
python dashboard/build_pbip.py
```

`build_star_schema.py` creates the CSV model inputs from `data/processed/`.
`build_pbip.py` creates `EcommerceAnalytics.pbip`, `EcommerceAnalytics.SemanticModel/`, `EcommerceAnalytics.Report/`, and refreshes `measures.dax`.

## Sanity checks once it is loaded

If the model is wired correctly, these must match. If any disagrees, a relationship or a key is wrong:

| Measure | Expected |
|---|---:|
| `Total Revenue` | 12,642,501.91 |
| `Total Profit` | 1,467,457.29 |
| `Profit Margin %` | 11.61% |
| `Total Orders` | 25,754 |
| `Total Customers` | 795 |
| `Total Products` | 10,292 |
| `Average Order Value` | 490.89 |
| `Median Order Value` | 201.30 |
| `Return Rate %` | 5.81% |
| `Unmeasured Orders` | 5,037 |
| `Loss-Making Line %` | 24.46% |
| `Discount Given` | 2,363,988.32 |

**Two red flags that mean a key is wrong, not a rounding difference:**

- `Total Orders` showing **25,035** means the model is counting `order_id` instead of `order_key`. `order_id` is reused across customers and dates.
- `Total Customers` showing **1,590** means the model is counting raw `customer_id` instead of `customer_key`. Every person in this dataset has two customer IDs.

All twelve figures above are asserted by `src/verify_claims.py` with 178 checks and 0 failures, so they are the source of truth to check against.

## Dashboard pages

| Page | Screenshot |
|---|---|
| Executive Overview | `reports/figures/dashboard_1_executive_overview.png` |
| Sales & Product Analysis | `reports/figures/dashboard_2_sales_product.png` |
| Customer Analytics | `reports/figures/dashboard_3_customer_analytics.png` |
| Operations & Returns | `reports/figures/dashboard_4_operations_returns.png` |

## Analytical fallback

The notebook at `notebooks/ecommerce_analysis.ipynb` already contains all fourteen analysis figures, executed with outputs embedded, and `reports/figures/` holds them as PNGs. The analytical findings do not depend on Power BI being available; the dashboard is a delivery surface for the same verified numbers.

## Final Dashboard Note`r`nThe final report package was locked in after KPI review and validation.

