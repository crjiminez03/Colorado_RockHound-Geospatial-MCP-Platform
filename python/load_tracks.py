"""
RockHound: Tracks Bronze Loader

Source: OpenStreetMap, tag highway=track, queried via the Overpass API for
the entire Colorado bounding box, exported as GeoJSON via Overpass Turbo.

Query used (for reference/reproducibility):
    [out:json][timeout:180];
    way["highway"="track"](36.99,-109.06,41.00,-102.04);
    out body;
    out geom;

Field coverage note: of 73,703 real Colorado track segments (1 non-
LineString feature skipped), surface was populated on 21,158 (29%),
tracktype on 11,528 (16%), 4wd_only on 3,797 (5%), smoothness on 7,536
(10%). Most segments have no explicit difficulty rating -- downstream
logic (check_vehicle_access in rockhound_server.py) must report "no data"
honestly, not assume a road is safe or unsafe by default.

Data-quality note: many segments carry tiger:reviewed=no, meaning they
were auto-imported from Census TIGER data years ago and never manually
verified by a human OSM mapper. Not fixed here, just a known caveat.

Note: unlike the Shapefile-sourced loaders elsewhere in this project, this
one builds WKT directly from the raw GeoJSON coordinates rather than using
geopandas, since the source here is already a GeoJSON export from Overpass
Turbo, not a Shapefile -- geopandas isn't needed for this format, and
building the LINESTRING string directly also avoids any risk of the
"LINESTRING Z" elevation-tag issue encountered with the NHD rivers source,
since Overpass exports don't include an elevation dimension.
"""

import json
import pyodbc

CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    r"SERVER=localhost\SQLEXPRESS;DATABASE=RockHound;Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)


def load_tracks():
    print("Reading tracks GeoJSON export ...")
    with open("data/tracks.geojson", "r") as f:
        data = json.load(f)

    features = data.get("features", [])
    print(f"  {len(features)} track features found")

    conn = pyodbc.connect(CONN_STR)
    cursor = conn.cursor()
    cursor.fast_executemany = True

    rows_to_insert = []
    skipped = 0
    for feature in features:
        geom = feature.get("geometry", {})
        geom_type = geom.get("type")
        coords = geom.get("coordinates")

        # Only LineString geometries are real track roads -- a stray
        # Polygon or other type occasionally shows up in Overpass exports
        # (e.g. a closed-loop "area" track) and isn't usable here
        if geom_type != "LineString" or not coords:
            skipped += 1
            continue

        wkt_coords = ", ".join(f"{lon} {lat}" for lon, lat in coords)
        wkt = f"LINESTRING ({wkt_coords})"

        props = feature.get("properties", {})
        osm_id = props.get("@id", "")
        name = props.get("name", "")
        surface = props.get("surface", "")
        tracktype = props.get("tracktype", "")
        fourwd_only = props.get("4wd_only", "")
        smoothness = props.get("smoothness", "")
        access = props.get("access", "")

        rows_to_insert.append((
            osm_id, name, surface, tracktype, fourwd_only, smoothness, access,
            wkt,
            "https://overpass-turbo.eu/",
            "Community/Crowdsourced"
        ))

    print(f"  Skipped {skipped} non-LineString features")

    cursor.executemany("""
        INSERT INTO Bronze.Raw_Tracks
            (osm_id, track_name, surface, tracktype, fourwd_only, smoothness, access,
             geometry_wkt, source_url, source_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows_to_insert)
    conn.commit()
    conn.close()
    print(f"  Loaded {len(rows_to_insert)} rows into Bronze.Raw_Tracks")


if __name__ == "__main__":
    load_tracks()
