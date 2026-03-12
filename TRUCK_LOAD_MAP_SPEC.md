# CLAUDE.md — Warship 2: Truck Load Map (TSR Prep Page)

## Project Overview

Interactive truck trailer load planning tool embedded in the Warship 2 TSR (Transportation Service Request) Prep page. Users visually plan pallet placement inside 53' and 48' dry van trailers with drag-and-drop and form-based input, supporting double-stacking, multi-stop LIFO loading sequences, and real-time weight/space utilization feedback.

**Stack:** FastAPI backend, Bootstrap 5 + Alpine.js frontend, Konva.js (HTML5 Canvas) for the interactive trailer map, MySQL database.

---

## 1. Trailer Specifications (Hardcoded Defaults, User-Adjustable)

### 53' Dry Van (Default)
| Dimension | Value | Notes |
|---|---|---|
| Interior length | 630" (52'6") | Wabash/Great Dane/Utility consensus |
| Interior width | 101" | Wall-to-wall; usable ~99" with E-track |
| Interior height | 110" | Some models 111.25" at rear |
| Swing door opening W | 98.5" | Range 98–99" |
| Swing door opening H | 110" | |
| Cubic capacity | ~4,000 ft³ | |

### 48' Dry Van
| Dimension | Value | Notes |
|---|---|---|
| Interior length | 567" (47'3") | |
| Interior width | 99" | Slightly narrower than 53' |
| Interior height | 110" | |
| Swing door opening W | 99" | |
| Swing door opening H | 110" | |
| Cubic capacity | ~3,570 ft³ | |

### User-Adjustable Fields
- `usableWidth`: 96–101" (default: 101" for 53', 99" for 48') — accounts for E-track, scuff liners
- `usableHeight`: 105–111" (default: 110") — accounts for roll-up doors or ceiling obstructions
- Trailer type toggle: 53' / 48'

---

## 2. Pallet Data Model

```python
# Backend — FastAPI / SQLAlchemy
class Pallet(Base):
    __tablename__ = "load_map_pallets"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    load_plan_id = Column(Integer, ForeignKey("load_plans.id"), nullable=False)
    
    # Dimensions (inches)
    length = Column(Float, nullable=False)          # Stringer direction (e.g., 48")
    width = Column(Float, nullable=False)            # Deck board direction (e.g., 40")
    height = Column(Float, nullable=False)           # Total height including pallet deck
    
    # Weight
    gross_weight = Column(Float, nullable=False)     # lbs, pallet + product
    
    # Placement
    orientation = Column(String(20), nullable=False) # 'straight', 'turned', 'pinwheel'
    x_position = Column(Float, nullable=True)        # Inches from trailer front-left corner
    y_position = Column(Float, nullable=True)        # Inches from trailer left wall
    
    # Stacking
    stackable = Column(Boolean, default=True)        # Can another pallet go on top?
    max_stack_weight = Column(Float, nullable=True)  # Max weight allowed on top (lbs)
    stack_position = Column(String(10), default="floor")  # 'floor' or 'stacked'
    stacked_on_id = Column(Integer, ForeignKey("load_map_pallets.id"), nullable=True)
    
    # Multi-stop
    stop_number = Column(Integer, default=1)         # 1 = first unload (nearest doors), 2, 3...
    
    # Metadata
    label = Column(String(50), nullable=True)        # SKU, PO#, or description
    color = Column(String(7), nullable=True)         # Hex color (auto-assigned by stop)
    sequence = Column(Integer, nullable=True)        # Loading order (reverse of unload)
    commodity = Column(String(100), nullable=True)   # Freight class or commodity type
    
    # Pallet type preset
    pallet_type = Column(String(20), default="GMA")  # GMA-48x40, 48x48, 42x42, 48x45, custom
```

