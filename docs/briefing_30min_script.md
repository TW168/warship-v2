# Warship 30-Minute Executive Briefing Script
## AMJK / SW — YTD 2026 (as of June 4, 2026)

> **Every number in this script comes directly from the Warship system. Do not paraphrase metrics — say them exactly. If the screen shows something different from what's printed here, use the screen number and say so.**

---

## Pre-Brief Setup (10 minutes before the meeting starts)

Open all twelve tabs in this order. They map one-to-one to the speaking segments below.

| # | URL | What you're showing |
|---|-----|---------------------|
| 1 | `/summary` | Full printable slide deck — your backup if the live app has issues |
| 2 | `/briefing` | Safety card, volume trend, freight cost trend, boxplot, AI summary |
| 3 | `/meeting-report` | MTD shipped weight + pallets by site (AMJK, TXAS, AMIN, AMAZ) |
| 4 | `/shipping` | Carrier Cost Per Pound bubble chart + customer tree map |
| 5 | `/maintenance/freight-driver` | Product ¢/lb waterfall decomposition (risers tab first) |
| 6 | `/maintenance/freight-audit` | Three-method ¢/lb cross-check |
| 7 | `/warehouse` | UDC hourly bar chart, ASH event heatmap, pallet entry/exit |
| 8 | `/warehouse/product-forecast` | Per-product trend direction + R² confidence |
| 9 | `/maintenance/shipment-size-impact` | Scissors chart + Extra Loads YTD |
| 10 | `/tsr-prep` | Available-to-ship BL list + geo map |
| 11 | `/silos-status` | Current inventory cards, consumption rate, anomaly queue |
| 12 | `/maintenance/lmi` | LMI Transportation Prices sub-index trend |

**Filters — set these before anyone walks in:**
- Site = `AMJK` · Product Group = `SW`
- Date range = `Jan 1, 2026` → latest complete month (May 31, 2026)
- **June is a partial month.** Every time June data appears on screen, say the words "provisional, month is not closed" out loud. Do not let a partial month distort a YoY comparison.

**If asked for a number you do not have on screen:**
> "Let me pull that directly from Warship — five seconds."
> Never estimate. Never round. Read the system.

---

## 30-Minute Agenda

| Segment | Time | Source Page | Topic |
|---------|------|-------------|-------|
| 1 | 00:00 – 02:00 | `/summary` slide 1 | Who we are — team, shifts, safety record |
| 2 | 02:00 – 06:00 | `/briefing` | Volume and the cost divergence headline |
| 3 | 06:00 – 11:00 | `/maintenance/freight-driver` + `/maintenance/freight-audit` | Which products and carriers drove the freight spike |
| 4 | 11:00 – 15:00 | `/shipping` + `/meeting-report` | Carrier concentration, customer mix, MTD site performance |
| 5 | 15:00 – 19:00 | `/warehouse` + `/warehouse/product-forecast` | Pallet flow, UDC missions, ASH events, product direction |
| 6 | 19:00 – 22:00 | `/maintenance/shipment-size-impact` | Why workload is actually lighter than the tonnage number looks |
| 7 | 22:00 – 25:00 | `/tsr-prep` | Dispatch readiness: BL list, geo map, pallet fit check |
| 8 | 25:00 – 28:00 | `/silos-status` + `/maintenance/lmi` + exception pages | Inventory health, market context, data controls |
| 9 | 28:00 – 30:00 | — | Three risks, three actions, three decisions needed |

---

## Full Talk Track

---

### SEGMENT 1 — Who We Are (00:00 – 02:00)

**Source:** `/summary` Slide 1 — open this tab, it is print-ready if live data fails

> **"Let me start with who is in this room on the operational side. CFP Warehouse and Shipping at AMJK is eleven people on two shifts, Monday through Friday, plus the last two Saturdays of every month as eight-hour workdays."**

> **"The team: one supervisor, one assistant supervisor, two office staff, one warehouse lead, and six forklift drivers. Warehouse runs day shift 7:00 AM to 3:30 PM, night shift 3:30 PM to midnight. Shipping runs 7:30 AM to 4:30 PM and 8:30 AM to 5:30 PM."**

> **"Since 2021 — zero recordable accidents. Five consecutive years. Zero injuries. That number does not appear on any freight invoice or cost report, but it is the most important number in this briefing. Every other metric in the next 28 minutes is built on top of a team that comes to work safely every day."**

> **"Today I will answer three leadership questions: Are we safe and in control? Are we shipping efficiently? Where is cost rising faster than volume and what do we do about it?"**

