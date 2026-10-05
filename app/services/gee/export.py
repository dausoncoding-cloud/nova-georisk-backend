"""
GEE thumbnail export — renders a server-side ee.Image to a local PNG
via getThumbURL, generic for any AOI/output path (no project-specific
naming baked in here; callers decide where files go).
"""
from __future__ import annotations

import logging
from pathlib import Path

import ee
import requests

logger = logging.getLogger(__name__)

DEFAULT_THUMBNAIL_DIMENSIONS = 512
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 180


def render_thumbnail(
    image: ee.Image,
    aoi: ee.Geometry,
    output_path: Path,
    vis_params: dict | None = None,
    dimensions: int = DEFAULT_THUMBNAIL_DIMENSIONS,
    crs: str = "EPSG:4326",
) -> Path:
    """
    Ask Earth Engine to render `image` clipped to `aoi` as a PNG
    thumbnail, download it, and write it to `output_path`. Returns the
    path written.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Explicit CRS makes the otherwise ungeoreferenced PNG safe to position
    # using the manifest's WGS84 bounds.  Older atlas files rendered without
    # this parameter remain marked as legacy/unknown-CRS by the API.
    params = {"region": aoi, "dimensions": dimensions, "format": "png", "crs": crs}
    if vis_params:
        params.update(vis_params)

    url = image.getThumbURL(params)
    response = requests.get(url, timeout=DEFAULT_DOWNLOAD_TIMEOUT_SECONDS)
    response.raise_for_status()
    output_path.write_bytes(response.content)

    logger.info("Rendered thumbnail: %s", output_path)
    return output_path