```python
class LoadPlan(Base):
    __tablename__ = "load_plans"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    tsr_id = Column(Integer, ForeignKey("tsr.id"), nullable=False)
    
    trailer_type = Column(String(10), default="53ft")  # '53ft' or '48ft'
    usable_width = Column(Float, default=101.0)
    usable_height = Column(Float, default=110.0)
    
    total_stops = Column(Integer, default=1)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    
    pallets = relationship("Pallet", backref="load_plan", cascade="all, delete-orphan")
```

### Frontend Pallet Object (JavaScript/Alpine.js)
```javascript
{
    id: 'pallet_001',
    length: 48,           // inches
    width: 40,            // inches  
    height: 52,           // inches (product + pallet deck)
    grossWeight: 1800,    // lbs
    
    orientation: 'straight',   // 'straight' | 'turned' | 'pinwheel'
    x: 0,                      // canvas position (inches from front-left)
    y: 0,                      // canvas position (inches from left wall)
    
    stackable: true,
    maxStackWeight: 2000,
    stackPosition: 'floor',    // 'floor' | 'stacked'
    stackedOnId: null,
    
    stopNumber: 1,
    label: 'SKU-A100',
    color: '#4A90D9',          // auto-assigned by stop
    sequence: 1,               // loading order
    commodity: 'Paper goods',
    palletType: 'GMA'          // preset
}
```

---

## 3. Pallet Placement Patterns (Auto-Layout Presets)

### GMA 48×40 in a 53' Trailer (630" × 101")

| Pattern | Orientation | Per Row | Rows | Total | Width Used | Gap |
|---|---|---|---|---|---|---|
| **Straight** | 48" along length, 40" across | 2 | 13 | **26** | 80" | 21" |
| **Turned** | 40" along length, 48" across | 2 | 15 | **30** | 96" | 5" |
| **Pinwheel** | Alternating per row | 2 | 7 sets + 0 | **28** | 88" | 13" |

### GMA 48×40 in a 48' Trailer (567" × 99")

| Pattern | Per Row | Rows | Total |
|---|---|---|---|
| **Straight** | 2 | 11–12 | **22–24** |
| **Turned** | 2 | 14 | **28** |
| **Pinwheel** | 2 | 6 sets | **24–26** |

### Other Pallet Sizes (Presets)
| Type | Dims (L×W) | Straight/53' | Turned/53' | Common Use |
|---|---|---|---|---|
| Square 48×48 | 48"×48" | 26 | 26 | Drums, barrels |
| Square 42×42 | 42"×42" | 30 | 30 | Paint, telecom |
| AIAG 48×45 | 48"×45" | 26 | 28 | Automotive |
| Beverage 36×36 | 36"×36" | 34 | 34 | Beverage |

### Auto-Layout Algorithm
1. User selects pallet preset or enters custom L×W
2. User selects pattern (Straight, Turned, Pinwheel)
3. System calculates: `pallets_across = floor(trailer_width / pallet_across_dim)`
4. System calculates: `rows = floor(trailer_length / pallet_along_dim)`
5. System places pallets on grid starting from the **rear** (for LIFO — Stop 1 nearest doors)
6. User can then manually adjust any pallet via drag-and-drop

---

## 4. Double Stacking Logic

### Rules Engine
```
CAN_STACK(bottom, top) = true IF:
  1. bottom.stackable == true
  2. top.grossWeight <= bottom.maxStackWeight
  3. (bottom.height + top.height) <= trailer.usableHeight
  4. top.length <= bottom.length AND top.width <= bottom.width  (no overhang)
  5. bottom.stackPosition == 'floor'  (no triple-stacking)
```

### Stack Slot Model
Each floor position is a "slot" that holds 0–2 pallets:
```javascript
{
    floorPallet: { ...palletData },
    topPallet: { ...palletData } | null,
    totalHeight: computed,         // bottom.height + (top?.height || 0)
    totalWeight: computed,         // bottom.grossWeight + (top?.grossWeight || 0)
    heightUtilization: computed,   // totalHeight / trailer.usableHeight * 100
    heightStatus: computed         // 'ok' (<85%), 'warning' (85-95%), 'over' (>95% or exceeds)
}
```