> **"Every number is live from Warship. No spreadsheets."**

*Transition:* "Here is the headline."

---

### SEGMENT 2 — Volume and the Cost Divergence (02:00 – 06:00)

**Source:** `/briefing` — Executive Summary card, Pick Weight Trend by Year, Freight Cost Trend by Year

*Switch to the `/briefing` tab. Cards load automatically from the live database.*

#### Volume — the good news

> **"Year to date, January through May 2026, we shipped 59.8 million pounds. Same five months last year: 54.6 million pounds. Year-over-year growth: 9.5 percent."**

> **"The monthly chart on screen shows each year as a separate line. The 2026 line is above 2025 in every single month. Demand is growing. The operation is absorbing it."**

*Point to the Pick Weight Trend chart. The 2026 line tracks above all prior years.*

#### The cost divergence — the problem

> **"Now look at the freight cost chart. The 2026 line does not just sit above 2025 — it is pulling away. Volume is up 9.5 percent. Freight cost per pound is up 11.7 percent."**

> **"In 2025 we ran at 7.68 cents per pound. In 2026 we are at 8.58 cents per pound. That is 90 basis points of unit cost inflation on top of a 9.5 percent volume increase. We are shipping more and paying more per pound to do it."**

> **"The gap is 2.2 percentage points between volume growth and cost growth. That gap is not going to close by itself. The next segment explains exactly where it is coming from."**

#### What the AI summary says

*Scroll to the AI Executive Summary card at the bottom of `/briefing`.*

> **"The system streams a narrative from our own local AI model using only the numbers already on this screen. It cannot invent data — it interprets data we fed it. The three-section output: TREND shows what happened, WHY identifies the cause, IMPROVE recommends the next action. Use it as a closing statement or as your action list for Q3 planning."**

*Transition:* "Let me now show you exactly which products and carriers are responsible for those 11.7 percent higher costs."

---

### SEGMENT 3 — Freight Cost Root Cause: Products and Carriers (06:00 – 11:00)

**Source:** `/maintenance/freight-driver` → Risers toggle → product waterfall
**Source:** `/maintenance/freight-audit` → three-method cross-check
**Source:** `/briefing` → Freight ¢/lb by Product Code boxplot

#### The boxplot — level and stability at a glance

*Switch to `/briefing`. Scroll to the Freight ¢/lb by Product Code boxplot.*

> **"Each box in this chart is one product code. The horizontal center line inside the box is the median freight rate for that product this year. The height of the box is the rate variability — how much the rate swings from load to load. Dots outside the box are outlier loads."**

> **"A tall narrow box means the carrier is pricing that product consistently. A short wide box means volatile pricing. A box that sits far to the right means you are paying a high rate on every load — consistently."**

> **"This chart identifies your negotiation and routing targets in one view."**

#### The biggest movers — real numbers

*Switch to `/maintenance/freight-driver`. Click the Risers tab.*

> **"The Freight Driver page ranks every SW product by year-over-year change in blended cents per pound. These are the top three increases:"**

> **"PSB0381501476AM-144P: 4.79 cents last year, 9.98 cents this year. Plus 108.5 percent. That product more than doubled in freight cost. This is the single largest driver of the 11.7 percent overall increase."**

> **"HCB0701801500AM-64: 5.64 cents to 8.76 cents. Plus 55.4 percent."**

> **"HSB0631601500AM-64: 9.61 cents to 12.58 cents. Plus 30.9 percent."**

> **"Three products going in the other direction — costs came down:"**

> **"EHB0632955000AM-25: 8.68 to 6.36 cents. Down 26.7 percent. PSB0331501476ENV-36: down 19.4 percent. EPB0802006000AM-40: down 15.2 percent."**

> **"The fact that some products got cheaper this year proves we are not in a pure market environment where every rate is rising. These are product-specific and carrier-specific movements."**

#### Decomposition — rate effect versus mix effect

*Click into PSB0381501476AM-144P. The waterfall chart loads.*

> **"Warship separates each product's year-over-year change into two components. The rate effect is how much the carrier's price per pound changed. The mix effect is how much of the change came from us using a different carrier mix than last year — shifting volume toward a more expensive carrier even if no individual carrier raised its rate."**

> **"These are two completely different problems with two completely different fixes. Rate effect means you negotiate. Mix effect means you look at your routing decisions. You cannot fix a mix problem with a rate negotiation."**

