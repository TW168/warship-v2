"""Pydantic models for shipment-size workload decomposition analytics."""

from pydantic import BaseModel


class ShipmentSizeImpactMonth(BaseModel):
    """Monthly shipment-size workload metrics for one site/product group."""

    year: int
    month: int
    total_weight_lbs: float
    load_count: int
    avg_lbs_per_load: float
    loads_per_million_lbs: float

    prior_year_weight_lbs: float | None = None
    prior_year_load_count: int | None = None
    prior_year_avg_lbs_per_load: float | None = None

    weight_delta_lbs: float | None = None
    load_delta: int | None = None
    avg_lbs_per_load_delta: float | None = None

    load_effect_lbs: float | None = None
    shipment_size_effect_lbs: float | None = None
    explained_delta_lbs: float | None = None
    unexplained_delta_lbs: float | None = None

    extra_loads_due_to_smaller_shipments: float | None = None


class ShipmentSizeImpactSeries(BaseModel):
    """One yearly series for line chart rendering."""

    year: int
    site: str
    product_group: str
    data: list[ShipmentSizeImpactMonth]


class ShipmentSizeImpactLatestSummary(BaseModel):
    """Latest comparable month summary to support executive KPI cards."""

    year: int | None = None
    month: int | None = None
    total_weight_lbs: float | None = None
    load_count: int | None = None
    avg_lbs_per_load: float | None = None
    prior_year_avg_lbs_per_load: float | None = None
    extra_loads_due_to_smaller_shipments: float | None = None
    load_effect_lbs: float | None = None
    shipment_size_effect_lbs: float | None = None


class ShipmentSizeImpactMetadata(BaseModel):
    """Metadata for filters and source shape transparency."""

    site: str
    product_group: str
    date_range: str
    exclude_carriers: bool
    excluded_carriers: list[str]
    total_records_original: int
    total_records_after_filter: int
    total_records_final: int
    metric_formula: str


class ShipmentSizeImpactResponse(BaseModel):
    """Response model for shipment-size workload decomposition endpoint."""

    series: list[ShipmentSizeImpactSeries]
    monthly_table: list[ShipmentSizeImpactMonth]
    latest_summary: ShipmentSizeImpactLatestSummary
    metadata: ShipmentSizeImpactMetadata
