# Reviewed Python 3.11 base used by the verified release baseline. Updating this
# digest requires rebuilding and rerunning the image-packaging release gate.
FROM python:3.11-slim@sha256:6f31d6e9ba2b0a787a3f81c37b004155b87b9efa1b771182bd550c1615745be5 AS dependencies

WORKDIR /app

# GDAL/GEOS/PROJ are required by geopandas/rasterio/pyproj/shapely
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libgeos-dev libproj-dev gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Wheels supply GDAL/GEOS/PROJ. Only their external C++/OpenMP/XML runtime libraries
# are needed from the build environment; compilers, system GDAL and crypto-library
# self-test vectors must not become production image layers.
RUN mkdir /runtime-libs \
    && cp --parents /usr/lib/*-linux-gnu/libstdc++.so.6* \
       /usr/lib/*-linux-gnu/libgcc_s.so.1 \
       /usr/lib/*-linux-gnu/libgomp.so.1* \
       /usr/lib/*-linux-gnu/libexpat.so.1* /runtime-libs/

FROM python:3.11-slim@sha256:6f31d6e9ba2b0a787a3f81c37b004155b87b9efa1b771182bd550c1615745be5 AS runtime
WORKDIR /app
COPY --from=dependencies /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=dependencies /usr/local/bin/ /usr/local/bin/
COPY --from=dependencies /runtime-libs/ /
COPY requirements.txt ./

RUN ldconfig \
    && addgroup --system nova \
    && adduser --system --ingroup nova --home /home/nova nova \
    && mkdir -p /app/outputs \
    && chown -R nova:nova /app /home/nova

# Migrations and the source catalogue live under app; requirements.txt is also
# read at runtime by execution provenance. Never copy the repository wholesale.
COPY --chown=nova:nova app/ ./app/
COPY --chown=nova:nova alembic.ini ./
COPY --chown=nova:nova scripts/admin_entitlements.py scripts/admin_identity.py scripts/reconcile_legacy_projects.py scripts/validate_production_environment.py ./scripts/

USER nova

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Disposable integration/smoke tooling is isolated from the production image.
FROM runtime AS test
COPY --chown=nova:nova tests/ ./tests/
COPY --chown=nova:nova scripts/ ./scripts/

# Keep production last so ordinary docker/Compose builds cannot select tests.
FROM runtime AS production