> **"We have not yet run this decomposition for PSB0381501476AM-144P for this briefing. That is Action One after this meeting."**

#### Three-method audit — are these numbers real?

*Switch to `/maintenance/freight-audit`.*

> **"Before I present any freight metric in an executive setting, the Freight Audit page runs three independent calculations against the same dataset:"**

> **"Method A: weighted average of the Unit_Freight rate column by pick weight. Method B: all-in dollar amount from Freight_Amount column divided by total pounds times 100. Method C: the stored procedure used by the Carrier Cost page. Three different code paths, three different source columns. All three agree on the 11.7 percent increase. We are not chasing a rounding error."**

*Transition:* "Now I will show the carrier picture and where our shipments are going."

---

### SEGMENT 4 — Carrier Concentration, Customer Mix, MTD Site Performance (11:00 – 15:00)

**Source:** `/shipping` → Carrier Cost Per Pound bubble chart, Customer Tree Map
**Source:** `/meeting-report` → All Site MTD card

#### Carrier cost bubble chart

*Switch to `/shipping`. The Carrier Cost Per Pound bubble chart loads at the bottom of the page.*

> **"This is the full carrier panel for AMJK SW year to date. Each bubble is one carrier. Bubble size represents total pounds shipped through that carrier. Vertical axis is cost in cents per pound."**

> **"We ran 1,772 loads year to date. GILTNER handled 555 of those — 31.3 percent of all loads. AAL is second at 25.4 percent. Combined, those two carriers handle 56.7 percent of our entire freight volume."**

> **"That concentration is inside a manageable range today. The risk is Q3 peak season. If GILTNER has a capacity problem — driver shortage, equipment issue, lane bid conflict — 31 percent of our loads need to find a home quickly. We do not currently have a pre-approved overflow carrier at scale."**

> **"On cost: DRAKE is the most expensive real carrier at 14.15 cents per pound across 157 loads. GILTNER runs more than three times that volume and at a lower rate. The DRAKE relationship deserves a specific renegotiation conversation with the GILTNER rate as the anchor."**

*Point to carriers in the upper-right of the chart.*

> **"Carriers in the upper-right are expensive and high-volume. That is where budget is going. Carriers in the lower-left are your cost-efficient workhorses. Protect those lanes."**

#### Customer tree map

*Scroll to the Customer Tree Map on `/shipping`.*

> **"The tree map shows where our shipments are physically going. Box size is proportional to total shipped weight. Year to date:"**

> **"WESTERN PLASTICS is the single largest customer at 6.04 million pounds. SYNTRANET is second at 2.38 million. BAUMRUCKER, LEGACY PAPER, and WESTERN PLASTICS CA each sit between 1.38 and 1.44 million."**

> **"WESTERN PLASTICS alone represents approximately 48 percent of the top-five customer weight. If that account slows down, the operation feels it immediately. That is a retention priority, not just a service priority."**

#### Multi-site MTD performance

*Switch to `/meeting-report`. Select the current year-month. The All Site MTD card loads.*

> **"The Meeting Report gives us the same MTD shipped weight and pallet comparison across all four sites: AMJK, TXAS, AMIN, and AMAZ. This lets leadership see in one view whether AMJK is running ahead or behind the network on a monthly basis."**

> **"This is the number to pull when someone asks how we compare to the other sites this month. It is live, not a report that was exported last week."**

*Transition:* "Now I will show what the warehouse floor actually looked like while we were moving all of this."

---

### SEGMENT 5 — Warehouse Floor: Pallet Flow, UDC Missions, ASH Events, Product Forecast (15:00 – 19:00)

**Source:** `/warehouse` → Pallet entry/exit, UDC hourly, ASH heatmap
**Source:** `/warehouse/product-forecast` → trend directions + R²

#### Pallet entry and exit

*Switch to `/warehouse`. The pallet entry/exit chart is the first visible element.*

> **"May 1 through June 2: 11,104 pallets received from production. 11,219 pallets shipped out to trucks. Net: minus 115 pallets — essentially flat."**

> **"Blue bars are production inbound. Gold bars are truck outbound. For every pallet that came in from the plant this month, one went out to a customer. At a 9.5 percent higher volume year over year, that balance does not happen by accident."**

> **"If these bars diverge — if inbound significantly exceeds outbound for more than two consecutive days — that is the early warning for dock congestion or a scheduling problem. The chart gives us that signal the same day it starts, not after inventory has backed up for a week."**

#### UDC hourly missions

*Scroll to the UDC Hourly chart.*

