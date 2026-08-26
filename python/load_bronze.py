"""
RockHound: Bronze Layer Ingestion

Loads BLM mining claims, BLM land ownership, and USGS mineral occurrence
data into SQL Server Bronze tables.

Key design decisions:
- Colorado bounding-box filter applied BEFORE insert -- several source files
  are nationwide despite being drawn from a Colorado-focused search
  (e.g. active claims: 579,730 national rows -> 14,699 after filtering).
- fast_executemany used for bulk insert performance instead of row-by-row
  cursor.execute() calls.
- Column names below reflect the REAL field names confirmed from actual
  downloaded BLM/USGS files (CSE_NAME, adm_manage, commodity_type, etc.),
  not generic assumptions -- these differ meaningfully between sources.
"""

import geopandas as gpd
import pandas as pd
import pyodbc
from shapely import wkt as shapely_wkt

CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    r"SERVER=localhost\SQLEXPRESS;DATABASE=RockHound;Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)

# Rough bounding box for Colorado -- used to filter nationwide source files
# down to just the relevant state before loading.
COLORADO_BBOX_WKT = "POLYGON((-109.06 36.99, -102.04 36.99, -102.04 41.00, -109.06 41.00, -109.06 36.99))"


def load_claims(filepath, status_label, source_url, layer=None):
    """Load a BLM mining claims file (GeoJSON or File Geodatabase) into Bronze.Raw_Claims."""
    print(f"Reading {filepath} ...")
    gdf = gpd.read_file(filepath, layer=layer) if layer else gpd.read_file(filepath)
    gdf = gdf.to_crs(epsg=4326)
    print(f"  {len(gdf)} total rows before Colorado filter")
    print(f"  Columns: {list(gdf.columns)}")

    co_box = shapely_wkt.loads(COLORADO_BBOX_WKT)
    gdf = gdf[gdf.geometry.intersects(co_box)]
    print(f"  {len(gdf)} rows after Colorado filter")

    conn = pyodbc.connect(CONN_STR)
    cursor = conn.cursor()
    cursor.fast_executemany = True

    rows_to_insert = [
        (
            str(row.get('ID', '')),
            str(row.get('CSE_NAME', '')),
            status_label,
            str(row.get('CSE_TYPE_NR', '')),
            '',  # county: not present in source data
            str(row.get('date_closed', '')),
            row.geometry.wkt,
            source_url,
            'Government Agency'
        )
        for _, row in gdf.iterrows()
    ]

    cursor.executemany("""
        INSERT INTO Bronze.Raw_Claims
            (claim_id, claim_name, claim_status, claim_type, county, date_closed, geometry_wkt, source_url, source_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows_to_insert)
    conn.commit()
    conn.close()
    print(f"  Loaded {len(rows_to_insert)} rows from {filepath}")


def load_land_ownership(filepath, source_url):
    """Load BLM Colorado Surface Management Agency (land ownership) into Bronze.Raw_Land_Ownership."""
    print(f"Reading {filepath} ...")
    gdf = gpd.read_file(filepath)
    gdf = gdf.to_crs(epsg=4326)
    print(f"  Columns: {list(gdf.columns)}")

    conn = pyodbc.connect(CONN_STR)
    cursor = conn.cursor()
    cursor.fast_executemany = True

    rows_to_insert = [
        (
            str(row.get('SMA_ID', '')),
            str(row.get('adm_manage', '')),   # short agency code: BLM, USFS, PRI, BIA, USFW, etc.
            str(row.get('adm_name', '')),
            row.geometry.wkt,
            source_url,
            'Government Agency'
        )
        for _, row in gdf.iterrows()
    ]

    cursor.executemany("""
        INSERT INTO Bronze.Raw_Land_Ownership
            (parcel_id, land_type, parcel_name, geometry_wkt, source_url, source_type)
        VALUES (?, ?, ?, ?, ?, ?)
    """, rows_to_insert)
    conn.commit()
    conn.close()
    print(f"  Loaded {len(rows_to_insert)} rows from {filepath}")


def load_mrds(filepath, source_url):
    """Load USGS Mineral Resources Data System (MRDS) into Bronze.Raw_Mineral_Occurrences.

    NOTE: MRDS 'flattened' export is nationwide despite being drawn from a
    Colorado-area map view -- explicit state filter is required (confirmed:
    304,632 national rows -> 17,669 Colorado rows).
    """
    print(f"Reading {filepath} ...")
    df = pd.read_csv(filepath, low_memory=False)
    print(f"  {len(df)} total rows before Colorado filter")
    df = df[df['state'] == 'Colorado']
    print(f"  {len(df)} rows after Colorado filter")
    print(f"  Columns: {list(df.columns)}")

    def safe_float(val):
        """Guard against NaN/invalid coordinate values -- SQL Server DECIMAL
        columns reject NaN outright, so return None (NULL) instead."""
        try:
            if pd.isna(val):
                return None
            return float(val)
        except (TypeError, ValueError):
            return None

    conn = pyodbc.connect(CONN_STR)
    cursor = conn.cursor()
    cursor.fast_executemany = True

    rows_to_insert = [
        (
            str(row.get('dep_id', '')),
            str(row.get('site_name', ''))[:200],
            safe_float(row.get('latitude')),
            safe_float(row.get('longitude')),
            str(row.get('commod1', ''))[:990],  # actual mineral/commodity -- see README data-mapping note
            source_url,
            'Government Agency'
        )
        for _, row in df.iterrows()
    ]

    cursor.executemany("""
        INSERT INTO Bronze.Raw_Mineral_Occurrences
            (site_id, mineral_name_raw, latitude, longitude, commodity_type, source_url, source_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, rows_to_insert)
    conn.commit()
    conn.close()
    print(f"  Loaded {len(rows_to_insert)} rows from {filepath}")


def load_counties(filepath, source_url):
    """Load US Census TIGER/Line county boundaries, filtered to Colorado (STATEFP = '08')."""
    print(f"Reading {filepath} ...")
    gdf = gpd.read_file(filepath)
    gdf = gdf.to_crs(epsg=4326)
    print(f"  {len(gdf)} total rows before Colorado filter")
    print(f"  Columns: {list(gdf.columns)}")

    gdf = gdf[gdf['STATEFP'] == '08']  # Colorado FIPS code
    print(f"  {len(gdf)} rows after Colorado filter")

    conn = pyodbc.connect(CONN_STR)
    cursor = conn.cursor()
    cursor.fast_executemany = True

    rows_to_insert = [
        (
            str(row.get('GEOID', '')),
            str(row.get('NAME', '')),
            str(row.get('STATEFP', '')),
            row.geometry.wkt,
            source_url,
            'Government Agency'
        )
        for _, row in gdf.iterrows()
    ]

    cursor.executemany("""
        INSERT INTO Bronze.Raw_Counties
            (county_fips, county_name, state_fips, geometry_wkt, source_url, source_type)
        VALUES (?, ?, ?, ?, ?, ?)
    """, rows_to_insert)
    conn.commit()
    conn.close()
    print(f"  Loaded {len(rows_to_insert)} rows from {filepath}")


def load_places(filepath, source_url):
    """Load US Census TIGER/Line places (cities/towns/CDPs) -- Colorado-specific file, no filter needed."""
    print(f"Reading {filepath} ...")
    gdf = gpd.read_file(filepath)
    gdf = gdf.to_crs(epsg=4326)
    print(f"  {len(gdf)} rows")
    print(f"  Columns: {list(gdf.columns)}")

    conn = pyodbc.connect(CONN_STR)
    cursor = conn.cursor()
    cursor.fast_executemany = True

    rows_to_insert = [
        (
            str(row.get('GEOID', '')),
            str(row.get('NAME', '')),
            str(row.get('LSAD', '')),  # legal/statistical area description -- distinguishes incorporated place vs CDP
            row.geometry.wkt,
            source_url,
            'Government Agency'
        )
        for _, row in gdf.iterrows()
    ]

    cursor.executemany("""
        INSERT INTO Bronze.Raw_Places
            (place_fips, place_name, place_type, geometry_wkt, source_url, source_type)
        VALUES (?, ?, ?, ?, ?, ?)
    """, rows_to_insert)
    conn.commit()
    conn.close()
    print(f"  Loaded {len(rows_to_insert)} rows from {filepath}")


if __name__ == "__main__":
    load_claims("data/BLM_Natl_MLRS_Mining_Claims_-_Not_Closed.geojson", "Active",
                "BLM Natl MLRS Mining Claims - Not Closed")
    load_claims("data/BLM_Natl_MLRS_Mining_Claims-Closed_(Past_Year).geojson", "Closed",
                "BLM Natl MLRS Mining Claims - Closed (Past Year)")
    load_claims("data/Mining_Claims_Closed.gdb", "Closed",
                "BLM Mining Claims Closed", layer="BLM_MLRS_MC_Closed")
    load_land_ownership("data/BLM_Colorado_Surface_Management_Agency.geojson",
                "BLM Colorado Surface Management Agency")
    load_mrds("data/usgs_mrds_colorado.csv",
                "https://mrdata.usgs.gov/mrds/")
    load_counties("data/tl_counties_us.shp",
                "https://catalog.data.gov/dataset/tiger-line-shapefile-current-nation-u-s-county-and-equivalent-entities")
    load_places("data/tl_places_colorado.shp",
                "https://catalog.data.gov/dataset/tiger-line-shapefile-current-state-colorado-place")
    print("Bronze load complete.")
