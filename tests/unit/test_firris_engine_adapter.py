import json
import uuid
import zipfile

import geopandas as gpd
import numpy as np
import rasterio

from app.platform.engines.base import EngineExecutionContext
from app.platform.engines.firris import FIRRISEngineAdapter
from app.schemas.analyses import FIRRISProduct


def test_firris_contract_lists_every_required_product_and_delivery_shape():
    contract = FIRRISEngineAdapter().contract()
    assert contract["engine_key"] == "firris"
    assert {item["key"] for item in contract["products"]} == {
        product.value for product in FIRRISProduct
    }
    for product in contract["products"]:
        assert product["available_delivery_types"][0] == "metadata_json"
        if product["key"] in {"flood_extent", "flood_probability"}:
            assert product["available_delivery_types"][:4] == ["metadata_json", "geotiff", "cog", "preview"]
            assert product["planned_delivery_types"] == []
            assert all(item["status"] == "available" for item in product["representations"])
        else:
            assert product["available_delivery_types"] == ["metadata_json"]
            assert product["planned_delivery_types"] == ["geotiff", "cog", "preview"]
            assert all(item["status"] == "planned" for item in product["representations"][1:])
        assert product["representations"][0] == {
            "kind": "metadata",
            "format": "json",
            "status": "available",
            "media_type": "application/json",
            "renderable": False,
        }
    extent = next(item for item in contract["products"] if item["key"] == "flood_extent")
    assert "vector" in extent["available_delivery_types"]


def test_firris_adapter_executes_all_products_without_changing_formulas(tmp_path):
    products = [product.value for product in FIRRISProduct]
    parameters = {
        "flood_extent": {"backscatter_before": [4, 1], "backscatter_during": [1, 1]},
        "flood_depth": {"water_surface_elevation": [3, 1], "ground_elevation": [1, 2]},
        "flood_velocity": {"discharge": [2, 3], "cross_sectional_area": [1, 3]},
        "flood_hazard": {"depth": [0.5, 1], "velocity": [1, 2]},
        "flood_probability": {"annual_probability": [0.1, 0.5]},
        "flood_duration": {"duration_days": [1, 10]},
        "flood_exposure": {"normalized_density": [0.1, 0.9]},
        "flood_vulnerability": {"fvi": [0.2, 0.8]},
        "flood_risk": {"hazard": [0.5], "exposure": [0.4], "vulnerability": [0.3]},
        "flood_susceptibility": {"susceptibility": [0.25, 0.75]},
        "flood_hazard_zonation": {"zonation_score": [0.25, 0.75]},
    }
    progress = []
    result = FIRRISEngineAdapter().execute(
        EngineExecutionContext(
            task_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            aoi_id=uuid.uuid4(),
            output_directory=tmp_path,
            operation="flood_mapping",
            products=products,
            parameters=parameters,
            gis_metadata={
                "crs": "EPSG:4326",
                "datum": "WGS 84",
                "projection": "Geographic",
                "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1},
                "spatial_resolution": {"x": 10, "y": 10, "unit": "m"},
                "acquisition_date": "2026-09-28",
                "producer": "NOVA GeoRisk",
                "engine_version": "1.0",
            },
            result_version=3,
        ),
        progress.append,
    )
    assert set(products) <= set(result.output_files)
    assert {
        "analysis_summary",
        "result_metadata",
        "provenance",
        "report_package",
    } <= set(result.output_files)
    assert all((tmp_path / f"{product}.json").is_file() for product in products)
    assert (tmp_path / "firris-result-package.zip").is_file()
    for product in products:
        entry = result.output_files[product]
        assert entry["artifact_type"] == "metadata"
        assert entry["result_version"] == 3
        assert entry["file_size_bytes"] > 0
        assert len(entry["checksum_sha256"]) == 64
        assert entry["layer"]["renderable"] is False
    assert progress == sorted(progress)
    assert result.summary["status"] == "completed"