> **"UDC tracks automated warehouse missions by hour of day. The hourly bar chart shows when the system is peak-loaded. Consistently high afternoon bars with low morning bars suggests the floor is starting slow and catching up — that pattern is a scheduling optimization opportunity."**

> **"The history line chart shows daily mission totals over time. A sudden drop in daily totals without a corresponding drop in shipped weight usually means manual overrides or a system mode change — something to investigate before it becomes a gap in traceability."**

#### ASH event heatmap

*Scroll to the ASH heatmap.*

> **"Every exception the automated system generates is logged as an ASH event. The heatmap breaks them down by event type on one axis and time on the other. What we are looking for: clusters."**

> **"A random scatter is normal operational variance — things that happened once and resolved. A cluster of the same event type on the same day of week or same time of day is a process defect or equipment pattern. That pattern is the difference between a one-time fix and a recurring problem that we need to eliminate."**

#### Product forecast

*Switch to `/warehouse/product-forecast`.*

> **"The Product Forecast dashboard runs a linear regression on each product's monthly shipped weight history and classifies the trend as INCREASE, DECREASE, or STABLE. Each product shows its regression R-squared — that tells you how much to trust the direction."**

> **"R-squared above 0.7: the trend is reliable, use it for planning. Below 0.4: the product is volatile or newly active — treat the direction as watch-list only, not a planning commitment."**

> **"The reason this matters operationally: if three of our top-ten products by weight are trending DECREASE simultaneously, that is a demand mix shift that needs a conversation with sales before the dock schedule is locked. The forecast gives us the lead time to have that conversation."**

*Transition:* "Now I will show why the workload number this year is actually better than the volume increase makes it look."

---

### SEGMENT 6 — Shipment Size and Workload Pressure (19:00 – 22:00)

**Source:** `/maintenance/shipment-size-impact` → scissors chart, Extra Loads YTD

*Switch to `/maintenance/shipment-size-impact`.*

> **"This is the chart that surprises people who have only seen the volume number."**

> **"Volume is up 9.5 percent. You would expect workload to be up 9.5 percent too. It is not. Workload is up less than volume because the average shipment got larger."**

> **"In 2025, average load size was 20,905 pounds per truck. In 2026, average load size is 22,449 pounds per truck. That is 7.4 percent larger loads. Bigger loads mean fewer truck appointments, fewer dock cycles, fewer staging moves, fewer paperwork events — for the same total tonnage."**

*Point to the scissors dual-axis chart. The two lines move in opposite directions.*

> **"The scissors pattern: as average lbs per load goes up on one axis, loads per million lbs goes down on the other axis. When those two lines cross, workload intensity is shifting. We are currently on the favorable side of the scissors."**

> **"The Extra Loads YTD number in the summary panel tells you how many additional truck appointments we would have needed this year if we had run 2025-sized loads instead of 2026-sized loads. That is the quantified workload benefit of the size improvement."**

> **"The risk I want leadership to understand: this advantage disappears if customers shift to ordering smaller, more frequent quantities. A 5 percent drop in average load size at current volume would add hundreds of dock appointments over the course of a year without adding a single pound of freight revenue."**

> **"We monitor this monthly. If average load size drops below 21,000 pounds — trending back toward 2025 levels — that triggers a workload pressure review before the schedule is locked."**

*Transition:* "Now dispatch. How do we set up the loads before they leave the building?"

---

### SEGMENT 7 — Dispatch Readiness: TSR Prep (22:00 – 25:00)

**Source:** `/tsr-prep` → BL list table, geographic map, pallet size lookup

*Switch to `/tsr-prep`.*

> **"TSR Prep is where dispatch planning connects physical inventory to route reality. The page shows every available-to-ship bill of lading right now — product code, weight, customer, site."**

> **"The map below the table plots every active destination as a pin. The nearest-neighbor algorithm draws routing lines between them and overlays radius circles to show geographic clusters. When three shipments are going to the same metro area in the same week, dispatch can see that in five seconds and make a consolidation decision before a truck is booked."**

> **"The detail that matters in practice: same-city customers would stack on top of each other as a single pin. Warship jitters those pins so each destination has a separate, visible marker. A planner who cannot distinguish which customer is which makes worse routing decisions. This eliminates that confusion."**

> **"Pallet size data comes directly from the product dimension table — dimensions and configuration for every product code. Dispatch knows before commitment whether the product physically fits the trailer. Catching a misfit before booking eliminates rejected loads at the dock — a cost that never shows up on a freight invoice but is real."**

