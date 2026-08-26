"""
RockHound: Hot Springs Bronze Loader

Source: Colorado Geological Survey CO_Geothermal_Map_v3_MapPackage,
Layer 3 (Hot Spring Use Type). Queried directly via ArcGIS REST API --
no file download needed, and coordinates come back pre-projected to
WGS84 (lat/long), unlike the underlying stored data (which is in
NAD83 UTM Zone 13N / EPSG:26913).

Finding this service was itself part of the real story: the public-facing
web map (an Esri Web AppBuilder app) doesn't expose its data source
directly -- the underlying ArcGIS REST MapServer endpoint had to be
tracked down by browsing the Colorado Geological Survey's REST services
directory (cgsarcimage.mines.edu/arcgis/rest/services) and confirming the
correct layer via its field list before writing any load code.
"""

import requests
import pyodbc

CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    r"SERVER=localhost\SQLEXPRESS;DATABASE=RockHound;Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)

HOT_SPRINGS_QUERY_URL = (
    "https://cgsarcimage.mines.edu/arcgis/rest/services/cgs_services/"
    "CO_Geothermal_Map_v3_MapPackage/MapServer/3/query"
    "?where=1%3D1&outFields=*&f=geojson"
)


def clean_numeric(raw_value):
    """Convert a raw field to a float, treating '-', blank, or whitespace-only
    strings as missing (None) rather than crashing or silently becoming 0."""
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if text in ("", "-", "N/A"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_hot_springs():
    print(f"Querying {HOT_SPRINGS_QUERY_URL} ...")
    response = requests.get(HOT_SPRINGS_QUERY_URL)
    response.raise_for_status()
    data = response.json()
    features = data.get("features", [])
    print(f"  {len(features)} hot spring records returned")

    conn = pyodbc.connect(CONN_STR)
    cursor = conn.cursor()
    cursor.fast_executemany = True

    rows_to_insert = []
    for feature in features:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"]
        rows_to_insert.append((
            props.get("HotSpringU", ""),
            props.get("Name", ""),
            props.get("OtherName", ""),
            props.get("Type", ""),
            props.get("County", ""),
            lat,
            lon,
            clean_numeric(props.get("Temperatur")),
            str(props.get("FlowRate_l", "")),
            str(props.get("Use_", "")),
            str(props.get("SiO2_\u00b0C", "")),
            str(props.get("Na_K_Ca_\u00b0", "")),
            HOT_SPRINGS_QUERY_URL,
            "Government Agency"
        ))

    cursor.executemany("""
        INSERT INTO Bronze.Raw_Hot_Springs
            (hot_spring_id, spring_name, other_name, spring_type, county,
             latitude, longitude, temperature_c, flow_rate_raw, use_code,
             sio2_geothermometer_c, na_k_ca_geothermometer_c, source_url, source_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows_to_insert)
    conn.commit()
    conn.close()
    print(f"  Loaded {len(rows_to_insert)} rows into Bronze.Raw_Hot_Springs")


if __name__ == "__main__":
    load_hot_springs()
