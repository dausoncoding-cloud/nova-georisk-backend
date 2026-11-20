# FRRIS: watershed and hydrology status

**Date:** 20 November 2026. **For:** the client (NOVA ARI). **Status:** information only; nothing new has been built.

## In short

FRRIS maps flood candidates from radar and checks them against Sentinel-2. It also shows **modelled** river-flood hazard from an external global model (GloFAS). FRRIS itself does **not** model watersheds or water flow today. Some building blocks exist in the code, but they have **never been run on real data**, and there is no screen to use them.

## What exists (in the code)

- **Terrain tools:** slope, flow direction (D8), flow accumulation, Topographic Wetness Index (TWI) and drainage density, with automated tests.
- **Watershed delineation:** given a reviewed elevation model (DEM) and a reviewed list of outlet points, FRRIS can trace the area draining to each outlet (up to 100 outlets).
- **Both depend on external datasets:** they need DEM and outlet data uploaded and approved in the External data area, and they can only be started by an administrator through a technical form. There is no step-by-step screen.

## What has never been run

None of the above has run on production or on real client data. They have only been tested on small synthetic test data. The flow tools are also slow on large areas in their current form.

## What does not exist

- **HAND** (Height Above Nearest Drainage).
- **Ready-made catchment boundaries** from global datasets (HydroSHEDS / HydroBASINS, MERIT Hydro).
- **Automatic river (stream) network extraction.**
- **Hydrological modelling:** no rainfall–runoff model (turning rainfall into river flow) and no hydraulic model (turning river flow into flood depth and extent). The flood depths shown in FRRIS come from the external GloFAS model, not from our own modelling.

## What a minimal demonstration would take

A **"Hydrology context"** option for an analysis area, built from global datasets that are already available in Google Earth Engine. Checked for the Rufiji area on 20 November: all of them are available there.

| Layer | Source | What the client sees |
|---|---|---|
| Catchments around the area | HydroSHEDS / HydroBASINS (levels 8–12) | Catchment outlines with their own area and their total upstream area (e.g. Rufiji main stem ≈ 174,000 km²) |
| River network | MERIT Hydro upstream-drainage area, above a stated threshold | The drainage lines through the area |
| HAND | MERIT Hydro (90 m) | The height of each place above its nearest drainage line: low values are more flood-prone |

These layers would appear in the map viewer, as GIS layers to download (GeoPackage, GeoTIFF), and as a short report section, with sources, resolution and limits stated.

**Effort: about 6 working days (7–8 with contingency).**
- These are **context layers** from global datasets at about 90 m. They are **not** a calibrated hydrological model of the Rufiji.
- The licence terms of MERIT Hydro and HydroSHEDS must be confirmed before any use in client deliverables.

## Hydrological modelling (separate project)

A real rainfall–runoff or hydraulic model of a river basin needs inputs FRRIS does not have:
- river-flow (gauge) records for calibration;
- channel cross-sections and survey data;
- flood-defence information.

It is a project of its own: indicatively **8–16 weeks**, depending on the basin and the available data. It should be scoped and priced separately once the data situation is known.
