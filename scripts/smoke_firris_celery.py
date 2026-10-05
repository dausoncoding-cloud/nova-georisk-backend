"""Real API -> Redis -> Celery worker -> Result -> protected artifact smoke test."""
from __future__ import annotations

import argparse
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile


def request_json(base_url: str, secret: str, method: str, path: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={
            "X-Internal-Secret": secret,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned {exc.code}: {body}") from exc


def request_bytes(base_url: str, secret: str, path: str) -> tuple[int, bytes, str]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        method="GET",
        headers={"X-Internal-Secret": secret},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.status, response.read(), response.headers.get_content_type()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://api-smoke:8000")
    parser.add_argument("--secret", default="celery-smoke-secret-not-for-production")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    status, project = request_json(
        args.base_url,
        args.secret,
        "POST",
        "/api/v1/projects",
        {"name": "FIRRIS Celery smoke", "engine_key": "firris"},
    )
    assert status == 201 and project["engine_key"] == "firris"

    status, aoi = request_json(
        args.base_url,
        args.secret,
        "POST",
        "/api/v1/aoi",
        {
            "project_id": project["id"],
            "name": "Smoke AOI",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[36.0, -2.0], [37.0, -2.0], [37.0, -1.0], [36.0, -1.0], [36.0, -2.0]]
                ],
            },
        },
    )
    assert status == 201

    status, submitted = request_json(
        args.base_url,
        args.secret,
        "POST",
        "/api/v1/analyses",
        {
            "project_id": project["id"],
            "aoi_id": aoi["id"],
            "products": ["flood_depth", "flood_risk"],
            "parameters": {
                "flood_depth": {
                    "water_surface_elevation": [5.0, 3.0],
                    "ground_elevation": [3.5, 4.0],
                },
                "flood_risk": {
                    "hazard": [0.8, 0.2],
                    "exposure": [0.5, 0.5],
                    "vulnerability": [0.5, 0.5],
                },
            },
            "gis_metadata": {
                "crs": "EPSG:4326",
                "datum": "WGS 84",
                "projection": "Geographic",
                "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1},
                "spatial_resolution": {"x": 10, "y": 10, "unit": "m"},
                "acquisition_date": "2026-09-28",
                "producer": "Smoke client value must be replaced",
            },
        },
    )
    assert status == 202 and submitted["task"]["status"] == "queued"
    task_id = submitted["task"]["id"]

    deadline = time.monotonic() + args.timeout
    task = None
    while time.monotonic() < deadline:
        _, task = request_json(args.base_url, args.secret, "GET", f"/api/v1/tasks/{task_id}")
        if task["status"] in {"completed", "failed", "canceled"}:
            break
        time.sleep(0.5)
    if task is None or task["status"] != "completed":
        raise RuntimeError(f"FIRRIS Celery task did not complete: {task}")

    query = urllib.parse.urlencode({"task_id": task_id})
    _, result_page = request_json(args.base_url, args.secret, "GET", f"/api/v1/results?{query}")
    assert result_page["total"] == 1
    result = result_page["items"][0]
    assert result["engine_key"] == "firris"
    assert result["provenance"]["engine_version"] == "1.0"
    assert "path" not in json.dumps(result)
    product = next(item for item in result["products"] if item["key"] == "flood_depth")
    assert product["artifact_type"] == "metadata"
    assert product["file_size_bytes"] > 0
    assert len(product["checksum_sha256"]) == 64
    assert len(result["layers"]) == 2
    assert all(layer["renderable"] is False for layer in result["layers"])
    _, artifact = request_json(args.base_url, args.secret, "GET", product["url"])
    assert artifact["product_key"] == "flood_depth"
    assert artifact["gis_metadata"]["producer"] == "NOVA GeoRisk"
    assert artifact["gis_metadata"]["engine_version"] == "1.0"
    package = next(item for item in result["exports"] if item["key"] == "report_package")
    status, package_bytes, media_type = request_bytes(
        args.base_url, args.secret, package["url"]
    )
    assert status == 200 and media_type == "application/zip"
    with zipfile.ZipFile(io.BytesIO(package_bytes)) as archive:
        assert {
            "analysis-summary.json",
            "result-metadata.json",
            "provenance.json",
            "products/flood_depth.json",
            "products/flood_risk.json",
        } <= set(archive.namelist())

    print(
        json.dumps(
            {
                "status": "passed",
                "task_id": task_id,
                "result_id": result["id"],
                "artifact": product["key"],
                "export": package["key"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
