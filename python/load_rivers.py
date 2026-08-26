"""
RockHound: Rivers Bronze Loader

Source: USGS National Hydrography Dataset (NHD), NHDFlowline feature class.
Downloaded from https://apps.nationalmap.gov/downloader/ with a Colorado
state filter applied -- delivered as three separate shapefile parts
(NHDFlowline_0/1/2) due to a size limit on the download, merged here.

Filtered to NAMED streams/rivers only (gnis_name populated), and to two
specific feature types:
  - FType 460 (StreamRiver): standard single-line stream/river segments
  - FType 558 (ArtificialPath): the centerline NHD uses to represent
    connectivity through a river/lake wide enough to be mapped as a
    polygon area rather than a simple line -- this is how NHD represents
    most of the length of major rivers (Colorado River, South Platte,
    Arkansas River, etc.) wherever they're wide enough to need it.
    An earlier version of this loader filtered to FType 460 only, which
    silently excluded most of the actual length of every major river in
    the state while still including hundreds of minor named creeks --
    caught by grouping loaded data by river_name and noticing major
    rivers had implausibly short total lengths compared to well-known
    minor creeks.

The unfiltered dataset is ~1.28 million records including unnamed minor
tributaries, canals, and ditches, which is far more detail than useful
for a "find claims near a named river" use case.
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

COLORADO_BBOX_WKT = "POLYGON((-109.06 36.99, -102.04 36.99, -102.04 41.00, -109.06 41.00, -109.06 36.99))"


def load_rivers():
    print("Reading NHDFlowline parts 0, 1, 2 ...")
    gdf0 = gpd.read_file("data/NHDFlowline_0.shp")
    gdf1 = gpd.read_file("data/NHDFlowline_1.shp")
    gdf2 = gpd.read_file("data/NHDFlowline_2.shp")
    gdf = pd.concat([gdf0, gdf1, gdf2], ignore_index=True)
    gdf = gpd.GeoDataFrame(gdf, geometry='geometry')
    gdf = gdf.to_crs(epsg=4326)
    print(f"  {len(gdf)} total combined rows")
    print(f"  Columns: {list(gdf.columns)}")

    # Filter to named streams/rivers only
    gdf = gdf[(gdf['gnis_name'].notna()) & (gdf['gnis_name'].str.strip() != '')]

    # Include both StreamRiver (460) and ArtificialPath (558) -- the latter
    # is required to capture most of the length of major rivers
    gdf = gdf[gdf['ftype'].isin([460, 558])]
    print(f"  {len(gdf)} rows after named-stream filter (ftype in [460, 558], gnis_name populated)")

    # Colorado bounding-box safety check, same pattern as every other source
    co_box = shapely_wkt.loads(COLORADO_BBOX_WKT)
    gdf = gdf[gdf.geometry.intersects(co_box)]
    print(f"  {len(gdf)} rows after Colorado bounding-box filter")

    conn = pyodbc.connect(CONN_STR)
    cursor = conn.cursor()
    cursor.fast_executemany = True

    rows_to_insert = [
        (
            str(row.get('permanent_', '')),
            str(row.get('gnis_name', '')).strip(),
            float(row.get('lengthkm', 0)) if pd.notna(row.get('lengthkm')) else None,
            str(row.get('reachcode', '')),
            str(row.get('ftype', '')),
            row.geometry.wkt,
            "https://apps.nationalmap.gov/downloader/",
            'Government Agency'
        )
        for _, row in gdf.iterrows()
    ]

    cursor.executemany("""
        INSERT INTO Bronze.Raw_Rivers
            (permanent_id, river_name, length_km, reachcode, ftype, geometry_wkt, source_url, source_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, rows_to_insert)
    conn.commit()
    conn.close()
    print(f"  Loaded {len(rows_to_insert)} rows into Bronze.Raw_Rivers")


if __name__ == "__main__":
    load_rivers()
