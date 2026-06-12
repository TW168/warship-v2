# LMI Freight Association Plan

## Purpose

Use 2026 Logistics Managers Index (LMI) freight and transportation signals to test whether external freight-market pressure is associated with AMJK Warship freight cost and shipment-size behavior.

This analysis is an association test, not an immediate causal proof. The core question is:

> When LMI freight and transportation pressure rises or falls in 2026, do AMJK freight cost, carrier behavior, or shipment size move in the same direction?

## Scope

- Site: `AMJK`
- Product group: `SW`
- Period: `2026 YTD`
- June 2026: partial/provisional unless the month is closed

## Important Exclusion

Do not use LMI warehouse metrics for this analysis.

The LMI warehousing index measures broad market warehouse prices, capacity, and utilization. That is not the same as AMJK warehouse floor performance. AMJK warehouse performance should continue to come from Warship operational data such as pallet movement, UDC activity, ASH events, and shipment-size workload metrics.

Excluded LMI fields:

- Warehousing Prices
- Warehousing Capacity
- Warehousing Utilization
- Inventory metrics, unless a separate inventory or demand analysis is requested

This plan focuses only on LMI freight and transportation signals.

## LMI Metrics To Use

Extract transportation-only values from the 2026 LMI PDF reports.

| LMI metric | Purpose |
|---|---|
| Transportation Prices | Primary external freight-rate pressure signal |
| Transportation Capacity | Indicates whether truck capacity is tight or loose |
| Transportation Utilization | Indicates market demand/activity for transportation assets |
| Freight/transportation text excerpts | Used for explanation and DeepSeek narrative, not raw numeric correlation |

## Warship Metrics To Compare

Align monthly Warship data to the same calendar months as LMI.

| Warship metric | Meaning |
|---|---|
| `freight_cplb` | AMJK actual freight cost per pound |
| `total_weight_lbs` | Monthly shipped weight |
| `load_count` | Monthly unique BL/load count |
| `avg_lbs_per_load` | Shipment size |
| `loads_per_million_lbs` | Workload intensity |
| `extra_loads_due_to_smaller_shipments` | Extra handling caused by smaller shipment size |
| carrier concentration | Helps separate market pressure from local carrier mix |

## Current Evidence From Code

- LMI score history currently exists in `raw_data/lmi_scores.csv`.
- LMI report files live under `raw_data/lmi/`.
- Freight cost trend data is computed in `routers/home.py` through the `/api/analytics/amjk-frt-ytd-vs-avg` route.
- Freight c/lb is calculated from `sp_bl_lbs_cnt_carrier` using weighted monthly freight amount and shipped weight.
- Shipment-size metrics are computed in `routers/maintenance/shipment_size_impact.py` through `/maintenance/api/shipment-size-impact`.
- Shipment-size output includes monthly `avg_lbs_per_load`, `loads_per_million_lbs`, and `extra_loads_due_to_smaller_shipments`.

## Joined Monthly Dataset

Build one joined monthly table for analysis.

```text
month
transportation_prices
transportation_capacity
transportation_utilization
freight_cplb
freight_cplb_yoy_pct
total_weight_lbs
load_count
avg_lbs_per_load
loads_per_million_lbs
extra_loads_due_to_smaller_shipments
```

Example shape:

```text
2026-01 | Transportation Prices | AMJK freight c/lb | avg lbs/load | loads/1M lbs
2026-02 | Transportation Prices | AMJK freight c/lb | avg lbs/load | loads/1M lbs
2026-03 | Transportation Prices | AMJK freight c/lb | avg lbs/load | loads/1M lbs
```

## Data Quality Checks

Before analysis, verify these points:

1. Every 2026 LMI PDF has extracted transportation metrics.
2. Month labels match between LMI and Warship data.
3. June 2026 is excluded or clearly marked provisional if the month is not closed.
4. Freight c/lb uses weighted monthly cost, not a simple average of rates.
5. Shipment-size metrics use the same site, product group, and date window as freight cost metrics.
6. LMI warehouse metrics are not included in the joined dataset.

Freight c/lb formula used by Warship:

```text
freight_amount = Unit_Freight / 100 * pick_weight
freight_cplb = freight_amount / pick_weight * 100
```

Shipment-size formula used by Warship:

```text
avg_lbs_per_load = total_weight_lbs / load_count
loads_per_million_lbs = load_count / (total_weight_lbs / 1,000,000)
```

## Association Tests

### 1. Same-Month Association

Question:

> When LMI Transportation Prices rise in the same month, does AMJK freight c/lb also rise?

Compare:

```text
Transportation Prices vs freight_cplb
Transportation Capacity vs freight_cplb
Transportation Utilization vs freight_cplb
Transportation Prices vs avg_lbs_per_load
Transportation Prices vs loads_per_million_lbs
```

### 2. Lagged Association

Freight-market pressure may appear in AMJK invoices after a delay. Test whether LMI leads Warship metrics by 0, 1, 2, or 3 months.

Example:

```text
LMI January -> AMJK freight January
LMI January -> AMJK freight February
LMI January -> AMJK freight March
LMI January -> AMJK freight April
```

Lag windows:

```text
0-month lag
1-month lag
2-month lag
3-month lag
```

### 3. Change-vs-Change Association

Compare monthly changes instead of raw levels.

