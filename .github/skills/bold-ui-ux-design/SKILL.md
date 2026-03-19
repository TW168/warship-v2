---
name: bold-ui-ux-design
description: Instructions for building impressive, professional light-themed layouts.
---

# UI/UX Style Guide: "Professional Bold"

## Visual Constraints
- **Theme:** Strictly **Light Mode**. No dark backgrounds allowed.
- **Primary Background:** `#F8FAFC` (Slate 50).
- **Metric Cards:** `bg-white border border-slate-200 rounded-3xl p-6 shadow-sm`.
- **Typography:** Use `font-extrabold` for primary KPIs. Use `tracking-tight` for headers.

## Component Patterns (Tailwind + HTMX)
- **Active States:** Add `active:scale-95 transition-transform` to every button.
- **Loading States:** Use "Skeleton Screens" (`animate-pulse`) for any data-heavy visualization being loaded via HTMX.
- **Grid System:** Use a **Bento Grid** layout. Large blocks for core trends (LMI), smaller blocks for secondary metrics (Gas Prices).

## Design Review
- Before finalizing a template in `templates/`, ensure there is sufficient white space.
- Ensure all charts use a high-contrast palette (e.g., Indigo-600, Emerald-500, Rose-500).