def test_firris_satellite_workflow_delivers_real_gis_and_reports(tmp_path):
    rows, cols = np.indices((20, 20))
    labels = ((rows > 8) & (cols < 12)).astype(int)
    valid_mask = np.ones((20, 20), dtype=bool)
    valid_mask[10, 1] = False
    result = FIRRISEngineAdapter().execute(
        EngineExecutionContext(
            task_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            aoi_id=uuid.uuid4(),
            output_directory=tmp_path,
            operation="flood_mapping",
            products=["flood_extent", "flood_probability"],
            parameters={
                "workflow": {
                    "source": {"provider": "prepared", "datasets": ["reviewed-fixture"]},
                    "feature_layers": {"row": rows.tolist(), "col": cols.tolist()},
                    "label_layer": labels.tolist(),
                    "valid_mask": valid_mask.tolist(),
                    "label_source": "reviewed test labels",
                    "sampling": {"sample_size": 200, "min_per_class": 20, "train_fraction": 0.7, "random_seed": 5},
                    "model": {"algorithm": "random_forest", "version": "test", "n_estimators": 30},
                }
            },
            gis_metadata={
                "crs": "EPSG:4326",
                "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1},
                "spatial_resolution": {"x": 0.05, "y": 0.05, "unit": "degree"},
                "producer": "NOVA GeoRisk",
            },
            result_version=1,
        ),
        lambda _: None,
    )
    assert result.output_files["flood_extent_cog"]["delivery_type"] == "cog"
    assert result.output_files["flood_extent_cog"]["layer"]["nodata"] == 255
    assert result.output_files["flood_extent_cog"]["gis_metadata"]["spatial_resolution"]["x"] == 0.05
    assert result.output_files["flood_extent_cog"]["gis_metadata"]["georeferencing_source"] == "delivered_raster_grid"
    assert result.output_files["flood_extent_cog"]["layer"]["legend"]["entries"][1]["label"].startswith("Classified flooded")
    assert "not AEP" in result.output_files["flood_probability_cog"]["layer"]["legend"]["title"]
    assert result.output_files["flood_extent_vector"]["artifact_type"] == "vector"
    assert result.output_files["flood_probability_preview"]["media_type"] == "image/png"
    assert result.output_files["firris_pdf_report"]["media_type"] == "application/pdf"
    assert result.output_files["firris_excel_report"]["format"] == "xlsx"
    assert result.output_files["samples_csv"]["format"] == "csv"
    assert result.output_files["samples_shapefile"]["delivery_type"] == "shapefile_zip"
    with zipfile.ZipFile(tmp_path / result.output_files["samples_shapefile"]["path"]) as archive:
        assert {"samples.shp", "samples.shx", "samples.dbf", "samples.prj"} <= set(archive.namelist())
        archive.extractall(tmp_path / "sample-shapefile-check")
    sample_shape = gpd.read_file(tmp_path / "sample-shapefile-check" / "samples.shp")
    assert len(sample_shape) == 200 and sample_shape.crs.to_epsg() == 4326
    assert set(sample_shape.columns) == {"row", "col", "label", "split", "geometry"}
    samples = json.loads((tmp_path / "samples.geojson").read_text(encoding="utf-8"))
    assert samples["type"] == "FeatureCollection"
    assert len(samples["features"]) == 200
    assert samples["features"][0]["geometry"]["type"] == "Point"
    assert result.summary["model"]["algorithm"] == "RandomForestClassifier"
    assert result.summary["quality"]["status"] == "passed"
    assert result.summary["products"]["flood_extent"]["area_statistics"]["flooded_area_m2"] > 0
    assert result.summary["products"]["flood_extent"]["area_statistics"]["valid_cells"] == 399
    with rasterio.open(tmp_path / "flood_extent.tif") as raster:
        assert raster.nodata == 255
        assert raster.read(1)[10, 1] == 255
    probability_metadata = json.loads((tmp_path / "flood_probability.json").read_text(encoding="utf-8"))
    assert "not annual exceedance probability" in probability_metadata["data"]["semantics"]
