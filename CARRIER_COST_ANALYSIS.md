# Carrier Cost Per Pound Analysis — Build Instructions

## Overview

Build a new feature in the Warship app: a Carrier Cost Per Pound Analysis page with a FastAPI endpoint calling a MySQL stored procedure, and a frontend bubble chart + data table.

**Stack:** FastAPI, Bootstrap 5, Alpine.js, Plotly.js, MySQL (existing Warship stack)

---

## Step 1: Create the MySQL Stored Procedure

Run this SQL against the `warship` database:

```sql
DELIMITER $$

CREATE PROCEDURE warship.sp_carrier_cost_per_pound(
    IN p_date_from DATE,
    IN p_date_to DATE,
    IN p_site VARCHAR(10),
    IN p_product_group VARCHAR(10)
)
BEGIN
    SELECT 
        s.Carrier_ID,
        COUNT(DISTINCT s.BL_Number) AS bl_count,
        CAST(SUM(COALESCE(s.Pick_Weight, 0)) AS SIGNED) AS total_weight,
        CAST(SUM(COALESCE(s.Number_of_Pallet, 0)) AS SIGNED) AS total_pallets,
        SUM(COALESCE(s.Unit_Freight, 0) * COALESCE(s.Number_of_Pallet, 0)) AS total_freight_cost,
        ROUND(
            SUM(COALESCE(s.Unit_Freight, 0) * COALESCE(s.Number_of_Pallet, 0)) 
            / NULLIF(SUM(COALESCE(s.Pick_Weight, 0)), 0),
            4
        ) AS cost_per_pound
    FROM warship.ipg_ez s
    WHERE
        s.Truck_Appointment_Date IS NOT NULL
        AND s.Product_Code NOT IN ('INSERT-C', 'INSERT-3')
        AND (p_date_from IS NULL OR s.Truck_Appointment_Date >= p_date_from)
        AND (p_date_to   IS NULL OR s.Truck_Appointment_Date <= p_date_to)
        AND (p_site IS NULL OR s.Site = p_site)
        AND (p_product_group IS NULL OR s.Product_Group = p_product_group)
        AND NOT EXISTS (
            SELECT 1
            FROM warship.ipg_ez n
            WHERE n.BL_Number = s.BL_Number
              AND (
                  n.snap_ts > s.snap_ts
                  OR (n.snap_ts = s.snap_ts AND n.file_name > s.file_name)
              )
        )
    GROUP BY s.Carrier_ID
    ORDER BY cost_per_pound DESC;
END$$

DELIMITER ;
```

---

## Step 2: Create the FastAPI Endpoint

Create a new route file (or add to existing routes) for the carrier cost analysis.

### Endpoint: `GET /api/carrier-cost-analysis`

**Query Parameters (all optional):**
- `date_from: date | None = None`
- `date_to: date | None = None`
- `site: str | None = None`
- `product_group: str | None = None`

**Implementation:**
- Call the stored procedure: `CALL warship.sp_carrier_cost_per_pound(%s, %s, %s, %s)`
- Pass `None` for any parameter not provided (MySQL receives NULL)
- Return JSON array of objects with fields: `carrier_id`, `bl_count`, `total_weight`, `total_pallets`, `total_freight_cost`, `cost_per_pound`
- Use the existing database connection pattern from the Warship app (check existing routes for reference)

**Example response:**
```json
[
  {
    "carrier_id": "CWF-IP",
    "bl_count": 1,
    "total_weight": 63464,
    "total_pallets": 53,
    "total_freight_cost": 6384.80,
    "cost_per_pound": 0.0245
  },
  ...
]
```

**Error handling:**
- Return 400 if date_from > date_to
- Return 500 with message if DB connection fails

---

## Step 3: Create the Frontend Page

### Page Location
Add a new page/template for the carrier cost analysis. Add a nav link to the existing Warship navigation.

### Page Layout (top to bottom)

#### 3A. Filter Bar (top of page)
A horizontal row of filters using Bootstrap 5 card/form-inline:
- **Date From**: `<input type="date">` — default to first day of current month
- **Date To**: `<input type="date">` — default to today
- **Site**: `<select>` dropdown with options: `All`, `AMAZ`, `AMIN`, `AMJK`, `AMSC`, `PFCH`, `TXAS`, `VAMT`
- **Product Group**: `<select>` dropdown with options: `All`, `SW`, `BP`, `CT`
- **Apply Filters** button: triggers API call and refreshes chart + table

Use Alpine.js for state management. On page load, auto-fetch with default filter values.

#### 3B. Bubble Chart (main visualization)
Use **Plotly.js** (CDN: `https://cdn.plot.ly/plotly-latest.min.js`)