> **"Upload workflow: the IPG EZ Excel report drops in, the system validates the column headers, parses every row, and upserts the BL list. The map refreshes from that data. Planning is live within minutes of the Excel arriving in email."**

*Transition:* "Last section: the controls that keep all of this data trustworthy."

---

### SEGMENT 8 — Inventory Health, Market Context, Data Controls (25:00 – 28:00)

**Source:** `/silos-status`, `/maintenance/lmi`, `/maintenance/not-in-xfcma`, `/maintenance/shipment-scan`, `/maintenance/sales-summary`

#### Silos: live inventory with anomaly detection

*Switch to `/silos-status`.*

> **"Silos Status starts with a current inventory card row — percent full per vessel, product weight, last measurement time, and alarm code if one is active. Below that, a daily trend chart shows the fill trajectory over the last 30 days for each vessel and content type."**

> **"The consumption rate panel calculates how fast each material is being used in pounds per day, and from that derives a days-remaining estimate. That number feeds raw material planning before the vessel actually runs low."**

> **"Every time a new CSV is uploaded, the system runs a full anomaly feature pipeline: rolling statistics, z-scores, run-length encoding on fill level and consumption rate. If any vessel's behavior falls outside its statistical baseline, the system generates an anomaly event. The event queue has three states: open, acknowledged, closed. Events do not disappear — they are tracked until someone explains or resolves them. This is how we avoid a silo surprise."**

#### Market context: LMI Transportation Prices

*Switch to `/maintenance/lmi`. Show the trend chart.*

> **"The LMI is the Logistics Manager's Index — a monthly diffusion index from logistics professionals across the US. Any reading above 50 means the logistics market is expanding. Below 50 means contraction."**

> **"Here is the trajectory that is relevant to our freight cost story: the LMI Transportation Prices sub-index ended 2025 at 66.7 in December — the highest reading since January when the year started with an inventory pull-forward. It then spent the first quarter of 2026 climbing. The overall LMI hit 65.7 in March 2026, up from 54.2 in December 2025."**

> **"What this tells us: the freight market we are operating in is in expansion territory. Transportation prices are rising across the industry, not just on our lanes. The Freight Driver page uses this LMI data to help separate how much of our 11.7 percent increase is the market doing this to everyone versus decisions we made that we can change."**

> **"You cannot negotiate your way to a 2023 rate in a 2026 market. But you can control the mix of carriers you use and the routing decisions you make — and those are the levers the Freight Driver page identifies."**

#### Exception workflows: the data accuracy layer

> **"Three maintenance pages that may look administrative are actually where data accuracy lives:"**

> **"Not-in-XFCMA: every week the QPQUPRFIL report is uploaded as a PDF. Warship parses it and shows product that physically exists in the warehouse but is not registered in the location system. Without this list, those pallets are invisible to planning and cannot be allocated to orders. We find them before the customer calls."**

> **"Shipment Scan: the daily scan Excel file uploads with automatic duplicate detection. Historical scan records are stored and queryable. When a discrepancy shows up between what was scanned and what was invoiced, we trace it in seconds rather than days."**

> **"Sales Summary: the daily MKORSHDK PDF is parsed and stored with order, shipment, and backlog metrics by product code. When a freight cost spikes on a product — like PSB doubling — the first cross-reference question is whether the order volume changed at the same time. The Sales Summary data answers that question without a phone call to sales."**

*Transition:* "Based on all of that, here are the specific risks, actions, and decisions."

---

### SEGMENT 9 — Three Risks, Three Actions, Three Decisions (28:00 – 30:00)

#### The Three Risks

> **"Risk one: Freight unit cost is growing 2.2 points faster than volume. Three product codes — PSB0381501476AM-144P at plus 108.5 percent, HCB0701801500AM-64 at plus 55.4 percent, and HSB0631601500AM-64 at plus 30.9 percent — are the primary contributors. If we enter Q3 peak season without decomposing and addressing those, the gap widens under higher volume."**

> **"Risk two: GILTNER and AAL combined handle 56.7 percent of our loads. Dual-carrier concentration at that level means one capacity disruption from either carrier in peak season directly impacts service and creates cost pressure on whoever absorbs the overflow. We do not have a pre-approved third option at scale."**

> **"Risk three: WESTERN PLASTICS represents approximately 48 percent of top-five customer weight. That is a single-account concentration risk in our outbound book. Retention of that relationship is as important as cost management — losing 20 percent of their volume would be felt immediately in both throughput and carrier utilization."**