### UI Behavior for Stacking
**Top-Down View:**
- Floor pallets render normally
- Stacked pallets show a **card-stack offset** (3px shadow offset bottom-right) indicating depth
- Badge overlay: `"2×"` or `"1/2 | 2/2"` count indicator
- Pallet fill color has a subtle **diagonal stripe overlay** when stacked (to visually distinguish from single-layer)
- Click a stacked position → popover shows both pallets with their individual LWH, weight, and a mini height bar

**Side View (Toggle):**
- Cross-section view looking from the rear doors into the trailer
- Y-axis: 0–110" (trailer height), X-axis: each row position from front to rear
- Each row renders as a vertical bar chart showing filled height vs. ceiling
- Color-coded: green (<80% of 110"), yellow (80–95%), red (>95% or overheight)
- Stacked pallets shown as two distinct segments with a dividing line
- Ceiling line drawn as a prominent red dashed line at usableHeight

### Stacking Interaction
- **To stack:** Drag a pallet from the palette/form onto an existing floor pallet. If `CAN_STACK` passes, it snaps on top. If not, show toast error explaining why (overweight, overheight, bottom not stackable, overhang).
- **To unstack:** Click the stacked pallet → "Remove from stack" button → pallet returns to the palette/input form
- **Form mode:** Select a floor pallet from dropdown → "Stack on top" button with a second pallet form

---

## 5. Multi-Stop LIFO Loading

### Concept
Pallets are grouped by delivery stop. **Stop 1** (first unload) is placed nearest the **rear doors**. **Stop 2** goes in front of Stop 1. **Stop N** (last unload) goes nearest the **nose/front wall**. This ensures each stop's pallets are accessible without moving other stops' freight — Last In, First Out.

### Stop Color Scheme
```javascript
const STOP_COLORS = {
    1: { fill: '#4A90D9', stroke: '#2C5F8A', label: 'Stop 1 (Rear)' },    // Blue
    2: { fill: '#E8A838', stroke: '#B07D1A', label: 'Stop 2' },            // Amber
    3: { fill: '#5CB85C', stroke: '#3D8B3D', label: 'Stop 3' },            // Green
    4: { fill: '#D9534F', stroke: '#A94442', label: 'Stop 4' },            // Red
    5: { fill: '#9B59B6', stroke: '#7D3C98', label: 'Stop 5 (Front)' },    // Purple
};
```

### LIFO Validation Rules
```
VALID_LIFO(pallets) = true IF:
  For every pallet P with stop_number S:
    No pallet with stop_number > S exists between P and the rear doors
    (i.e., no pallet closer to the doors has a HIGHER stop number)
```

Implementation: sort all pallets by x_position (distance from rear doors). Walk from rear to front. The stop_number should be non-decreasing. If a Stop 2 pallet appears between two Stop 1 pallets, flag a **LIFO violation warning** (yellow border + toast).

### Auto-Layout with Multi-Stop
When auto-laying out with multiple stops:
1. Calculate total pallets per stop
2. Assign rows from rear: Stop 1 fills rows from the door backward
3. Stop 2 starts where Stop 1 ended
4. Continue for each stop
5. Show divider lines between stop zones on the canvas

### Loading Sequence Numbers
Each pallet gets a `sequence` number — the order a forklift should load them:
- Stop N pallets load first (they go to the front/nose)
- Stop 1 pallets load last (they end up at the rear/doors)
- Within a stop, rear-row pallets load before front-row pallets

Display as a circled number overlay on each pallet in the top-down view.

---

## 6. Weight Distribution Visualization

### Metrics Displayed (Real-Time)

```javascript
const metrics = {
    totalWeight: sum(all_pallet_weights),
    maxPayload: 45000,                     // lbs (80K GVW - ~35K tare)
    weightUtilization: totalWeight / maxPayload * 100,
    
    cubeUtilization: totalPalletVolume / trailerVolume * 100,
    
    linearFootUsed: maxPalletXPosition / 12,   // convert inches to feet
    linearFootTotal: trailerLength / 12,
    
    lbsPerLinearFoot: computed_per_row,         // should be ≤ 1000
    
    frontHalfWeight: sum(pallets where x < trailerLength/2),
    rearHalfWeight: sum(pallets where x >= trailerLength/2),
    balanceRatio: frontHalfWeight / rearHalfWeight,  // ideal: 0.8–1.2
    
    leftWeight: sum(pallets where y < trailerWidth/2),
    rightWeight: sum(pallets where y >= trailerWidth/2),
    lateralBalance: leftWeight / rightWeight,         // ideal: 0.95–1.05
};
```

### Visual Indicators
- **Weight gauge bar** (horizontal): Shows totalWeight vs maxPayload. Green/yellow/red zones.
- **Cube utilization bar**: Shows volume used vs total trailer volume.
- **Balance indicator**: A simple dot on a 2D crosshair showing front/rear and left/right weight balance. Center = perfect. Offset = imbalanced.
- **Lbs/ft heat stripe**: Along the trailer length axis, a color-coded stripe showing weight density per linear foot. Green ≤800, Yellow 800–1000, Red >1000.
- **Per-row weight labels**: Small text at each row position showing total weight in that row.

### Weight Rules Summary (Reference)
| Limit | Value |
|---|---|
| Federal GVW | 80,000 lbs |
| Typical tare weight | 33,000–36,000 lbs |
| Typical max payload | 44,000–47,000 lbs |
| Target lbs/linear foot | ≤ 800 |
| Max lbs/linear foot | 1,000 |
| Steer axle limit | 12,000–12,500 lbs |
| Drive tandem limit | 34,000 lbs |
| Trailer tandem limit | 34,000 lbs |

(DOT axle calculations deferred to future version — display limits as reference only.)

---

## 7. Canvas Architecture (Konva.js)

### Layer Stack (4 Layers)
```
Layer 4 (top):  UI Layer        — Snap guidelines, tooltips, selection handles, weight labels
Layer 3:        Pallets Layer   — All draggable pallet groups (rect + label + stack badge)
Layer 2:        Trailer Layer   — Walls, floor, door opening, stop zone dividers (listening: false)
Layer 1 (bottom): Grid Layer   — Ruler markings, grid lines, row/column numbers (listening: false)
```

### Scale & Grid
- **Grid size:** 4 inches (divides evenly into 48, 40, 36, 42)
- **Default scale:** Auto-fit trailer width to canvas width (responsive)
- **Zoom:** Mouse wheel / pinch-to-zoom (Konva native), min 0.3x, max 3x
- **Pan:** Click-drag on empty space (stage.draggable when not on a pallet)

### Trailer Rendering (Top-Down View)
```
Floor:      Rect fill #e8e0d4 (warm wood tone) with subtle gradient darkening toward rear
Walls:      Rect stroke 6px #555 (left, right, front/nose)
Door gap:   Dashed line or open space at rear, with small "door hinge" indicators
Wheel wells: Two small gray rectangles at rear (cosmetic only, non-blocking)
Row markers: Light dashed lines every 48" along length with row numbers
Center line: Light dashed line down the middle of the width
```

### Trailer Rendering (Side View — Toggle)
```
Floor line:   Solid line at y=0
Ceiling line: Red dashed line at y=usableHeight (110")
Left wall:    Solid line at x=0 (nose)
Door opening: Open/dashed at x=trailerLength (rear)
Row stacks:   Vertical bar per row showing pallet heights
              - Bottom pallet: solid fill
              - Top pallet (stacked): lighter fill or hatched
              - Gap between: thin divider line
Height labels: At top of each stack
```

### Pallet Rendering (Konva Group)
Each pallet is a `Konva.Group` containing:
```
- Konva.Rect:  Fill color (by stop), stroke #333, cornerRadius 2
                Shadow: color #000, blur 4, offset {2,2}, opacity 0.3
- Konva.Text:  Label (SKU/PO#), centered, white or dark based on fill contrast
- Konva.Text:  Weight label, smaller font, bottom of pallet
- Konva.Rect:  Stack badge (if stacked) — small "2×" indicator, top-right corner
- Konva.Text:  Sequence number circle, top-left corner
```

**Stacked pallet visual:** When a floor pallet has a top pallet:
- Render a second offset rectangle (+3px, +3px) behind/below the main pallet rect
- Add diagonal line pattern overlay (CSS-style hatching via Konva custom sceneFunc)
- Badge shows "2×" with the combined weight

### Interaction Handlers
```javascript
// Drag with snap-to-grid
pallet.on('dragmove', (e) => {
    // Real-time collision check — turn red if overlapping
    // Show ghost snap position
    // Constrain within trailer bounds
});

pallet.on('dragend', (e) => {
    // Snap to 4" grid
    // Validate: no collision, within bounds
    // If invalid: revert to last valid position
    // If over stackable pallet: offer to stack
    // Recalculate all metrics
    // Save position to backend
});

pallet.on('click', (e) => {
    // Select pallet — show edit panel
    // If stacked: show stack detail popover
});

pallet.on('dblclick', (e) => {
    // Toggle orientation (rotate 90°)
    // Revalidate position after rotation
});
```

### Collision Detection (AABB)
```javascript
function hasCollision(draggedRect, allPallets) {
    const a = draggedRect.getClientRect();
    for (const other of allPallets) {
        if (other === draggedRect) continue;
        if (other.stackPosition === 'stacked') continue; // ignore stacked pallets in floor collision
        const b = other.getClientRect();
        if (a.x < b.x + b.width && a.x + a.width > b.x &&
            a.y < b.y + b.height && a.y + a.height > b.y) {
            return true;
        }
    }
    return false;
}
```

---

## 8. UI Layout (Bootstrap 5 + Alpine.js)

### Page Structure (TSR Prep Page — New Tab or Section)

```
┌─────────────────────────────────────────────────────────────────┐
│  TSR Prep > Load Map                                     [Save] │
├──────────────────────┬──────────────────────────────────────────┤
│                      │                                          │
│   CONTROL PANEL      │        TRAILER CANVAS                    │
│   (Left sidebar,     │        (Konva.js Stage)                  │
│    ~300px fixed)     │                                          │
│                      │   ┌──────────────────────────────────┐   │
│  ┌────────────────┐  │   │  [Top-Down View] / [Side View]   │   │
│  │ Trailer Config │  │   │                                  │   │
│  │ Type: [53'/48']│  │   │   ╔══════════════════════════╗   │   │
│  │ Width: [101"]  │  │   │   ║                          ║   │   │
│  │ Height:[110"]  │  │   │   ║   TRAILER FLOOR PLAN     ║   │   │
│  └────────────────┘  │   │   ║   with pallets            ║   │   │
│                      │   │   ║                          ║   │   │
│  ┌────────────────┐  │   │   ║        ← nose    doors →  ║   │   │
│  │ Add Pallet     │  │   │   ╚══════════════════════════╝   │   │
│  │ Type: [GMA ▼]  │  │   │                                  │   │
│  │ L: [48] W:[40] │  │   └──────────────────────────────────┘   │
│  │ H: [52]        │  │                                          │
│  │ Weight: [1800] │  │   ┌──────────────────────────────────┐   │
│  │ Stop: [1 ▼]    │  │   │  METRICS BAR                     │   │
│  │ Stackable: [✓] │  │   │  Weight: ████████░░ 38,400/45,000│   │
│  │ Max Stack:[2K] │  │   │  Cube:   ██████░░░░ 62%          │   │
│  │ Label: [____]  │  │   │  Lbs/ft: ▓▓▓▓▓▒▒▒░░ (per row)   │   │
│  │ Qty: [1]       │  │   │  Balance: [●] (crosshair)        │   │
│  │ [Add to Plan]  │  │   │  LIFO: ✅ Valid / ⚠️ Violation    │   │
│  └────────────────┘  │   └──────────────────────────────────┘   │
│                      │                                          │
│  ┌────────────────┐  │                                          │
│  │ Auto-Layout    │  │                                          │
│  │ Pattern: [▼]   │  │                                          │
│  │ Straight       │  │                                          │
│  │ Turned         │  │                                          │
│  │ Pinwheel       │  │                                          │
│  │ [Apply Layout] │  │                                          │
│  └────────────────┘  │                                          │
│                      │                                          │
│  ┌────────────────┐  │                                          │
│  │ Stop Manager   │  │                                          │
│  │ Stop 1: 12 plt │  │                                          │
│  │ Stop 2: 8 plt  │  │                                          │
│  │ Stop 3: 6 plt  │  │                                          │
│  │ [+ Add Stop]   │  │                                          │
│  └────────────────┘  │                                          │
│                      │                                          │
│  ┌────────────────┐  │                                          │
│  │ Pallet List    │  │                                          │
│  │ (scrollable)   │  │                                          │
│  │ P1: 48x40 1800#│  │                                          │
│  │ P2: 48x40 2200#│  │                                          │
│  │ ...            │  │                                          │
│  └────────────────┘  │                                          │
├──────────────────────┴──────────────────────────────────────────┤
│  [Export PDF]  [Print Load Map]  [Save & Return to TSR]         │
└─────────────────────────────────────────────────────────────────┘
```

### View Toggle Behavior
- **Top-Down** (default): Standard overhead view of trailer floor with pallets
- **Side View**: Cross-section from rear doors looking toward nose. Shows height utilization per row. Stacked pallets clearly visible as two segments.
- Toggle is a segmented button above the canvas: `[Top-Down] [Side View]`
- Both views share the same data — changes in one reflect in the other
- Keyboard shortcut: `T` to toggle

### Interaction Modes
1. **Select mode** (default): Click pallets to select, drag to move, double-click to rotate
2. **Add mode**: Click on trailer floor to place a new pallet with current form values
3. **Stack mode**: Drag a pallet onto another to initiate stacking (with validation)

### Responsive Behavior
- Canvas auto-resizes to fill available width
- Sidebar collapses to bottom drawer on mobile/tablet
- Touch: drag to move, pinch to zoom, long-press for context menu (rotate, delete, stack)

---

## 9. API Endpoints

```
# Load Plans
GET    /api/tsr/{tsr_id}/load-plan          → Get load plan + all pallets
POST   /api/tsr/{tsr_id}/load-plan          → Create new load plan
PUT    /api/load-plan/{plan_id}             → Update trailer config
DELETE /api/load-plan/{plan_id}             → Delete load plan

# Pallets
POST   /api/load-plan/{plan_id}/pallets     → Add pallet(s)
PUT    /api/load-plan/{plan_id}/pallets/{id} → Update pallet (position, orientation, stack)
DELETE /api/load-plan/{plan_id}/pallets/{id} → Remove pallet
PUT    /api/load-plan/{plan_id}/pallets/batch → Batch update positions (after drag)

# Auto-Layout
POST   /api/load-plan/{plan_id}/auto-layout → Apply pattern (straight/turned/pinwheel)
         Body: { pattern, palletType, palletDims, stopAssignments }

# Stacking
POST   /api/load-plan/{plan_id}/pallets/{id}/stack    → Stack pallet on top of another
DELETE /api/load-plan/{plan_id}/pallets/{id}/unstack   → Remove from stack

# Validation
GET    /api/load-plan/{plan_id}/validate    → Run all validations, return warnings/errors

# Export
GET    /api/load-plan/{plan_id}/export/pdf  → Generate load map PDF
```

---

## 10. Validation Rules (Real-Time)

### Errors (Block save, red indicators)
| Rule | Check |
|---|---|
| Collision | No two floor pallets overlap (AABB) |
| Out of bounds | All pallets within trailer L×W |
| Overheight | stack totalHeight ≤ usableHeight |
| Overweight stack | top.grossWeight ≤ bottom.maxStackWeight |
| Overhang | Stacked pallet dims ≤ bottom pallet dims |
| Triple stack | No pallet stacked on a stacked pallet |

### Warnings (Allow save, yellow indicators)
| Rule | Check |
|---|---|
| LIFO violation | Stop N pallet between doors and Stop M (M < N) |
| Weight over 1000 lbs/ft | Any row exceeds 1,000 lbs per linear foot |
| Lateral imbalance | Left/right weight ratio outside 0.9–1.1 |
| Front/rear imbalance | Front/rear weight ratio outside 0.7–1.3 |
| Payload exceeded | Total weight > 45,000 lbs (configurable) |
| Low utilization | Cube utilization < 50% (informational) |

---

## 11. Pallet Type Presets

```javascript
const PALLET_PRESETS = {
    'GMA':     { length: 48, width: 40, label: 'GMA Standard (48×40)' },
    '48x48':   { length: 48, width: 48, label: 'Square (48×48)' },
    '42x42':   { length: 42, width: 42, label: 'Square (42×42)' },
    '48x45':   { length: 48, width: 45, label: 'AIAG Auto (48×45)' },
    '36x36':   { length: 36, width: 36, label: 'Beverage (36×36)' },
    'custom':  { length: null, width: null, label: 'Custom Dimensions' },
};
```

---

## 12. Export / Print

### PDF Load Map
Generate a printable load map containing:
- Top-down trailer diagram with pallet positions, labels, and sequence numbers
- Side view showing height utilization
- Summary table: total pallets, total weight, cube utilization, stop breakdown
- Pallet manifest: list of all pallets with dims, weight, stop, position
- Weight distribution chart (lbs/ft per row)
- LIFO compliance status
- TSR reference number, date, prepared by

### Print-Friendly
- CSS `@media print` styling for the canvas view
- Or use server-side `Konva.toDataURL()` → embed in PDF template

---

## 13. Design Aesthetic

### Direction: Industrial-Utilitarian with Precision
This is a **tool for warehouse and logistics professionals** — not a consumer app. The aesthetic should feel like a **precision instrument panel**: clean, information-dense, high-contrast, and zero fluff.

### Color Palette
```css
--bg-primary: #1a1d23;        /* Dark charcoal background */
--bg-secondary: #242830;      /* Panel backgrounds */
--bg-canvas: #2a2e36;         /* Canvas area background */
--trailer-floor: #3d3529;     /* Warm dark wood (trailer floor) */
--trailer-wall: #6b6b6b;      /* Metallic gray (walls) */
--text-primary: #e8e8e8;      /* High contrast text */
--text-secondary: #9ca3af;    /* Muted labels */
--accent: #f59e0b;            /* Amber — action buttons, highlights */
--success: #22c55e;           /* Green — valid, under limit */
--warning: #f59e0b;           /* Amber — approaching limit */
--danger: #ef4444;            /* Red — over limit, errors */
--grid-line: rgba(255,255,255,0.06); /* Subtle grid */
```

### Typography
- Headings / labels: **JetBrains Mono** or **IBM Plex Mono** (monospace — fits the precision/industrial theme)
- Body / form fields: **IBM Plex Sans** (clean, readable, industrial)
- Canvas labels: monospace, small (10–12px equivalent at default zoom)

### Key Design Details
- **Canvas border:** 1px solid #444 with 2px inset shadow — feels like a recessed instrument panel
- **Pallets:** Slight corner radius (2px), drop shadow, visible stroke. Stop colors are saturated but not neon.
- **Metrics bar:** Horizontal gauges with segmented fill (green → yellow → red thresholds). Numbers in monospace.
- **Sidebar:** Dark panels with subtle borders, compact spacing, form inputs with dark background (#1e2028) and light borders
- **Buttons:** Amber accent for primary actions, ghost/outline for secondary
- **Tooltips on hover over pallets:** Show full details (dims, weight, stop, sequence) in a floating dark card

---

## 14. File Structure (Within Warship 2)

```
warship2/
├── app/
│   ├── routers/
│   │   └── load_map.py              # API endpoints
│   ├── models/
│   │   └── load_map.py              # SQLAlchemy models
│   ├── services/
│   │   ├── load_map_service.py      # Business logic
│   │   ├── auto_layout.py           # Pallet placement algorithms
│   │   ├── load_validation.py       # All validation rules
│   │   └── load_map_pdf.py          # PDF export generator
│   ├── templates/
│   │   └── load_map/
│   │       ├── load_map.html        # Main page template
│   │       └── partials/
│   │           ├── _sidebar.html    # Control panel
│   │           ├── _canvas.html     # Konva canvas container
│   │           └── _metrics.html    # Metrics bar
│   └── static/
│       └── js/
│           ├── load-map/
│           │   ├── canvas.js        # Konva setup, layers, rendering
│           │   ├── pallets.js       # Pallet creation, drag, snap, collision
│           │   ├── stacking.js      # Stack logic and validation
│           │   ├── side-view.js     # Side view rendering
│           │   ├── metrics.js       # Real-time metric calculations
│           │   ├── auto-layout.js   # Client-side layout preview
│           │   ├── multi-stop.js    # LIFO sequence management
│           │   └── export.js        # PDF/print export
│           └── lib/
│               └── konva.min.js     # Konva.js library
```

---

## 15. Implementation Phases

### Phase 1: Core Canvas + Basic Placement
- Trailer rendering (top-down, 53' and 48')
- Single pallet creation via form
- Drag-and-drop with snap-to-grid
- Collision detection
- Basic weight/cube metrics
- Save/load from database

### Phase 2: Stacking + Side View
- Double-stack logic and validation
- Side view toggle with height bars
- Stack UI interactions (drag-to-stack, unstack)
- Height utilization display

### Phase 3: Multi-Stop LIFO
- Stop manager UI
- Stop-based color coding
- LIFO validation
- Loading sequence numbering
- Stop zone dividers on canvas
- Auto-layout with multi-stop support

### Phase 4: Auto-Layout + Polish
- Pattern presets (straight/turned/pinwheel)
- Auto-layout engine with stop awareness
- Pallet type presets
- PDF export
- Print styling
- Keyboard shortcuts
- Mobile/touch optimization

---

## 16. Dependencies

### Backend
- FastAPI (existing)
- SQLAlchemy (existing)
- MySQL (existing)
- ReportLab or WeasyPrint (PDF export)

### Frontend
- Bootstrap 5 (existing)
- Alpine.js (existing)
- **Konva.js** (NEW — CDN or local: ~150KB minified)
- No additional build tools needed — vanilla JS modules

### CDN
```html
<script src="https://unpkg.com/konva@9/konva.min.js"></script>
```

---

## 17. Key Konva.js Patterns to Follow

### Snap-to-Grid
```javascript
const GRID = 4; // 4-inch grid
pallet.on('dragend', () => {
    pallet.position({
        x: Math.round(pallet.x() / GRID) * GRID,
        y: Math.round(pallet.y() / GRID) * GRID,
    });
    palletsLayer.batchDraw();
});
```

### Boundary Constraint
```javascript
pallet.on('dragmove', () => {
    const pos = pallet.position();
    const w = pallet.width(), h = pallet.height();
    pallet.position({
        x: Math.max(0, Math.min(pos.x, trailerLength - w)),
        y: Math.max(0, Math.min(pos.y, trailerWidth - h)),
    });
});
```

### Performance Settings
```javascript
// Static layers
gridLayer.listening(false);
trailerLayer.listening(false);

// Pallets that only translate
pallet.transformsEnabled('position');

// Batch redraws
palletsLayer.batchDraw();

// Cache complex static shapes
trailerOutline.cache();
```
