---
name: warship-living-docs
description: "Create and continuously update Warship documentation from code changes. Use for endpoint docs, architecture updates, data contracts, SQL and Excel source mapping, and release notes."
argument-hint: "Describe the feature, route, or file changes to document."
user-invocable: true
disable-model-invocation: false
---

# Warship Living Documentation

## Purpose
Maintain continuously accurate project documentation that evolves with code.

## Use When
- New route is added, removed, or renamed.
- Endpoint request or response shape changes.
- SQL logic, table/view source, or Excel parsing logic changes.
- Template behavior or page workflow changes.
- Operational assumptions (units, date windows, YTD rules) change.

## Required Inputs
- Target changed files or route names.
- Scope of documentation update (API docs, architecture, runbook, all).

## Procedure
1. Identify impacted components:
- Routers
- Schemas
- Templates
- Data scripts
- Existing docs

2. Extract ground-truth facts from code:
- Exact route paths and HTTP methods
- Query/body params with defaults
- Response fields and value semantics
- Data source origin (table/view/workbook/sheet)

3. Update the right documentation targets:
- Route catalog sections
- Data contract sections
- Architecture flow notes
- Operational caveats and assumptions

4. Add unit and timeframe annotations:
- lbs vs weight
- dollars vs c/lb
- monthly vs YTD vs full-year
- exclusions (partial year, missing sheet, etc.)

5. Add change note:
- Date
- Files reviewed
- What was added, updated, removed
- Open questions

## Quality Gate (must pass)
- No undocumented new endpoint remains.
- No stale endpoint references remain.
- All numeric fields have units where needed.
- All data-source claims map to actual code paths, tables, or files.
- Ambiguities are listed explicitly as unresolved.

## Output Format
- Summary
- Documentation files updated
- Endpoint/data-contract deltas
- Open assumptions and questions
