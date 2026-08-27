"""
RockHound: Trailheads Bronze Loader

Source: OpenStreetMap, tag highway=trailhead, queried via the Overpass API
for the entire Colorado bounding box, exported as GeoJSON via Overpass Turbo
(https://overpass-turbo.eu/) rather than scripted directly against the
Overpass API -- Overpass is community-run infrastructure with fair-use
expectations, and Overpass Turbo's export feature is the standard way to
pull a one-time bulk dataset like this rather than hitting the API
programmatically for a static extract.

Query used (for reference/reproducibility):
    [out:json][timeout:180];
    node["highway"="trailhead"](36.99,-109.06,41.00,-102.04);
    out body;

Field coverage note: name populated on 469/552 (85%), operator on 87/552
(16%), fee on 42/552 (8%). Elevation and vehicle-access tags exist on this
data but on fewer than 5% of records -- not reliable, not loaded here.
Phase 3's elevation and vehicle-access goals still need their own
dedicated data sources.
"""

import json
import pyodbc

CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    r"SERVER=localhost\SQLEXPRESS;DATABASE=RockHound;Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)


def load_trailheads():
    print("Reading trailheads GeoJSON export ...")
    with open("data/geoJSON.geojson", "r") as f:
        data = json.load(f)

    features = data.get("features", [])
    print(f"  {len(features)} trailhead features found")

    conn = pyodbc.connect(CONN_STR)
    cursor = conn.cursor()
    cursor.fast_executemany = True

    rows_to_insert = []
    for feature in features:
        props = feature.get("properties", {})
        coords = feature.get("geometry", {}).get("coordinates", [None, None])
        lon, lat = coords[0], coords[1]
        osm_id = props.get("@id", "")
        name = props.get("name", "")
        operator = props.get("operator", "")
        fee = props.get("fee", "")
        rows_to_insert.append((
            osm_id,
            name,
            operator,
            fee,
            lat,
            lon,
            "https://overpass-turbo.eu/",
            "Community/Crowdsourced"
        ))

    cursor.executemany("""
        INSERT INTO Bronze.Raw_Trailheads
            (osm_id, trail_name, operator, has_fee, latitude, longitude, source_url, source_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, rows_to_insert)
    conn.commit()
    conn.close()
    print(f"  Loaded {len(rows_to_insert)} rows into Bronze.Raw_Trailheads")


if __name__ == "__main__":
    load_trailheads()
