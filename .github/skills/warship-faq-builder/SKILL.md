---
name: warship-faq-builder
description: "Extract, organize, and maintain Warship FAQ by user role. Link questions to code paths, workflows, and documentation. Generate `/docs/FAQ.md` from code analysis and user patterns."
argument-hint: "Describe the workflow, feature, or page to extract FAQs from, or request a full FAQ refresh."
user-invocable: true
disable-model-invocation: false
---

# Warship FAQ Builder

## Purpose
Maintain a single source of truth FAQ organized by user role (Warehouse Operators, Shipping Coordinators, Operations Managers, Administrators). Extract FAQs from code patterns, page workflows, API behavior, and common support issues. Keep FAQs accurate and linked to implementation details.

## Use When
- A new page, feature, or workflow is added that users will ask about.
- User confusion patterns emerge (unclear naming, unexpected behavior, missing context).
- A page or endpoint behavior changes.
- API response structure or parameter meaning changes.
- Operational rules, constraints, or assumptions change.
- Full FAQ refresh is needed across all roles.

## Required Inputs
- **Single workflow:** Target page/feature name (e.g., "Meeting Report", "Truck Load Map", "Carrier Cost Analysis")
- **Full refresh:** Request "regenerate all FAQs" or "full FAQ refresh"
- **Error pattern:** Describe the confusion or issue (e.g., "users don't understand ¢/lb calculation")

## User Roles (from SRS)
1. **Warehouse Operators** — View UDC activity, ASH event heatmaps
2. **Shipping Coordinators** — Run meeting reports, prepare TSR shipment maps
3. **Operations Managers** — View briefings, freight analytics, weight trends
4. **Administrators** — Upload IPG EZ Excel reports, view software architecture

## Procedure

### Phase 1: Identify the Scope
- Single feature/page → Extract FAQs for that feature only
- Full refresh → Scan all routers, templates, and pages

### Phase 2: Gather Evidence
For each page/feature, read:
- Router file to understand inputs, filters, data sources
- Template to understand UI elements, interactions, labels
- Schemas to understand data structure and validation
- Data source documentation (MySQL tables, Excel sheets, API responses)
- Related templates/pages that users might confuse with this one

### Phase 3: Generate FAQ Questions
For each page/feature, ask:
1. **What is this page/feature for?** → Answer from router `description` or template comments
2. **Who uses it?** → Which user roles
3. **How do I access it?** → Route path, menu navigation
4. **What do these terms mean?** → Define ambiguous labels (¢/lb, YTD, median, outliers, BL, etc.)
5. **How is this data calculated?** → Point to SQL, code, or CLAUDE.md
6. **What filters/inputs are available?** → From form fields, URL params
7. **What does the output mean?** → Explain every chart, table, metric
8. **Why is my data missing/different?** → Common data gaps (partial month, excluded sites, etc)
9. **Can I export/download this?** → Capabilities and limitations
10. **What should I do if X happens?** → Troubleshooting for errors, empty results

### Phase 4: Organize by Role
Assign each FAQ to user roles who need it (can be multiple):
- Warehouse Operators: UDC, ASH, pallet entry/exit, event heatmaps
- Shipping Coordinators: Meeting reports, TSR prep, truck load map, carrier analysis
- Operations Managers: Briefing, freight analytics, weight trends, LMI
- Administrators: Architecture, Excel upload, data refresh, maintenance pages

### Phase 5: Link to Code
For each FAQ answer:
- If it references a calculation, link to the SQL or Python file and line range
- If it explains a term, link to CLAUDE.md or SRS definition
- If it describes a workflow, link to the router or template
- If it shows an example, include inline code or screenshot path

