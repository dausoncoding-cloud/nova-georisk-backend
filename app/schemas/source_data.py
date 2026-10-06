"""Fail-closed source-data manifests. These attest metadata, not scientific truth."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator
from app.schemas.strict import StrictModel
from app.schemas.map_methods import SusceptibilityMethod, ZonationDefinition
from app.schemas.firris_evidence import ValidationDefinition, ImpactDefinition, DSSMetricDefinition, LiveFeedPolicy

from app.services.source_data.catalogue import get_profile


class TemporalCoverage(StrictModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def check_range(self):
        if not self.start.tzinfo or not self.end.tzinfo or self.end < self.start:
            raise ValueError("Temporal coverage requires timezone-aware ordered timestamps")
        return self


class SpatialResolution(StrictModel):
    x: float = Field(gt=0)
    y: float = Field(gt=0)
    unit: Literal["m", "degree"]


class GeographicCoverage(StrictModel):
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def check_bounds(self):
        if self.west >= self.east or self.south >= self.north:
            raise ValueError("Geographic coverage is not ordered")
        return self


class QualityAssessment(StrictModel):
    method: str = Field(min_length=3)
    assessed_at: datetime
    assessor: str = Field(min_length=2)
    status: Literal["passed"]

    @model_validator(mode="after")
    def check_timestamp(self):
        if not self.assessed_at.tzinfo:
            raise ValueError("QA timestamp must be timezone-aware")
        return self


class Licence(StrictModel):
    identifier: str = Field(min_length=2)
    permitted_use: str = Field(min_length=3)
    redistribution: Literal["allowed", "restricted"]


class Provenance(StrictModel):
    producer: str = Field(min_length=2)
    custodian: str = Field(min_length=2)
    source_uri: str = Field(min_length=3)
    acquisition_method: str = Field(min_length=3)


class Uncertainty(StrictModel):
    measure: str = Field(min_length=2)
    value: float = Field(ge=0)
    unit: str = Field(min_length=1)
    confidence_level: float | None = Field(default=None, gt=0, le=1)


class PredictorDefinition(StrictModel):
    role: Literal["predictor", "response"]
    family: Literal["climate", "hydrology", "remote_sensing", "terrain", "land_cover", "buffering"]
    unit: str = Field(min_length=1)
    definition: str = Field(min_length=10)
    evidence_ref: str = Field(min_length=3)


class SoilClassScore(StrictModel):
    label: str = Field(min_length=1)
    score: float


class SoilScoringPolicy(StrictModel):
    classes: dict[str, SoilClassScore] = Field(min_length=5, max_length=5)
    specification_reference: str = Field(min_length=3)
    score_definition: str = Field(min_length=10)
    score_units: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_codes(self):
        if any(not re.fullmatch(r"0|[1-9][0-9]{0,8}", key) for key in self.classes):
            raise ValueError("Soil class codes require canonical nonnegative integers")
        if len({item.label.casefold() for item in self.classes.values()}) != 5:
            raise ValueError("Soil class labels must be distinct")
        return self


class ProximityPolicy(StrictModel):
    normalization: Literal["aoi_minmax_entropy"]
    river_direction: Literal["benefit", "cost"]
    service_direction: Literal["benefit", "cost"]
    policy_reference: str = Field(min_length=3)


class RasterPredictorDefinition(StrictModel):
    name: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,63}$')
    catalogue_reference: str = Field(min_length=3,max_length=512)
    variable: PredictorDefinition

    @model_validator(mode="after")
    def predictor_only(self):
        if self.variable.role != "predictor":
            raise ValueError("Prediction raster must identify a sourced predictor, not a response")
        return self


class ZonationPolicyDefinition(ZonationDefinition):
    reference_periods: dict[str,TemporalCoverage] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reference_supports(self):
        if set(self.reference_periods) - {"aep"} or ("aep" in self.factor_units) != ("aep" in self.reference_periods):
            raise ValueError("AEP needs an explicit historical reference period; event factors use the analysis period")
        return self


class SourceDatasetManifest(StrictModel):
    project_id: uuid.UUID
    category: str
    source_id: str = Field(min_length=1, max_length=255)
    crs: str
    vertical_datum: str | None
    units: str
    temporal_coverage: TemporalCoverage
    geographic_coverage: GeographicCoverage
    spatial_resolution: SpatialResolution | None
    positional_uncertainty_m: float | None = Field(ge=0)
    spatial_unit_reference: str | None = None
    quality_assessment: QualityAssessment
    licence: Licence
    provenance: Provenance
    uncertainty: Uncertainty
    sha256: str
    nodata: float | None = None
    indicator_units: dict[str, str] | None = None
    indicator_directions: dict[str, Literal["benefit", "cost"]] | None = None
    indicator_scale_descriptions: dict[str, str] | None = None
    missing_value_policy: Literal["reject"] | None = None
    class_scheme: dict[str, str] | None = None
    land_cover_scheme: Literal["esa_worldcover", "modis_lc_type1"] | None = None
    observation_interval_hours: float | None = Field(default=None, gt=0)
    inventory_asset_types: list[str] | None = None
    hydraulic_model_run_id: str | None = None
    hydraulic_model_validation_reference: str | None = None
    observation_year: int | None = Field(default=None, ge=1900, le=2200)
    event_definition: str | None = None
    predictor_definitions: dict[str, PredictorDefinition] | None = None
    predictor_catalogue_reference: str | None = Field(default=None, min_length=3)
    soil_scoring_policy: SoilScoringPolicy | None = None
    proximity_scoring_policy: ProximityPolicy | None = None
    historical_record_definition: str | None = Field(default=None, min_length=10, max_length=512)
    validation_definition: ValidationDefinition | None = None
    impact_definition: ImpactDefinition | None = None
    dss_metric_definitions: dict[str, DSSMetricDefinition] | None = None
    live_feed_policy: LiveFeedPolicy | None = None
    susceptibility_method: SusceptibilityMethod | None = None
    raster_predictor: RasterPredictorDefinition | None = None
    zonation_policy: ZonationPolicyDefinition | None = None
    observation_definition: str | None = Field(default=None, min_length=10, max_length=512)

    @model_validator(mode="after")
    def check_category_contract(self):
        profile = get_profile(self.category)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.sha256):
            raise ValueError("sha256 must be a 64-digit hexadecimal checksum")
        if not re.fullmatch(r"EPSG:[1-9][0-9]*", self.crs):
            raise ValueError("crs must be an EPSG authority code")
        if profile["crs"] == "EPSG:4326" and self.crs != "EPSG:4326":
            raise ValueError("CSV/GeoJSON source CRS must be EPSG:4326")
        if profile["vertical_datum"] == "required" and not self.vertical_datum:
            raise ValueError("This category requires an explicit vertical datum")
        if profile["vertical_datum"] == "not_applicable" and self.vertical_datum is not None:
            raise ValueError("Vertical datum is not applicable to this category")
        if self.units != profile["unit"]:
            raise ValueError(f"units must be {profile['unit']}")
        if profile["format"] == "geotiff":
            if self.spatial_resolution is None or self.nodata is None:
                raise ValueError("Raster resolution and nodata are required")
            if self.positional_uncertainty_m is not None:
                raise ValueError("Raster positional uncertainty belongs in resolution/uncertainty metadata")
        elif self.spatial_resolution is not None or self.nodata is not None:
            raise ValueError("Raster resolution/nodata are not applicable to CSV/GeoJSON")
        if profile["format"] == "geojson" and self.positional_uncertainty_m is None:
            raise ValueError("GeoJSON positional uncertainty is required")
        if "longitude_latitude_columns" in profile["geometry"] and self.positional_uncertainty_m is None:
            raise ValueError("Station/survey point positional uncertainty is required")
        if "spatial_unit_id_join" in profile["geometry"] and not self.spatial_unit_reference:
            raise ValueError("Indicator survey requires a declared boundary source reference")
        if self.category == "land_cover" and not self.class_scheme:
            raise ValueError("Land-cover class scheme is required")
        if self.land_cover_scheme is not None and self.category != "land_cover":
            raise ValueError("Land-cover scoring scheme is only applicable to land cover")
        if self.observation_interval_hours is not None and self.category not in {"rainfall_stations", "river_discharge_stations"}:
            raise ValueError("Observation interval is only applicable to rainfall/discharge stations")
        if self.inventory_asset_types is not None and self.category not in {"buildings", "critical_infrastructure", "economic_assets"}:
            raise ValueError("Asset inventory types are only applicable to Exposure asset sources")
        if self.inventory_asset_types is not None and (not self.inventory_asset_types or any(not item.strip() for item in self.inventory_asset_types)):
            raise ValueError("Asset inventory types must be nonempty")
        if self.category == "hydraulic_model_velocity" and (
            not self.hydraulic_model_run_id or not self.hydraulic_model_validation_reference
        ):
            raise ValueError("Hydraulic-model velocity requires a reviewed model run and validation reference")
        if self.category != "hydraulic_model_velocity" and (
            self.hydraulic_model_run_id is not None or self.hydraulic_model_validation_reference is not None
        ):
            raise ValueError("Hydraulic-model metadata is only applicable to hydraulic-model velocity")
        if self.category == "annual_inundation_observation":
            if not self.observation_year or not self.event_definition or len(self.event_definition.strip()) < 10:
                raise ValueError("Annual exceedance observation requires a year and explicit event definition")
            start, end = self.temporal_coverage.start, self.temporal_coverage.end
            if (start.year != self.observation_year or end.year != self.observation_year
                    or start.utcoffset() != timedelta(0) or end.utcoffset() != timedelta(0)
                    or (start.month, start.day, start.hour, start.minute, start.second) != (1, 1, 0, 0, 0)
                    or (end.month, end.day, end.hour, end.minute, end.second) != (12, 31, 23, 59, 59)):
                raise ValueError("Annual observation must attest complete January–December coverage for its year")
        elif self.observation_year is not None or self.event_definition is not None:
            raise ValueError("Annual event metadata is only applicable to annual inundation observations")
        indicators = profile.get("required_indicators")
        if indicators and (not self.indicator_units or set(self.indicator_units) != set(indicators)
                       or any(not unit.strip() for unit in self.indicator_units.values())):
            raise ValueError("All required indicator units must be declared")
        if self.category == "vulnerability_indicators" and (
            not self.indicator_directions or set(self.indicator_directions) != set(indicators)
        ):
            raise ValueError("Every vulnerability indicator requires an explicit reviewed benefit/cost direction")
        if self.category == "vulnerability_indicators" and (
            self.missing_value_policy != "reject"
            or not self.indicator_scale_descriptions
            or set(self.indicator_scale_descriptions) != set(indicators)
            or any(not description.strip() for description in self.indicator_scale_descriptions.values())
        ):
            raise ValueError("Vulnerability indicators require reject-on-missing and a declared measurement scale for each indicator")
        if self.category == "community_capacity_indicators" and (
            self.missing_value_policy != "reject"
            or not self.indicator_directions
            or set(self.indicator_directions) != set(indicators)
            or any(direction != "benefit" for direction in self.indicator_directions.values())
            or not self.indicator_scale_descriptions
            or set(self.indicator_scale_descriptions) != set(indicators)
            or any(not description.strip() for description in self.indicator_scale_descriptions.values())
        ):
            raise ValueError("Community capacities require reviewed benefit orientations, measurement scales and reject-on-missing")
        if self.observation_definition is not None and self.category != "inundation_time_slice":
            raise ValueError("Observation definition is only applicable to inundation time slices")
        if self.category == "inundation_time_slice" and self.temporal_coverage.start != self.temporal_coverage.end:
            raise ValueError("Inundation time slice must have one exact observation timestamp")
        if self.category == "flood_predictor_observations":
            if not self.predictor_catalogue_reference:
                raise ValueError("Predictor observations require an explicit catalogue reference")
            if not self.predictor_definitions or not 2 <= len(self.predictor_definitions) <= 65 or sum(item.role == "response" for item in self.predictor_definitions.values()) != 1:
                raise ValueError("Predictor observations require declared variables with exactly one response")
            if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key) for key in self.predictor_definitions):
                raise ValueError("Predictor names must be unambiguous identifiers")
            if set(self.predictor_definitions) & {"sample_id", "observed_at", "longitude", "latitude", "Intercept"}:
                raise ValueError("Predictor names cannot collide with sample identity fields")
        elif self.predictor_definitions is not None or self.predictor_catalogue_reference is not None:
            raise ValueError("Predictor definitions only apply to predictor observations")
        if (self.category == "soil_texture_classes") != (self.soil_scoring_policy is not None):
            raise ValueError("Soil texture requires an explicit sourced five-class scoring policy")
        if self.proximity_scoring_policy is not None and self.category not in {"river_drainage_network", "critical_infrastructure"}:
            raise ValueError("Proximity policy only applies to sourced river/service geometries")
        if self.historical_record_definition is not None and self.category not in {"river_discharge_stations", "historical_flood_events"}:
            raise ValueError("Historical definitions only apply to discharge/event records")
        if self.susceptibility_method is not None and self.category != "flood_predictor_observations":
            raise ValueError("Susceptibility methods are bound to historical predictor observations")
        if (self.category == "flood_predictor_raster") != (self.raster_predictor is not None):
            raise ValueError("Predictor raster requires its exact sourced catalogue variable definition")
        if (self.category == "flood_zonation_policy") != (self.zonation_policy is not None):
            raise ValueError("Zonation decision table requires an explicit sourced method/factor/class definition")
        if self.category.startswith('validation_'):
            definition = self.validation_definition
            if definition is None:
                raise ValueError('Validation sources require explicit quantity, units, comparison and evaluation definitions')
            if self.category in {'validation_continuous_prediction', 'validation_binary_prediction', 'validation_probability'} and not definition.model_reference:
                raise ValueError('Predictions/scores require a sourced model reference')
            if self.category in {'validation_binary_observation', 'validation_binary_prediction', 'validation_probability'} and definition.class_labels is None:
                raise ValueError('Binary validation requires source-declared class labels')
            if self.category == 'validation_uncertainty' and definition.uncertainty_kind is None:
                raise ValueError('Uncertainty requires an explicit sourced measure')
            if self.category == 'validation_folds' and definition.fold_definitions is None:
                raise ValueError('Fold assignments require a sourced fold plan')
        elif self.validation_definition is not None:
            raise ValueError('Validation definition is category-bound')
        if (self.category == 'flood_impact_records') != (self.impact_definition is not None):
            raise ValueError('Impact records require a sourced impact basis, currency and evidence definition')
        if self.category == 'dss_records':
            if not self.dss_metric_definitions or len(self.dss_metric_definitions) > 100:
                raise ValueError('DSS records require sourced metric/domain/unit definitions')
        elif self.dss_metric_definitions is not None:
            raise ValueError('DSS metric definitions are category-bound')
        if (self.category == 'sensor_registry') != (self.live_feed_policy is not None):
            raise ValueError('Sensor registry requires an explicit live-feed policy')
        return self


class SourceDatasetValidation(StrictModel):
    category: str
    format: str
    record_count: int
    bounds: list[float] | None
    sha256: str
    structural_validation_only: Literal[True] = True
    analysis_ready: Literal[False] = False


class SourceDatasetRegistered(SourceDatasetValidation):
    dataset_id: uuid.UUID


class SourceReadinessReview(StrictModel):
    evidence_refs: list[str] = Field(min_length=1)
    qa_verified: Literal[True]
    licence_verified: Literal[True]
    provenance_verified: Literal[True]
    crs_datum_verified: Literal[True]
    temporal_coverage_verified: Literal[True]
    uncertainty_reviewed: Literal[True]
    hydrologic_coverage_verified: bool = False
    dem_conditioning_verified: bool = False
    coverage_complete_verified: bool = False
    hydraulic_model_verified: bool = False
    annual_record_complete_verified: bool = False
    predictor_catalogue_verified: bool = False
    scoring_policy_verified: bool = False
    validation_definition_verified: bool = False
    independent_observations_verified: bool = False
    impact_definition_verified: bool = False
    dss_definitions_verified: bool = False
    live_policy_verified: bool = False
    susceptibility_method_verified: bool = False
    zonation_method_verified: bool = False

    @model_validator(mode="after")
    def check_evidence(self):
        if any(not item.strip() for item in self.evidence_refs):
            raise ValueError("Readiness evidence references cannot be blank")
        return self


class SourceReadinessStatus(StrictModel):
    dataset_id: uuid.UUID
    analysis_ready: bool
    sha256: str
