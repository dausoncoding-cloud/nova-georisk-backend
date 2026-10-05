"""FIRRIS adapter for deterministic products and the satellite/ML workflow."""
from __future__ import annotations

import json
import tempfile
import zipfile
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import geopandas as gpd
from pyproj import CRS, Transformer
from rasterio.warp import transform_bounds
from shapely.geometry import Point

from app.platform.engines.base import EngineAdapter, EngineExecutionContext, EngineExecutionOutput
from app.platform.result_exports import artifact_entry, build_result_exports
from app.schemas.analyses import FIRRISProduct
from app.services.firris.workflow import FIRRISWorkflowOutput, run_satellite_workflow
from app.services.firris.area_statistics import raster_area_statistics
from app.services.maps import flood_products
from app.services.maps.export import export_flood_extent_geojson, write_cog, write_continuous_png, write_geotiff
from app.services.reporting.report_builder import (
    IndexSummary,
    ReportContext,
    export_csv,
    generate_excel_report,
    generate_pdf_report,
)


_LABELS = {
    "flood_extent": "Flood Extent",
    "flood_depth": "Flood Depth",
    "flood_velocity": "Flood Velocity",
    "flood_hazard": "Flood Hazard",
    "flood_probability": "Flood Probability",
    "flood_duration": "Flood Duration",
    "flood_exposure": "Flood Exposure",
    "flood_vulnerability": "Flood Vulnerability",
    "flood_risk": "Flood Risk",
    "flood_susceptibility": "Flood Susceptibility",
    "flood_hazard_zonation": "Flood Hazard Zonation",
}

_SATELLITE_LEGENDS = {
    "flood_extent": {
        "title": "SAR-derived flood classification",
        "entries": [{"label": "Not classified as flooded (0)", "color": "#228B22"}, {"label": "Classified flooded (1)", "color": "#00BFFF"}],
        "nodata_label": "No data / outside valid coverage",
    },
    "flood_probability": {
        "title": "Conditional Random Forest class score (not AEP)",
        "entries": [{"label": "0.00–0.20", "color": "#0B6E4F"}, {"label": "0.20–0.40", "color": "#F6D55C"}, {"label": "0.40–0.60", "color": "#ED553B"}, {"label": "0.60–1.00", "color": "#7A0019"}],
        "nodata_label": "No data / outside valid coverage",
    },
}


def _array(value: Any, name: str) -> np.ndarray:
    if value is None:
        raise ValueError(f"Missing FIRRIS parameter '{name}'.")
    array = np.asarray(value, dtype=float)
    if array.size == 0 or not np.all(np.isfinite(array)):
        raise ValueError(f"FIRRIS parameter '{name}' must contain finite numeric values.")
    return array


def _json_value(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(_json_value(value), indent=2, allow_nan=False), encoding="utf-8")


def _actual_raster_metadata(workflow: FIRRISWorkflowOutput, client_metadata: dict[str, Any]) -> dict[str, Any]:
    """Use the delivered raster grid, not client-declared bounds/resolution."""
    sample = next(iter(workflow.product_arrays.values()))
    height, width = sample.shape
    transform = workflow.raster_spec.transform
    corners = [transform @ (x, y) for x, y in [(0, 0), (width, 0), (0, height), (width, height)]]
    crs = CRS.from_epsg(workflow.raster_spec.crs_epsg)
    unit = crs.axis_info[0].unit_name if crs.axis_info else "unknown"
    return {
        **client_metadata,
        "crs": crs.to_string(),
        "datum": crs.datum.name if crs.datum else None,
        "projection": crs.coordinate_operation.name if crs.coordinate_operation else "Geographic",
        "bounding_box": {
            "west": min(x for x, _ in corners), "south": min(y for _, y in corners),
            "east": max(x for x, _ in corners), "north": max(y for _, y in corners),
        },
        "spatial_resolution": {
            "x": float(np.hypot(transform.a, transform.d)),
            "y": float(np.hypot(transform.b, transform.e)), "unit": unit,
        },
        "width": width,
        "height": height,
        "georeferencing_source": "delivered_raster_grid",
    }