#### The Three Actions This Week

> **"Action one: Run the Freight Driver decomposition for PSB0381501476AM-144P — rate effect versus carrier mix effect. The fix is different for each. This takes under five minutes in the app and produces a number. Do not schedule a freight review meeting without this number in hand first."**

> **"Action two: Open a rate conversation with DRAKE using the carrier bubble chart as the anchor. 14.15 cents per pound, 157 loads. The data is in the system. The conversation needs to happen before Q3 volumes justify expanding that carrier's share."**

> **"Action three: Establish a shipment-size floor trigger. If average lbs per load drops below 21,000 — the midpoint between this year's 22,449 and last year's 20,905 — a workload pressure review is triggered before the dock schedule is finalized for that week."**

#### The Three Decisions Needed from Leadership

> **"Decision one: Set the carrier concentration ceiling. Is 35 percent a single-carrier acceptable maximum? At 31.3 percent, GILTNER is inside that threshold. If the ceiling is 30 percent, we begin a deliberate diversification action now, before the contract cycle."**

> **"Decision two: Authorize DRAKE renegotiation. The data supports it. The ask is not a broad freight review — it is one specific carrier, one data-backed conversation."**

> **"Decision three: Fix the governance cadence. Every number on this screen regenerates from live data in under 30 seconds. A monthly Warship evidence review replaces ad-hoc report requests and gives leadership a consistent, auditable basis for freight and operations decisions. What day of the month do you want this on the calendar?"**

---

### Close (29:45 – 30:00)

> **"One sentence: we are running a safe, balanced, growing operation with a specific and addressable cost problem — and we have the evidence to fix it."**

> **"Questions: safety first, then cost, then carrier strategy, then implementation timing."**

---

## Q&A Bank

**Q: Why should we trust the 8.58 ¢/lb number?**
> "Three independent methods — Unit_Freight weighted average, Freight_Amount all-in, and the stored procedure — all run against the same dataset on the Freight Audit page and all agree. It is not from one query."

**Q: Is the freight increase the market or us?**
> "The LMI Transportation Prices sub-index at `/maintenance/lmi` was 66.7 in December 2025 and rising into Q1 2026 — the freight market is genuinely in expansion. But the market does not explain a specific product doubling from 4.79 to 9.98. The product-level decomposition on the Freight Driver page separates what the market did from what our routing decisions did."

**Q: PSB more than doubled — is that an error?**
> "That is the validated figure from three methods. Whether it is a carrier rate increase, a shift to a more expensive carrier, or a change in destination mix is exactly what the Freight Driver waterfall will tell us. The number is correct. The cause needs the decomposition."

**Q: The warehouse is balanced — is that sustainable?**
> "At 9.5 percent more volume with the same headcount, balance comes from load size growing 7.4 percent — fewer dock appointments per million pounds shipped. The product forecast page identifies which product lines are growing or shrinking so we can plan headcount adjustments before the floor feels them."

**Q: What is WESTERN PLASTICS receiving and does that concentration concern us?**
> "6.04 million pounds year to date. They are approximately 48 percent of top-five customer weight at AMJK SW. The tree map on `/shipping` updates live. The concern is not the volume — it is the dependency. A 20 percent reduction in their order rate would be felt immediately in carrier utilization and dock throughput."

**Q: What does the LMI reading of 65.7 in March mean for Q3?**
> "65.7 is well above the 50 breakeven and above the long-run average of 61.4. Transportation Prices have been in expansion since Q4 2025. The trend for respondent predictions is that capacity will tighten and prices will stay elevated through the next 12 months. We should not plan Q3 freight budgets assuming a return to 2024 rates."

**Q: June data on the briefing page — should we trust it?**
> "June is a partial month. Every June comparison in this briefing is provisional. We use complete months — January through May — for all YoY calculations. June numbers are shown for context only until the month closes."

**Q: Can this presentation be regenerated for next month without rebuilding it?**
> "Yes. Every chart, every KPI tile, every AI summary on `/briefing` and `/summary` loads from live database queries. Change the date filter, press reload, every number updates. Under 30 seconds. No spreadsheet involved."

---

## Delivery Notes

- Target 120–130 words per minute. Numbers take longer than words — do not rush them.
- State the headline metric, then the implication. Do not narrate the chart.
- When challenged, navigate to the source page and point to the number. Never debate from memory.
- Every segment ends with one operational implication or decision, not a recap of what you just showed.
- The briefing is exactly 30 minutes when setup is complete before the meeting starts.