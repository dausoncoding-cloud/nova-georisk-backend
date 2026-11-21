"""Report subsection "Exposure by administrative unit" (FRRIS v1.1; docs/FRRIS_ADMIN_LEVEL_EXPOSURE_PLAN.md §5).

Inside the estimated-exposure section, after its tables. One table per level for the observed flood candidates and the
1-in-100-year zone: the top 15 units by people, an "Other units" row, "Outside any unit" when it is not zero, and the
total; a sum-check line and the boundary source, version and licence under each table. A level that is not available
says why (wards: "Ward boundaries not yet provided"). Estimates, never people affected.
"""
from __future__ import annotations

from typing import Any

from app.services.firris.admin_exposure_exports import TOP_UNITS, limitations, report_table, source_text, sum_check_text
from app.services.firris.admin_units import LEVELS, REPORT_EXTENTS

TITLE = "Exposure by administrative unit"
PLURAL = {"Region": "Regions", "District": "Districts", "Ward": "Wards"}
SHORT = {"observed_extent": "Observed flood candidates", "rp100": "1-in-100-year zone"}


def _int(value) -> str:
    return "—" if value is None else f"{round(value):,}"


def _share(value) -> str:
    if value is None:
        return "—"
    pct = value * 100
    return "100%" if pct >= 99.95 else ("< 0.1%" if 0 < pct < 0.1 else f"{pct:.1f}%")


def _buildings(cell: dict) -> str:
    if cell.get("buildings") is None:
        return "not counted"
    return f"{_int(cell['buildings'])} ({_int(cell.get('buildings_065'))})"


def admin_unit_subsection(writer, record: dict[str, Any] | None, *, number: int) -> None:
    by = (record or {}).get("by_admin_unit")
    if not by:
        return
    writer.heading(f"{number}.1 {TITLE}", 2)
    if by.get("status") != "assessed" and not any(lv.get("status") == "not_provided" for lv in by.get("levels") or []):
        writer.para(f"{TITLE}: not available. {by.get('reason') or ''}".strip())
        return
    writer.para("The estimated exposure above, broken down by administrative unit. Each unit is clipped to the analysis area; "
                "a unit only partly inside the area is never reported as if whole, and its share inside the area is given. "
                "Units add up to the area totals: buildings exactly, people within 0.5 person or 0.01% of the total, whichever "
                "is larger. A level whose units would not add up is withheld rather than rescaled. These are estimates, not "
                "people affected.")
    extents = {e["key"]: e["label"] for e in by.get("extents") or []}
    keys = [key for key in REPORT_EXTENTS if key in extents]
    caveat = ((record or {}).get("observed_extent_caveat") or {}).get("text")
    cluster_text = ((record or {}).get("observed_cluster") or {}).get("text")
    levels = {lv["level"]: lv for lv in by.get("levels") or []}
    for code in LEVELS:
        level = levels.get(code)
        if level is None:
            continue
        plural = PLURAL.get(level["level_name"], level["level_name"])
        if level.get("status") != "assessed":
            writer.para(f"{plural}: {level.get('reason')}" + ("" if str(level.get("reason") or "").endswith(".") else "."))
            continue
        table = report_table(level, keys)
        header = [level["level_name"], "Share inside the area"]
        for key in keys:
            header += [f"{SHORT[key]}: people", f"{SHORT[key]}: buildings ≥ 0.75 (≥ 0.65)"]
        rows = []
        for row in table["rows"]:
            name = row["name"] + (f" ({row['parent']})" if row.get("parent") and code != "L1" else "") + (" †" if row.get("cluster") else "")
            line = [name, _share(row.get("share"))]
            for key in keys:
                line += [_int(row[key]["people"]), _buildings(row[key])]
            rows.append(line)
        total = ["Total (the area totals)", ""]
        for key in keys:
            t = table["total"][key]
            total += [_int(t["people"]), _buildings(t) if t.get("buildings") is not None else "—"]
        rows.append(total)
        more = (f" The top {TOP_UNITS} of {table['units']} units by people in the observed flood candidates; the others are grouped "
                "as \"Other units\" (every unit is in the workbook and the GeoPackage)." if table["others"] else "")
        writer.table(header, rows, caption=f"Estimated exposure by {level['level_name'].lower()}: WorldPop R2025A people (area-weighted) and "
                                           f"Open Buildings v3 buildings (centroid inside).{more}")
        checks = [sum_check_text(level, key, SHORT[key]) for key in keys]
        notes = [text for text in checks if text]
        if any(row.get("cluster") for row in table["rows"]) and cluster_text:
            notes.append(f"† {cluster_text}")
        if level.get("buildings_note"):
            notes.append(level["buildings_note"])
        notes.append(source_text(level))
        writer.para(" ".join(notes))
    if caveat and "observed_extent" in keys:
        writer.para(f"Observed flood candidates, in every table: {caveat}")
    texts = limitations(record) + [next((lv.get("overlap_rule") for lv in levels.values() if lv.get("overlap_rule")), "")]
    writer.para("Limitations: " + " ".join(text for text in texts if text))