def _layer_metadata(
    context: EngineExecutionContext,
    *,
    product: str,
    units: str,
    renderable: bool,
    available: list[str],
    legend: dict[str, Any] | None = None,
    nodata: float | int | None = None,
) -> dict[str, Any]:
    return {
        "layer_type": "raster",
        "crs": context.gis_metadata.get("crs"),
        "bounding_box": context.gis_metadata.get("bounding_box"),
        "spatial_resolution": context.gis_metadata.get("spatial_resolution"),
        "units": units,
        "nodata": nodata,
        "legend": legend,
        "renderable": renderable,
        "rendering_reason": None if renderable else "No map-renderable representation was delivered for this run.",
        "available_delivery_types": available,
        "planned_delivery_types": [],
        "product_key": product,
    }


class FIRRISEngineAdapter(EngineAdapter):
    key = "firris"
    name = "FIRRIS"
    version = "1.0"

    def contract(self) -> dict[str, Any]:
        satellite_products = {"flood_extent", "flood_probability"}
        return {
            "engine_key": self.key,
            "engine_name": self.name,
            "engine_version": self.version,
            "operations": ["flood_mapping"],
            "products": [
                {
                    "key": product.value,
                    "label": _LABELS[product.value],
                    "available_delivery_types": [
                        "metadata_json",
                        *(["geotiff", "cog", "preview"] if product.value in satellite_products else []),
                        *(["vector"] if product.value == "flood_extent" else []),
                    ],
                    "planned_delivery_types": [] if product.value in satellite_products else ["geotiff", "cog", "preview"],
                    "representations": [
                        {"kind": "metadata", "format": "json", "status": "available", "media_type": "application/json", "renderable": False},
                        {"kind": "raster", "format": "geotiff", "status": "available" if product.value in satellite_products else "planned", "media_type": "image/tiff", "renderable": False},
                        {"kind": "raster", "format": "cog", "status": "available" if product.value in satellite_products else "planned", "media_type": "image/tiff", "renderable": product.value in satellite_products},
                        {"kind": "preview", "format": "png", "status": "available" if product.value in satellite_products else "planned", "media_type": "image/png", "renderable": product.value in satellite_products},
                        *(
                            [{"kind": "vector", "format": "geojson", "status": "available", "media_type": "application/geo+json", "renderable": True}]
                            if product.value == "flood_extent" else []
                        ),
                    ],
                }
                for product in FIRRISProduct
            ],
        }

    def _compute(self, product: str, params: dict[str, Any]) -> dict[str, Any]:
        product_params = params.get(product, params)
        if product == "flood_extent":
            values = flood_products.compute_flood_extent(
                _array(product_params.get("backscatter_before"), "backscatter_before"),
                _array(product_params.get("backscatter_during"), "backscatter_during"),
                float(product_params.get("change_ratio_threshold", 1.5)),
            )
            return {"values": values.astype(bool), "units": "boolean"}
        if product == "flood_depth":
            values = flood_products.compute_flood_depth(
                _array(product_params.get("water_surface_elevation"), "water_surface_elevation"),
                _array(product_params.get("ground_elevation"), "ground_elevation"),
            )
            return {"values": values, "units": "m"}
        if product == "flood_velocity":
            values = flood_products.compute_flood_velocity(
                _array(product_params.get("discharge"), "discharge"),
                _array(product_params.get("cross_sectional_area"), "cross_sectional_area"),
            )
            return {"values": values, "units": "m/s"}
        if product == "flood_hazard":
            values = flood_products.compute_hazard_index(
                _array(product_params.get("depth"), "depth"),
                _array(product_params.get("velocity"), "velocity"),
            )
            return {"values": values, "classes": flood_products.classify_hazard_index(values), "units": "m2/s"}
        classifier_inputs = {
            "flood_probability": ("annual_probability", flood_products.classify_probability),
            "flood_duration": ("duration_days", flood_products.classify_duration),
            "flood_exposure": ("normalized_density", flood_products.classify_exposure_density),
            "flood_vulnerability": ("fvi", flood_products.classify_vulnerability_map),
            "flood_susceptibility": ("susceptibility", flood_products.classify_susceptibility),
            "flood_hazard_zonation": ("zonation_score", flood_products.classify_zonation),
        }
        if product in classifier_inputs:
            parameter, classifier = classifier_inputs[product]
            values = _array(product_params.get(parameter), parameter)
            classes = np.asarray([_json_value(classifier(float(value))) for value in values.reshape(-1)]).reshape(values.shape)
            result = {"values": values, "classes": classes, "units": "days" if product == "flood_duration" else "index"}
            if product == "flood_probability":
                result["semantics"] = "Caller-supplied annual probability; not derived or validated by FIRRIS."
            return result
        if product == "flood_risk":
            values = flood_products.compute_flood_risk(
                _array(product_params.get("hazard"), "hazard"),
                _array(product_params.get("exposure"), "exposure"),
                _array(product_params.get("vulnerability"), "vulnerability"),
            )
            classes = np.asarray([_json_value(flood_products.classify_risk_map(float(value))) for value in values.reshape(-1)]).reshape(values.shape)
            return {"values": values, "classes": classes, "units": "index"}
        raise ValueError(f"Unsupported FIRRIS product '{product}'.")

    def _gis_artifacts(self, context: EngineExecutionContext, product: str, computed: dict[str, Any], raster_spec, valid_mask: np.ndarray) -> dict[str, dict[str, Any]]:
        values = np.asarray(computed["values"])
        if values.ndim != 2:
            return {}
        if valid_mask.shape != values.shape:
            raise ValueError("FIRRIS output and valid-pixel mask shapes differ.")
        label = _LABELS[product]
        units = computed["units"]
        numeric = np.nan_to_num(values, nan=0).astype(np.uint8) if product == "flood_extent" else values.astype(np.float32)
        nodata = 255 if product == "flood_extent" else -9999.0
        product_metadata = {**context.gis_metadata, "product_key": product, "units": units,
                            "nodata": nodata, "result_version": context.result_version}
        if product == "flood_extent":
            if context.aoi_geometry is not None:
                from shapely.geometry import shape
                west, south, east, north = shape(context.aoi_geometry).bounds
                product_metadata["aoi_bounds_wgs84"] = {"west": west, "south": south,
                                                         "east": east, "north": north}
            product_metadata.update({"methodology": "SAR-derived screening pseudo-labels -> Random Forest flood classification",
                                     "independent_ground_truth": False,
                                     "validation_limitation": "Pseudo-label held-out accuracy is not independent authoritative flood accuracy"})
        export_values = np.where(valid_mask & np.isfinite(values.astype(float)), numeric, nodata).astype(numeric.dtype)
        tif_path = context.output_directory / f"{product}.tif"
        cog_path = context.output_directory / f"{product}.cog.tif"
        preview_path = context.output_directory / f"{product}.png"
        write_geotiff(str(tif_path), export_values, raster_spec, nodata=nodata)
        write_cog(str(cog_path), export_values, raster_spec, nodata=nodata)
        preview_palette = ["#228B22", "#00BFFF"] if product == "flood_extent" else ["#0B6E4F", "#F6D55C", "#ED553B", "#7A0019"]
        write_continuous_png(str(preview_path), export_values, palette=preview_palette, nodata=nodata)
        available = ["metadata_json", "geotiff", "cog", "preview"]
        if product == "flood_extent":
            available.append("vector")
        layer = _layer_metadata(context, product=product, units=units, renderable=True, available=available, legend=_SATELLITE_LEGENDS.get(product), nodata=nodata)
        entries = {
            f"{product}_geotiff": artifact_entry(tif_path, label=f"{label} GeoTIFF", media_type="image/tiff", artifact_type="raster", result_version=context.result_version, role="product", product_key=product, delivery_type="geotiff", format_name="geotiff", gis_metadata=product_metadata, layer=layer),
            f"{product}_cog": artifact_entry(cog_path, label=f"{label} COG", media_type="image/tiff", artifact_type="raster", result_version=context.result_version, role="product", product_key=product, delivery_type="cog", format_name="cog", gis_metadata=product_metadata, layer=layer),
            f"{product}_preview": artifact_entry(preview_path, label=f"{label} preview", media_type="image/png", artifact_type="preview", result_version=context.result_version, role="product", product_key=product, delivery_type="preview", format_name="png", gis_metadata=product_metadata, layer=layer),
        }
        if product == "flood_extent":
            vector_path = context.output_directory / "flood_extent.geojson"
            _write_json(vector_path, export_flood_extent_geojson((values == 1) & valid_mask, raster_spec))
            bounds = context.gis_metadata["bounding_box"]
            west, south, east, north = transform_bounds(context.gis_metadata["crs"], "EPSG:4326", bounds["west"], bounds["south"], bounds["east"], bounds["north"], densify_pts=21)
            vector_layer = {**layer, "layer_type": "vector", "crs": "EPSG:4326", "bounding_box": {"west": west, "south": south, "east": east, "north": north}, "spatial_resolution": None, "nodata": None}
            entries["flood_extent_vector"] = artifact_entry(vector_path, label="Flood Extent vector", media_type="application/geo+json", artifact_type="vector", result_version=context.result_version, role="product", product_key=product, delivery_type="vector", format_name="geojson", gis_metadata={**product_metadata, "crs": "EPSG:4326", "bounding_box": vector_layer["bounding_box"]}, layer=vector_layer)
        return entries

    def _workflow_reports(self, context: EngineExecutionContext, workflow: FIRRISWorkflowOutput, summaries: dict[str, Any]) -> dict[str, dict[str, Any]]:
        reports: dict[str, dict[str, Any]] = {}
        if workflow.enhancement_preview is not None:
            from PIL import Image
            preview_path = context.output_directory / "enhanced-display.png"
            Image.fromarray(workflow.enhancement_preview, "RGBA").save(preview_path)
            reports["enhanced_display"] = artifact_entry(preview_path, label="Optional enhanced display (not analysis input)",
                media_type="image/png", artifact_type="preview", result_version=context.result_version,
                role="export", delivery_type="preview", format_name="png")

        sample_path = context.output_directory / "samples.csv"
        export_csv(workflow.samples, str(sample_path))
        reports["samples_csv"] = artifact_entry(sample_path, label="Analysis samples", media_type="text/csv", artifact_type="report", result_version=context.result_version, role="export", delivery_type="csv", format_name="csv")
        sample_crs = f"EPSG:{workflow.raster_spec.crs_epsg}"
        transformer = Transformer.from_crs(sample_crs, "EPSG:4326", always_xy=True)
        sample_features = []
        for row in workflow.samples.itertuples(index=False):
            properties = row._asdict()
            lon, lat = transformer.transform(float(properties.pop("coordinate_x")), float(properties.pop("coordinate_y")))
            sample_features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {key: _json_value(value) for key, value in properties.items()},
            })
        sample_geojson_path = context.output_directory / "samples.geojson"
        _write_json(sample_geojson_path, {"type": "FeatureCollection", "features": sample_features})
        reports["samples_geojson"] = artifact_entry(sample_geojson_path, label="Georeferenced samples", media_type="application/geo+json", artifact_type="vector", result_version=context.result_version, role="export", delivery_type="geojson", format_name="geojson", gis_metadata={"crs": "EPSG:4326", "producer": "NOVA GeoRisk"})
        # Shapefile fields are intentionally short and stable; CSV/GeoJSON
        # retain the full feature inventory without DBF field-name truncation.
        sample_zip = context.output_directory / "samples-shapefile.zip"
        sample_rows = [
            {"row": int(feature["properties"]["pixel_row"]),
             "col": int(feature["properties"]["pixel_col"]),
             "label": int(feature["properties"]["observed_label"]),
             "split": str(feature["properties"]["sample_split"]),
             "geometry": Point(feature["geometry"]["coordinates"])}
            for feature in sample_features
        ]
        with tempfile.TemporaryDirectory(prefix="nova-samples-") as directory:
            shapefile = Path(directory) / "samples.shp"
            gpd.GeoDataFrame(sample_rows, geometry="geometry", crs="EPSG:4326").to_file(
                shapefile, driver="ESRI Shapefile", index=False,
            )
            with zipfile.ZipFile(sample_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(Path(directory).glob("samples.*")):
                    archive.write(path, arcname=path.name)
        reports["samples_shapefile"] = artifact_entry(
            sample_zip, label="Georeferenced analysis samples Shapefile",
            media_type="application/zip", artifact_type="vector", result_version=context.result_version,
            role="export", delivery_type="shapefile_zip", format_name="zip",
            gis_metadata={"crs": "EPSG:4326", "producer": "NOVA GeoRisk",
                          "fields": ["row", "col", "label", "split"],
                          "full_attributes_export": "samples.csv and samples.geojson"},
        )
        for key, filename, payload, label in [
            ("validation_metrics", "validation-metrics.json", workflow.validation_metrics, "Validation metrics"),
            ("model_metadata", "model-metadata.json", workflow.model_metadata, "Model metadata"),
            ("quality_assessment", "quality-assessment.json", workflow.quality, "Satellite data quality assessment"),
        ]:
            path = context.output_directory / filename
            _write_json(path, payload)
            reports[key] = artifact_entry(path, label=label, media_type="application/json", artifact_type="metadata", result_version=context.result_version, role="export", delivery_type="metadata_json", format_name="json")
        numeric_metrics = {key: value for key, value in workflow.validation_metrics.items() if isinstance(value, (int, float)) and np.isfinite(value)}
        report_context = ReportContext(
            project_name=str(context.project_id),
            aoi_name=str(context.aoi_id),
            index_summaries=[
                IndexSummary(name=_LABELS[key], mean=float(value["mean"]), min=float(value["min"]), max=float(value["max"]), classification="Model output")
                for key, value in summaries.items() if isinstance(value, dict) and {"mean", "min", "max"} <= set(value)
            ],
            classification_metrics=numeric_metrics,
            class_area_statistics=[
                {"product": _LABELS[key], **class_area}
                for key, value in summaries.items()
                for class_area in value.get("area_statistics", {}).get("class_areas", [])
            ],
            notes="Generated by the FIRRIS universal satellite image analysis workflow. See provenance and quality artifacts for source and validation limitations.",
        )
        pdf_path = context.output_directory / "firris-analysis-report.pdf"
        xlsx_path = context.output_directory / "firris-analysis-report.xlsx"
        generate_pdf_report(report_context, str(pdf_path))
        generate_excel_report(
            {
                "Product Summary": pd.DataFrame([{"product": key, **{field: item for field, item in value.items() if field != "area_statistics"}} for key, value in summaries.items()]),
                "Area Statistics": pd.DataFrame([{"product": key, **{field: item for field, item in value["area_statistics"].items() if field != "class_areas"}} for key, value in summaries.items() if "area_statistics" in value]),
                "Class Areas": pd.DataFrame([{"product": key, **class_area} for key, value in summaries.items() for class_area in value.get("area_statistics", {}).get("class_areas", [])]),
                "Validation Metrics": pd.DataFrame([{"metric": key, "value": json.dumps(value) if isinstance(value, dict) else value} for key, value in workflow.validation_metrics.items()]),
                "Samples": workflow.samples,
            }, str(xlsx_path),
        )
        reports["firris_pdf_report"] = artifact_entry(pdf_path, label="FIRRIS analysis report", media_type="application/pdf", artifact_type="report", result_version=context.result_version, role="export", delivery_type="pdf", format_name="pdf")
        reports["firris_excel_report"] = artifact_entry(xlsx_path, label="FIRRIS analysis workbook", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", artifact_type="report", result_version=context.result_version, role="export", delivery_type="excel", format_name="xlsx")
        for key, array in workflow.validation_arrays.items():
            path = context.output_directory / f"{key}.tif"
            write_geotiff(str(path), array.astype(np.uint8), workflow.raster_spec, nodata=0)
            reports[key] = artifact_entry(path, label=key.replace("_", " ").title(), media_type="image/tiff", artifact_type="raster", result_version=context.result_version, role="export", delivery_type="geotiff", format_name="geotiff", gis_metadata=context.gis_metadata)
        return reports

    def execute(self, context: EngineExecutionContext, progress_callback) -> EngineExecutionOutput:
        if context.operation != "flood_mapping":
            raise ValueError(f"Unsupported FIRRIS operation '{context.operation}'.")
        context.output_directory.mkdir(parents=True, exist_ok=True)
        params = context.parameters
        workflow_config = params.get("workflow")
        workflow = None
        if workflow_config:
            progress_callback(5)
            workflow = run_satellite_workflow(dict(workflow_config), context.gis_metadata, context.aoi_geometry, context.output_directory)
            source_config = dict(workflow_config.get("source") or {})
            actual = _actual_raster_metadata(workflow, context.gis_metadata)
            actual["target_period"] = source_config.get("target_period")
            actual["baseline_period"] = source_config.get("baseline_period")
            context = replace(context, gis_metadata=actual)
            progress_callback(55)
        outputs: dict[str, dict[str, Any]] = {}
        summaries: dict[str, Any] = {}
        for index, product in enumerate(context.products, start=1):
            if workflow is not None and product in workflow.product_arrays:
                source_values = workflow.product_arrays[product]
                computed = {"values": np.where(workflow.valid_mask, source_values, np.nan), "units": "dimensionless" if product == "flood_probability" else "binary class"}
                if product == "flood_probability":
                    computed["semantics"] = "Conditional Random Forest class score; not annual exceedance probability or return period."
            else:
                computed = self._compute(product, params)
            values = np.asarray(computed["values"])
            finite = values[np.isfinite(values.astype(float))]
            summaries[product] = {"cells": int(values.size), "units": computed["units"], "mean": float(np.mean(finite)), "min": float(np.min(finite)), "max": float(np.max(finite))}
            if workflow is not None and values.ndim == 2:
                summaries[product]["area_statistics"] = raster_area_statistics(workflow.product_arrays[product], workflow.raster_spec, nodata_mask=workflow.valid_mask)
            metadata_path = context.output_directory / f"{product}.json"
            _write_json(metadata_path, {"product_key": product, "product_name": _LABELS[product], "gis_metadata": context.gis_metadata, "data": {key: _json_value(value) for key, value in computed.items()}})
            gis_entries = self._gis_artifacts(context, product, computed, workflow.raster_spec, workflow.valid_mask) if workflow is not None else {}
            available = ["metadata_json", *[entry["delivery_type"] for entry in gis_entries.values()]]
            outputs[product] = artifact_entry(
                metadata_path, label=_LABELS[product], media_type="application/json", artifact_type="metadata",
                result_version=context.result_version, role="product", product_key=product,
                delivery_type="metadata_json", format_name="json", gis_metadata=context.gis_metadata,
                layer=_layer_metadata(context, product=product, units=computed["units"], renderable=bool(gis_entries), available=available, legend=_SATELLITE_LEGENDS.get(product) if gis_entries else None, nodata=(255 if product == "flood_extent" else -9999.0) if gis_entries else None),
            )
            outputs.update(gis_entries)
            progress_callback(min(92, 55 + int(index / len(context.products) * 37)) if workflow else min(92, 5 + int(index / len(context.products) * 87)))
        reports = self._workflow_reports(context, workflow, summaries) if workflow is not None else {}
        summary: dict[str, Any] = {"status": "completed", "products": summaries}
        if workflow is not None:
            summary.update({"quality": workflow.quality, "validation": workflow.validation_metrics, "model": workflow.model_metadata})
        provenance = {
            "producer": context.gis_metadata["producer"], "engine_key": self.key, "engine_version": self.version,
            "operation": context.operation, "artifact_schema_version": "1.0",
            **(workflow.provenance if workflow is not None else {"workflow": "direct product calculation"}),
        }
        outputs.update(reports)
        outputs.update(build_result_exports(
            context.output_directory, task_id=str(context.task_id), project_id=str(context.project_id),
            aoi_id=str(context.aoi_id), engine_key=self.key, engine_version=self.version,
            result_type="flood_mapping", result_version=context.result_version, summary=_json_value(summary),
            provenance=_json_value(provenance), gis_metadata=context.gis_metadata,
            product_entries={key: entry for key, entry in outputs.items() if entry.get("role") == "product"},
            supplemental_entries=reports,
        ))
        progress_callback(98)
        return EngineExecutionOutput(
            result_type="flood_mapping",
            summary=_json_value(summary),
            provenance=_json_value(provenance),
            output_files=outputs,
        )
