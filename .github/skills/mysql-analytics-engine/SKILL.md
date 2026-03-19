---
name: mysql-analytics-engine
description: Expert SQL optimization and data retrieval for logistics metrics.
---

# MySQL Analytics Skill

## Database Rules
- **Efficiency:** Write optimized JOINs for the freight and cost tables. Use EXPLAIN to verify query performance.
- **Aggregation:** Perform heavy calculations (averages, totals, LMI trends) directly in MySQL to minimize Python-side overhead.
- **Data Integrity:** Ensure all data fetched from MySQL is validated against Pydantic models in `schemas/`.

## Analytics Workflow
- When asked for a "Trend Analysis," generate SQL queries that group data by month/year.
- Ensure all logistics dates are handled correctly in MySQL to prevent timezone or formatting errors.