```text
Delta Transportation Prices vs Delta freight_cplb
Delta Transportation Capacity vs Delta freight_cplb
Delta Transportation Utilization vs Delta load_count
Delta Transportation Prices vs Delta avg_lbs_per_load
Delta Transportation Prices vs Delta loads_per_million_lbs
```

This helps avoid a false conclusion where two metrics appear related only because both trend upward or downward over time.

## Interpretation Rules

| Finding | Meaning | Action |
|---|---|---|
| Transportation Prices strongly tracks AMJK freight c/lb | Market-driven freight inflation | Lock rates and capacity early |
| Transportation Prices does not track AMJK freight c/lb | Local controllable issue is likely | Inspect carrier, product, destination, and customer mix |
| Transportation Prices rises and avg lbs/load falls | Market pressure plus smaller shipment pressure | Consolidate orders, discuss minimums, review appointment density |
| Transportation Prices rises and avg lbs/load rises | AMJK may be offsetting market pressure through consolidation | Preserve and expand consolidation behavior |
| Transportation Capacity tightens and carrier concentration rises | Capacity risk | Qualify backup carriers before peak season |
| AMJK freight rises while LMI is flat or down | Local issue likely | Review carrier rates, outlier BLs, product mix, and destination mix |

## Recommended Briefing Visuals

Add one briefing card titled:

```text
LMI Freight Market vs AMJK Freight Cost
```

### Visual 1: Dual-Axis Line Chart

- Line 1: LMI Transportation Prices
- Line 2: AMJK freight c/lb
- X-axis: month

Purpose:

> Show whether external freight-market pressure and AMJK freight cost move together over time.

### Visual 2: Freight Scatter Plot

- X-axis: LMI Transportation Prices
- Y-axis: AMJK freight c/lb
- Point label: month

Purpose:

> Show whether higher transportation-price readings correspond to higher AMJK freight cost.

### Visual 3: Shipment-Size Scatter Plot

- X-axis: LMI Transportation Prices
- Y-axis: avg lbs/load or loads per million lbs
- Point label: month

Purpose:

> Show whether freight-market pressure is associated with shipment consolidation or smaller-load pressure.

### Visual 4: Correlation Table

```text
Relationship                                  Same Month   1-Month Lag   2-Month Lag   3-Month Lag
Transportation Prices -> Freight c/lb
Transportation Capacity -> Freight c/lb
Transportation Utilization -> Freight c/lb
Transportation Prices -> Avg lbs/load
Transportation Prices -> Loads per 1M lbs
```

## DeepSeek Role

DeepSeek should not calculate correlations or invent metrics.

The application should calculate these first:

- joined monthly rows
- same-month correlations
- lagged correlations
- change-vs-change correlations
- interpretation flags
- data quality warnings

Then DeepSeek should explain the already-computed result in plain business language.

Example payload shape:

```json
{
  "site": "AMJK",
  "product_group": "SW",
  "period": "2026 YTD",
  "lmi_metrics_used": [
    "Transportation Prices",
    "Transportation Capacity",
    "Transportation Utilization"
  ],
  "excluded_lmi_metrics": [
    "Warehousing Prices",
    "Warehousing Capacity",
    "Warehousing Utilization"
  ],
  "correlations": {
    "transportation_prices_vs_freight_cplb_same_month": 0.72,
    "transportation_prices_vs_freight_cplb_1_month_lag": 0.81,
    "transportation_prices_vs_avg_lbs_per_load": -0.35
  },
  "monthly_observations": []
}
```

Prompt shape:

```text
You are a senior logistics analyst.

Use only the supplied computed metrics. Do not invent data.

Write exactly three sections:

TREND:
Do LMI freight signals and AMJK freight cost move together?

WHY:
Is this likely market pressure, local carrier/product mix, shipment-size pressure, or mixed?

IMPROVE:
Give three actions AMJK should take.
```

## Proposed Endpoint

Create a read-only analytics endpoint:

```text
GET /api/analytics/lmi-freight-association?site=AMJK&product_group=SW&year=2026
```

The response should include:

- monthly joined rows
- same-month correlations
- lagged correlations
- change-vs-change correlations
- interpretation flags
- data quality warnings

## Expected Business Answer

The final briefing should answer:

> Is AMJK freight cost moving with the freight market, or are we seeing internal cost pressure from carrier mix, product mix, customer mix, or smaller shipment size?

Possible conclusions:

1. Market-driven: LMI Transportation Prices and AMJK freight c/lb move together, especially with a lag.
2. Local-driven: AMJK freight c/lb rises without matching LMI transportation pressure.
3. Mixed: LMI pressure rises and AMJK also has smaller loads, higher workload intensity, or carrier concentration.
4. Operational offset: LMI pressure rises, but AMJK holds freight c/lb stable through larger shipments, better carrier mix, or better routing.

## Implementation Order

1. Extract 2026 LMI transportation-only metrics from PDFs.
2. Build the monthly joined dataset.
3. Compute same-month and lagged correlations.
4. Add change-vs-change correlation checks.
5. Add data-quality warnings.
6. Add briefing visualizations.
7. Add DeepSeek interpretation using only computed results.
8. Add the final executive conclusion to the 30-minute briefing.

## Open Questions

1. Should the first version analyze only `AMJK` and `SW`, or allow all site/product combinations immediately?
2. Should June 2026 be excluded by default until month close?
3. Should carrier concentration be monthly in this endpoint, or should it remain a separate freight-driver drill-down?
4. Should LMI Transportation Capacity be inverted in the visual interpretation so lower capacity reads as higher pressure?
