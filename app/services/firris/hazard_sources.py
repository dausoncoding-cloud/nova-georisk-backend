"""Modelled flood hazard (GloFAS v2.1): dataset facts, citation and licence, in ONE place.

Every report section, workbook sheet, GIS layer, README and provenance record of the Depth & Exposure module
reads these constants, so a change (for example once the licence is confirmed) is made here only.
Sources and checks: docs/FRRIS_DEPTH_EXPOSURE_IMPLEMENTATION_PLAN.md §2a (Phase 0, 2026-11-17).
"""
from __future__ import annotations

GLOFAS_ASSET = "JRC/CEMS_GLOFAS/FloodHazard/v2_1"
GLOFAS_VERSION = "v2.1"
METHOD_VERSION = "frris-depth-exposure-1"
RETURN_PERIODS = (10, 20, 50, 75, 100, 200, 500)
MIN_DEPTH_M = 0.1  # the dataset minimum: a cell is wet at depth >= 0.1 m
# Our own depth bins (plan §2): the GloFAS depth-category codes are too coarse and are not shown.
DEPTH_BINS = ((0.1, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, None))
OCCURRENCE_YEARS = (1, 10, 25, 30, 50, 100)

# Dataset citation (JRC Data Catalogue, confirmed by the owner 2026-11-17). Never cite doi:10.1016/j.advwatres.2016.05.002
# as the dataset DOI: it is Dottori et al. (2016), the method paper of the EARLIER global maps (plan §2a.4).
GLOFAS_DOI = "10.2905/JRC.VD32YWG"
GLOFAS_PID = "http://data.europa.eu/89h/jrc-floods-floodmapgl_rp50y-tif"
GLOFAS_CITATION = ("Baugh, C.; Colonese, J.; D'Angelo, C.; Dottori, F.; Neal, J.; Prudhomme, C.; Salamon, P. (2024): "
                   "Global river flood hazard maps. European Commission, Joint Research Centre (JRC) [Dataset]. "
                   f"doi:{GLOFAS_DOI} (PID {GLOFAS_PID})")
GLOFAS_METHOD_REFERENCES = (
    "Alfieri, L. et al. (2014). Advances in pan-European flood hazard mapping. Hydrological Processes 28: 4067–4077. "
    "doi:10.1002/hyp.9947",
    "Dottori, F. et al. (2017). An operational procedure for rapid flood risk assessment in Europe. Natural Hazards and "
    "Earth System Sciences 17: 1111–1126. doi:10.5194/nhess-17-1111-2017",
)

# Licence: RESOLVED 2026-11-17 (plan §2a.5), from the JRC Data Catalogue: ODbL v1.0, access conditions "No limitations".
# * Produced Works (maps, graphs, the report) carry GLOFAS_PRODUCED_WORK_NOTICE.
# * Derivative databases (GloFAS-derived GIS layers and tables in the result package) carry GLOFAS_DATABASE_NOTICE,
#   and the README says they are available under ODbL v1.0; no restrictive terms are added to them.
GLOFAS_LICENCE_CONFIRMED = True
ODBL_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
GLOFAS_LICENCE = ("Open Data Commons Open Database License (ODbL) v1.0; access conditions: no limitations "
                  "(JRC Data Catalogue).")
GLOFAS_PRODUCED_WORK_NOTICE = "Contains data from GloFAS flood hazard maps (JRC/CEMS), ODbL v1.0"
GLOFAS_DATABASE_NOTICE = ("Derived from the GloFAS flood hazard maps v2.1 (JRC/CEMS). This derivative database is available "
                          f"under the Open Data Commons Open Database License (ODbL) v1.0 ({ODBL_URL}); no further "
                          "restrictions are added. Source: " + GLOFAS_CITATION + ".")
GLOFAS_ATTRIBUTION = GLOFAS_PRODUCED_WORK_NOTICE + ". " + GLOFAS_CITATION + "."
# Result-package files derived from GloFAS (derivative databases): listed under the ODbL note of the package README.
GLOFAS_DERIVED_KEYS = ("modelled_flood_depth_rp", "modelled_permanent_water", "modelled_flood_hazard", "exposed_population_rp",
                       "flood_exposure")

# How to read the maps (CEMS-Flood wiki; plan §2a.2). Shown in the report and the GIS README.
GLOFAS_METHOD_NOTE = (
    "Modelled river-flood inundation for return periods of 10 to 500 years (LISFLOOD hydrology, LISFLOOD-FP hydraulics). "
    "In each grid cell a Gumbel distribution was fitted to annual maximum river discharge, so a return period T refers "
    "to the river discharge (AEP = 1/T); the mapped depth is the simulated inundation for that discharge. "
    "Flood defences are not modelled (undefended), the bankfull (1.5-year) flow is removed, rivers below 500 km² "
    "upstream area and pluvial or coastal flooding are not included. Modelled context at ~90 m; not an observation "
    "and not a measure of this map's accuracy."
)
# The Earth Engine depth-category codes, recorded in provenance only (checked over Rufiji, plan §2a.1).
GLOFAS_CATEGORY_CODES = {"2": "0.1 to < 3 m", "3": "3 to < 10 m", "4": ">= 10 m", "1": "not present in Earth Engine v2.1"}