**Chart Configuration:**
- **X-axis**: `total_weight` — label: "Total Weight (lbs)"
- **Y-axis**: `cost_per_pound` — label: "Cost Per Pound ($)"
- **Bubble size**: `total_freight_cost` — scale bubbles proportionally using `sizeref` so the largest bubble is readable but not overwhelming
- **Bubble color**: Use a sequential color scale based on `cost_per_pound` (red = expensive, green = cheap). Use Plotly's `RdYlGn_r` colorscale.
- **Hover template**: Show carrier name, cost/lb, total weight, total freight cost, BL count, total pallets — all formatted nicely
- **Text labels**: Show `carrier_id` on each bubble using `mode: 'markers+text'`, `textposition: 'top center'`
- **Layout**: responsive, white background, clear gridlines, title: "Carrier Cost Per Pound Analysis"

**Important Plotly settings:**
```javascript
var trace = {
    x: data.map(d => d.total_weight),
    y: data.map(d => d.cost_per_pound),
    text: data.map(d => d.carrier_id),
    mode: 'markers+text',
    textposition: 'top center',
    marker: {
        size: data.map(d => d.total_freight_cost),
        sizemode: 'area',
        sizeref: 2.0 * Math.max(...data.map(d => d.total_freight_cost)) / (80**2),
        sizemin: 8,
        color: data.map(d => d.cost_per_pound),
        colorscale: 'RdYlGn_r',
        colorbar: { title: '$/lb' },
        line: { width: 1, color: '#333' }
    },
    hovertemplate:
        '<b>%{text}</b><br>' +
        'Cost/lb: $%{y:.4f}<br>' +
        'Total Weight: %{x:,.0f} lbs<br>' +
        'Freight Cost: $%{customdata[0]:,.2f}<br>' +
        'BL Count: %{customdata[1]}<br>' +
        'Pallets: %{customdata[2]}<extra></extra>',
    customdata: data.map(d => [d.total_freight_cost, d.bl_count, d.total_pallets])
};
```

#### 3C. Summary Cards (between chart and table)
A row of 4 Bootstrap cards showing:
- **Total Carriers**: count of carriers returned
- **Total Freight Cost**: sum of all `total_freight_cost`, formatted as currency
- **Total Weight**: sum of all `total_weight`, formatted with commas + "lbs"
- **Avg Cost/lb**: weighted average (total freight cost / total weight), formatted as `$X.XXXX`

#### 3D. Data Table (below chart)
A Bootstrap 5 striped table with sortable columns:

| Carrier ID | BL Count | Total Weight (lbs) | Total Pallets | Total Freight Cost ($) | Cost Per Pound ($) |
|---|---|---|---|---|---|

**Table features:**
- Default sort: `cost_per_pound` descending (most expensive first)
- Click column headers to sort ascending/descending (use Alpine.js for client-side sorting)
- Format numbers: weights with commas, costs with `$` and 2 decimals, cost_per_pound with 4 decimals
- Highlight the most expensive carrier row with a light red background
- Highlight zero-cost carriers (like CPU) with a light gray background
- Show a footer row with totals for weight, pallets, freight cost, and weighted avg cost/lb

---

## Step 4: Add Recommended Indexes

If these indexes don't already exist on `ipg_ez`, create them for performance:

```sql
CREATE INDEX idx_ipg_ez_bl_snap ON warship.ipg_ez (
    BL_Number, snap_ts, file_name
);

CREATE INDEX idx_ipg_ez_filter ON warship.ipg_ez (
    Truck_Appointment_Date, Site, Product_Group, Product_Code
);
```

Check existing indexes first with:
```sql
SHOW INDEX FROM warship.ipg_ez;
```

Only add what's missing.

---

## Step 5: Navigation Integration

Add a link to this new page in the Warship sidebar/navbar. Suggested label: **"Carrier Cost Analysis"** under an Analytics or Reports section.

---

## File Structure Summary

```
(add to existing Warship project structure)
├── routes/
│   └── carrier_cost.py          # New FastAPI route
├── templates/
│   └── carrier_cost.html        # New page template
└── static/
    └── js/
        └── carrier_cost.js      # (optional) separate JS if preferred
```

## Notes
- Follow existing Warship code patterns for DB connections, template rendering, and error handling
- Load Plotly.js from CDN, do not install via npm
- The SP uses the same "latest snapshot" NOT EXISTS logic as the existing view `vw_bl_lbs_cnt_carrier_customer`
- All filter parameters are optional — passing none returns all data
- Test with: date_from=2026-01-01, date_to=2026-01-31, site=AMJK, product_group=SW