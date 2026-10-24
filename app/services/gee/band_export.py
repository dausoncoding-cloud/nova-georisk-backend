"""Request-bound GEE per-band delivery; filenames identify bands, never positions.

The original provider ZIP is retained. The validated manifest binds the image
expression, region, ordered request, received bytes and canonical TIFF. Hashes
provide audit/integrity evidence, not a provider signature or scientific truth.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import zipfile

import numpy as np
import rasterio

EXPORT_FORMAT = "ZIPPED_GEO_TIFF_PER_BAND"
VALIDITY_PREFIX = "valid__"
MAX_EXPORT_BYTES = 512 * 1024 * 1024


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def request_contract(image_expression: str, region_expression: str, bands: list[str],
                     *, scale: float, crs: str) -> dict:
    if (not bands or len(set(bands)) != len(bands)
            or any(not isinstance(band, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", band) for band in bands)):
        raise ValueError("GEE export requires unique exact band identities")
    if not isinstance(image_expression, str) or not image_expression or not isinstance(region_expression, str) or not region_expression:
        raise ValueError("GEE export requires serialized image and region identities")
    record = {"schema_version": 1, "format": EXPORT_FORMAT,
              "image_expression_sha256": hashlib.sha256(image_expression.encode()).hexdigest(),
              "region_expression_sha256": hashlib.sha256(region_expression.encode()).hexdigest(),
              "bands": list(bands), "validity_bands": [VALIDITY_PREFIX + band for band in bands],
              "mask_encoding": "source mask > 0; unmask(0, sameFootprint=False); binary validity",
              "scale_m": scale, "crs": crs}
    fingerprint = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {**record, "request_sha256": fingerprint, "filename_prefix": "firris_" + fingerprint}


def assemble_export(downloaded: Path, contract: dict) -> tuple[Path, Path, dict]:
    """Reject anonymous/missing/extra/duplicate members, mismatched grids or IDs.

    ZIP member order has no scientific meaning. Exact provider filenames are
    mapped to request band IDs, then written in the explicit request order.
    Optional embedded descriptions must agree; they cannot override filenames.
    """
    bands = contract["bands"]
    prefix = contract["filename_prefix"]
    validity_bands = contract["validity_bands"]
    delivered = bands + validity_bands
    expected = {f"{prefix}.{band}.tif": band for band in delivered}
    if not zipfile.is_zipfile(downloaded):
        raise ValueError("GEE export lacks required per-band identity metadata")
    extraction = downloaded.parent / "gee-extracted"
    extraction.mkdir(exist_ok=False)
    paths = {}
    with zipfile.ZipFile(downloaded) as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        if len(names) != len(delivered) or len(set(names)) != len(names) or set(names) != set(expected):
            raise ValueError("GEE export band identities/count differ from the exact request")
        if sum(member.file_size for member in members) > MAX_EXPORT_BYTES:
            raise ValueError("GEE expanded export exceeds protected capacity")
        for member in members:
            mode = member.external_attr >> 16
            if (member.flag_bits & 1 or member.is_dir() or (stat.S_IFMT(mode) not in (0, stat.S_IFREG))
                    or not 0 < member.file_size <= MAX_EXPORT_BYTES):
                raise ValueError("GEE export member is not a bounded regular raster")
            # Exact flat filenames have already excluded traversal and aliases.
            target = extraction / member.filename
            with archive.open(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            paths[expected[member.filename]] = target
    grid = None
    members_record = []
    for band in delivered:
        path = paths[band]
        with rasterio.open(path) as source:
            if source.driver != "GTiff" or source.count != 1:
                raise ValueError("GEE per-band export must contain exactly one raster band")
            if source.descriptions[0] not in (None, band):
                raise ValueError("GEE embedded band identity conflicts with its provider filename")
            if source.crs is None:
                raise ValueError("GEE per-band export lacks CRS metadata")
            current = (source.crs, source.transform, source.width, source.height)
            if grid is not None and current != grid:
                raise ValueError("GEE exported bands do not share one exact grid")
            grid = current
            dtype = np.dtype(source.dtypes[0])
            # Float64 preserves these source samples exactly. Do not silently
            # round wide integer rasters or accept nonnumeric provider payloads.
            if dtype.kind not in "fiu" or (dtype.kind in "iu" and dtype.itemsize > 4) or dtype.itemsize > 8:
                raise ValueError("GEE export dtype cannot be preserved losslessly")
            if source.width * source.height * len(bands) * 8 > MAX_EXPORT_BYTES:
                raise ValueError("GEE canonical raster exceeds protected capacity")
            members_record.append({"band": band, "member": path.name, "sha256": digest(path),
                                   "size_bytes": path.stat().st_size, "dtype": source.dtypes[0],
                                   "provider_description": source.descriptions[0]})
    # GEE can tag valid zero samples as nodata in per-band files. Never infer
    # validity from a fill value: the paired provider mask is explicit evidence.
    for band, validity_band in zip(bands, validity_bands, strict=True):
        with rasterio.open(paths[validity_band]) as validity:
            mask_values = validity.read(1)
            if not np.isin(mask_values, [0, 1]).all():
                raise ValueError("GEE exported validity evidence must be binary")
    output_path = downloaded.with_suffix(".tif")
    staged = output_path.with_suffix(".partial.tif")
    crs, transform, width, height = grid
    with rasterio.open(staged, "w", driver="GTiff", width=width, height=height,
                       count=len(bands), dtype="float64", crs=crs, transform=transform, nodata=np.nan) as output:
        for index, band in enumerate(bands, 1):
            with rasterio.open(paths[band]) as source, rasterio.open(paths[validity_bands[index-1]]) as validity:
                values = source.read(1).astype(np.float64)
                valid = validity.read(1) == 1
                output.write(np.where(valid, values, np.nan), index)
                output.set_band_description(index, band)
        output.update_tags(gee_export_request_sha256=contract["request_sha256"])
    # Read back the delivered representation, including masks and samples. No
    # identity or value is inferred from the physical order of archive members.
    with rasterio.open(staged) as output:
        if list(output.descriptions) != bands or output.count != len(bands):
            raise ValueError("Canonical GEE raster lacks exact band identities/order")
        for index, band in enumerate(bands, 1):
            with rasterio.open(paths[band]) as source, rasterio.open(paths[validity_bands[index-1]]) as validity:
                expected_values = np.where(validity.read(1) == 1, source.read(1).astype(np.float64), np.nan)
            if not np.array_equal(output.read(index), expected_values, equal_nan=True):
                raise ValueError("Canonical GEE raster differs from provider samples")
    staged.replace(output_path)
    manifest = {"request": contract, "identity_evidence": "exact request-bound provider per-band filenames",
                "provider_archive": {"filename": downloaded.name, "sha256": digest(downloaded),
                                     "size_bytes": downloaded.stat().st_size},
                "ordered_bands": [member for member in members_record if member["band"] in bands],
                "ordered_validity_bands": [member for member in members_record if member["band"] in validity_bands],
                "grid": {"crs": crs.to_string(), "transform": list(transform)[:6], "width": width, "height": height},
                "canonical_raster": {"filename": output_path.name, "sha256": digest(output_path)},
                "scope": "Received export-byte integrity; not a provider signature, original source-byte checksum or independent validation"}
    manifest_path = downloaded.with_suffix(".bands.json")
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return output_path, manifest_path, manifest
