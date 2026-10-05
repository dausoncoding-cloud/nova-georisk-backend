FROM python:3.11-slim

WORKDIR /app

# GDAL/GEOS/PROJ are required by geopandas/rasterio/pyproj/shapely
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libgeos-dev libproj-dev gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup --system nova \
    && adduser --system --ingroup nova --home /home/nova nova \
    && mkdir -p /app/outputs \
    && chown -R nova:nova /app /home/nova

COPY --chown=nova:nova . .

USER nova

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