### Phase 6: Quality Gate
- Every page has at least 3 FAQs
- Every FAQ answer explains the "why" and "how," not just "what"
- All calculated/aggregated metrics include unit + time scope annotation
- All external data sources are cited (MySQL table, Excel sheet, API endpoint)
- All ambiguous terms are defined (¢/lb, YTD, median, outliers, BL, etc.)
- No stale references to removed pages or endpoints
- No duplication across roles (reuse FAQ across roles, don't copy-paste)

## Output Format

`/docs/FAQ.md` with structure:

```markdown
# Warship FAQ

**Last Updated:** [DATE]  
**Scope:** All pages and workflows  
**Maintained by:** SLM (senior_lead_architect)

---

## Table of Contents
- [General / All Users](#general--all-users)
- [Warehouse Operators](#warehouse-operators)
- [Shipping Coordinators](#shipping-coordinators)
- [Operations Managers](#operations-managers)
- [Administrators](#administrators)
- [Troubleshooting](#troubleshooting)

---

## General / All Users

### Q: What is Warship?
**A:** Warship is a unified internal platform for warehouse inventory, shipping logistics, and freight analytics. It replaces standalone scripts and centralizes all operations data into a single FastAPI web app.

[Source: CLAUDE.md, docs/SRS.md]

### Q: How do I access Warship?
**A:** Navigate to `http://localhost:8088` in your internal browser. You will see the Overview page with quick-access cards for each major workflow.

---

## Warehouse Operators

### Q: What is UDC?
**A:** UDC = Unit Distribution Center. It tracks warehouse movement metrics (pallets in/out hourly). See the [Warehouse page](/warehouse) for live UDC charts.

[Source: docs/SRS.md, routers/warehouse.py]

...

## Shipping Coordinators

...

## Operations Managers

...

## Administrators

### Q: Where do I upload IPG EZ Excel reports?
**A:** Go to [/maintenance/input](/maintenance/input) (sysadmin only). Upload the `.xlsx` file. The system parses it and imports shipment records into MySQL. See [FAQ: Excel upload process](#admin-excel-upload-process) for details.

[Source: routers/maintenance.py, SRS § 7 External Integrations]

...

## Troubleshooting

### Q: Why is my chart missing data?
**A:** Common causes:
1. **Partial month:** We show YTD data from Jan 1 → today. If today is early in the month, charts may look sparse.
2. **Site/product filter:** Check that your filters match actual data. Some sites may have zero shipments in the selected range.
3. **Excel not uploaded:** If using IPG EZ data, ensure the latest Excel file was uploaded to [/maintenance/input](/maintenance/input).

See routers/home.py lines 45–60 for default filters (AMJK site, SW product group).

[Source: routers/home.py, docs/CLAUDE.md]

...
```

## Integration with Living Docs & Fact Guard

- **warship-living-docs:** Use this to update SRS § 4, 5, 6 with new feature requirements
- **warship-fact-guard:** Use this to verify all FAQ claims are sourced from actual code
- **anti-hallucination:** Enforce that every metric definition is grounded in MySQL schema or CLAUDE.md

## Change Log Template

Every time you regenerate FAQ, add a dated entry:

```markdown
## Change Log

- **2026-03-19:** Added FAQs for Briefing print output (chart sizing). Updated Warehouse Operators section with pallet entry/exit definitions. [Reviewer: SLM]
- **2026-03-10:** Full refresh. Added Administrator section, reorganized by workflow. [Reviewer: SLM]
```

---

## Common FAQ Patterns (steal these)

| Question | Where It Fits | Answer Template |
|----------|---------------|-----------------|
| "What is X?" | Opening of each role section | "X is [definition]. See [page] to view/create X. [Source]" |
| "How do I use X?" | Workflow steps | "1. Go to [page]. 2. [Filter / input]. 3. [Action]. 4. [Result]. [Screenshot/link]" |
| "What does Y mean?" | Definition | "Y = [expanded form / metric]. Calculated as [formula]. Measured in [units]. See [code link]." |
| "Why is my data..?" | Troubleshooting | "Common causes: [list 3]. Check [page] for [action]. [Source]" |
| "How is Z calculated?" | Data semantics | "Z = [full formula]. Data source: [MySQL table / Excel sheet / API]. Updated [frequency]. See [code]." |
