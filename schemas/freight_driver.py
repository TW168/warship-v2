"""Pydantic models for freight ¢/lb root-cause drill-down analytics.

These power the "Why is this product's freight ¢/lb rising?" page, which
decomposes a product's year-over-year blended ¢/lb change into carrier-mix and
carrier-rate effects (with shipment-size context and outlier loads), and a
companion "biggest ¢/lb increases" risers ranking.
"""

from __future__ import annotations

from pydantic import BaseModel


class FreightDriverMonth(BaseModel):
    """One month of blended ¢/lb metrics for a single product."""

    year: int
    month: int
    ym: str  # "YYYY-MM"
    blended_cplb: float
    total_weight_lbs: float
    load_count: int
    avg_lbs_per_load: float


class FreightDriverSeries(BaseModel):
    """One yearly series (months 1–12) for the this-year-vs-last-year trend."""

    year: int
    data: list[FreightDriverMonth]


class CarrierBreakdownRow(BaseModel):
    """Per-carrier current-vs-prior comparison and its contribution to each effect."""

    carrier_id: str
    cur_share: float          # share of current-window weight (0–1)
    prior_share: float        # share of prior-window weight (0–1)
    share_delta: float
    cur_cplb: float | None    # carrier's current Method-A ¢/lb
    prior_cplb: float | None  # carrier's prior Method-A ¢/lb
    rate_delta: float | None
    cur_weight: float
    prior_weight: float
    mix_effect: float         # ¢/lb contribution from this carrier's mix shift
    rate_effect: float        # ¢/lb contribution from this carrier's rate change


class DestinationBreakdownRow(BaseModel):
    """Per-destination (ship-to state) current-vs-prior comparison and effects."""

    destination: str          # ship-to state code, e.g. "CA"
    cur_share: float
    prior_share: float
    share_delta: float
    cur_cplb: float | None
    prior_cplb: float | None
    rate_delta: float | None
    cur_weight: float
    prior_weight: float
    mix_effect: float         # ¢/lb contribution from shipping more/less to this destination
    rate_effect: float        # ¢/lb contribution from rate change within this destination


class DestinationDecomposition(BaseModel):
    """Destination-lens shift-share (a parallel attribution that also sums to total_delta)."""

    mix_effect: float         # shipping toward more/less expensive destinations
    rate_effect: float        # rate change within destinations
    explained: float
    residual: float
    available: bool = True     # False when ship-to data could not be loaded


class MarketContext(BaseModel):
    """LMI macro freight-price context used to interpret the rate effect."""

    available: bool
    lmi_transportation_prices: float | None = None
    direction: str | None = None   # "rising" | "falling" | "flat"
    month: str | None = None       # "YYYY-MM" of the latest LMI reading
    lmi_composite: float | None = None
    interpretation: str = ""       # plain-language market read


class OutlierBL(BaseModel):
    """A single high-cost load in the current window."""

    bl_number: str
    truck_appointment_date: str | None
    carrier_id: str | None
    unit_freight: float
    pick_weight: float


class FreightDriverDecomposition(BaseModel):
    """Year-over-year ¢/lb bridge: prior → +mix → +rate → residual → current."""

    prior_blended_cplb: float
    current_blended_cplb: float
    total_delta: float
    mix_effect: float
    rate_effect: float
    explained: float          # mix_effect + rate_effect
    residual: float           # total_delta - explained (interaction term)


class ShipmentSizeContext(BaseModel):
    """Avg lbs per BL, current vs prior — context for within-carrier rate moves."""

    cur_avg_lbs_per_bl: float
    prior_avg_lbs_per_bl: float
    avg_lbs_delta: float
    pct_change: float


class PrimaryDriverVerdict(BaseModel):
    """Rule-based conclusion about what is driving the ¢/lb change."""

    driver: str  # "carrier_mix" | "carrier_rate" | "mixed" | "insufficient_data"
    headline: str
    detail: str
    dominant_carrier_id: str | None = None


class FreightDriverMetadata(BaseModel):
    """Filter echo and source-shape transparency for the drill-down."""

    site: str
    product_group: str
    product_code: str
    current_period: str
    prior_period: str
    date_range: str
    total_rows: int
    rows_for_product: int
    method: str


class FreightDriverResponse(BaseModel):
    """Response model for the single-product freight driver decomposition."""

    series: list[FreightDriverSeries]
    decomposition: FreightDriverDecomposition
    carrier_table: list[CarrierBreakdownRow]
    destination_table: list[DestinationBreakdownRow]
    destination_decomposition: DestinationDecomposition
    market_context: MarketContext
    outliers: list[OutlierBL]
    shipment_size_context: ShipmentSizeContext
    verdict: PrimaryDriverVerdict
    metadata: FreightDriverMetadata


class RiserRow(BaseModel):
    """One product's YoY ¢/lb change for the risers ranking."""

    product_code: str
    cur_cplb: float
    prior_cplb: float | None
    delta_cplb: float | None
    pct_change: float | None
    cur_weight_lbs: float
    cur_load_count: int


class FreightRisersMetadata(BaseModel):
    """Metadata for the movers ranking response."""

    site: str
    product_group: str
    current_period: str
    prior_period: str
    products_considered: int
    direction: str = "increase"  # "increase" | "decrease"


class FreightRisersResponse(BaseModel):
    """Response model for the 'biggest ¢/lb increases' ranking."""

    risers: list[RiserRow]
    metadata: FreightRisersMetadata
