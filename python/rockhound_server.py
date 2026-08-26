"""
RockHound MCP Server

Exposes two governed, purpose-built tools over Streamable HTTP -- the AI
client never gets raw SQL access, only these specific, parameterized,
pre-approved queries against the curated Silver layer.

Run with: python rockhound_server.py
Server listens on http://127.0.0.1:8000/mcp

Note on transport: this runs over Streamable HTTP rather than stdio because
the target MCP client (a desktop app with a remote-connector-only UI in this
build) required an HTTPS-reachable server. For local testing/demo, this was
exposed via a Cloudflare quick tunnel (`cloudflared tunnel --url
http://localhost:8000`) and verified working through the official MCP
Inspector (`npx @modelcontextprotocol/inspector`).
"""

from mcp.server import MCPServer
import pyodbc

mcp = MCPServer("RockHound")

CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    r"SERVER=localhost\SQLEXPRESS;DATABASE=RockHound;Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)


def get_connection():
    return pyodbc.connect(CONN_STR)


@mcp.tool()
def find_vacant_claims_near_mineral(mineral_name: str, max_distance_miles: float = 5.0, max_results: int = 50) -> str:
    """Find vacant/closed mining claims near historical occurrences of a given mineral.
    Returns the closest matches, capped at max_results (default 50).

    Performance history: a plain JOIN on STDistance() took 13+ minutes for
    common minerals due to the spatial index not being used for that join
    shape -- fixed with CROSS APPLY. A later per-row county lookup then
    became the new bottleneck at scale (4+ minutes for ~24,570 raw Quartz
    matches, regardless of query syntax). Fixed with a two-phase approach:
    fast distance-only matching and capping first, then county lookup only
    on the small final result set instead of on every raw match.
    """
    conn = get_connection()
    cursor = conn.cursor()
    max_meters = max_distance_miles * 1609.34

    cursor.execute("""
        SELECT DISTINCT c.claim_key, c.claim_name, c.is_recently_closed, c.date_closed,
               c.boundary.STDistance(mo.location) / 1609.34 AS distance_miles
        FROM Silver.Mineral_Occurrences mo
        CROSS APPLY (
            SELECT TOP (1000) c2.*
            FROM Silver.Claims c2
            WHERE c2.is_vacant = 1
              AND c2.boundary.STDistance(mo.location) < ?
        ) c
        WHERE mo.commodity_type LIKE ?
        ORDER BY c.is_recently_closed DESC, distance_miles
    """, max_meters, f"%{mineral_name}%")
    all_rows = cursor.fetchall()

    if not all_rows:
        conn.close()
        return f"No vacant claims found near {mineral_name} occurrences within {max_distance_miles} miles."

    rows = all_rows[:max_results]

    county_by_key = {}
    if rows:
        claim_keys = [r.claim_key for r in rows]
        placeholders = ",".join("?" for _ in claim_keys)
        cursor.execute(f"""
            SELECT c.claim_key, cty.county_name
            FROM Silver.Claims c
            OUTER APPLY (
                SELECT TOP 1 county_name FROM Silver.Counties co
                WHERE co.boundary.STIntersects(c.boundary) = 1
            ) cty
            WHERE c.claim_key IN ({placeholders})
        """, claim_keys)
        for r in cursor.fetchall():
            county_by_key[r.claim_key] = r.county_name
    conn.close()

    results = []
    for r in rows:
        recency_note = f" [CLOSED RECENTLY: {r.date_closed}]" if r.is_recently_closed else ""
        county = county_by_key.get(r.claim_key)
        county_note = f", {county} County" if county else ""
        results.append(f"{r.claim_name}{county_note} - {r.distance_miles:.1f} mi from documented {mineral_name}{recency_note}")
    header = f"Showing closest {len(rows)} of {len(all_rows)} total matches:\n" if len(all_rows) > max_results else f"Showing all {len(rows)} matches:\n"
    return header + "\n".join(results)


@mcp.tool()
def check_land_access(latitude: float, longitude: float, mineral_search_radius_miles: float = 2.0) -> str:
    """Check land ownership, claim status, county, nearest city, nearest named
    river, documented minerals, and nearby hot springs at a given coordinate --
    a complete site report before heading out.

    Note: nearest river uses the same efficient pattern as nearest city (ORDER
    BY STDistance with the spatial index) rather than a full radius scan, since
    "how far to the nearest named river" is the useful question for placer
    deposit potential -- not an exhaustive list of every river within X miles.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DECLARE @searchPoint GEOGRAPHY = geography::Point(?, ?, 4326);

        SELECT
            (SELECT TOP 1 land_type FROM Silver.Land_Parcels
             WHERE boundary.STContains(@searchPoint) = 1) AS land_type,
            (SELECT TOP 1 county_name FROM Silver.Counties
             WHERE boundary.STContains(@searchPoint) = 1) AS county_name,
            (SELECT TOP 1 city_name FROM Silver.Cities
             ORDER BY boundary.STDistance(@searchPoint)) AS nearest_city,
            (SELECT TOP 1 boundary.STDistance(@searchPoint) / 1609.34 FROM Silver.Cities
             ORDER BY boundary.STDistance(@searchPoint)) AS nearest_city_distance_miles,
            (SELECT TOP 1 river_name FROM Silver.Rivers
             ORDER BY path.STDistance(@searchPoint)) AS nearest_river,
            (SELECT TOP 1 path.STDistance(@searchPoint) / 1609.34 FROM Silver.Rivers
             ORDER BY path.STDistance(@searchPoint)) AS nearest_river_distance_miles
    """, latitude, longitude)
    row = cursor.fetchone()

    if not row or not row.land_type:
        conn.close()
        return "No land ownership record found for this location."

    cursor.execute("""
        DECLARE @searchPoint GEOGRAPHY = geography::Point(?, ?, 4326);
        SELECT claim_name, is_vacant
        FROM Silver.Claims
        WHERE boundary.STContains(@searchPoint) = 1
        ORDER BY is_vacant ASC, claim_name ASC
    """, latitude, longitude)
    claims = cursor.fetchall()

    claim_note = ""
    if claims:
        active_claims = [c.claim_name for c in claims if not c.is_vacant]
        vacant_count = sum(1 for c in claims if c.is_vacant)
        if active_claims:
            claim_note = f", ACTIVE claims here (do not dig): {', '.join(active_claims)}"
            if vacant_count:
                claim_note += f" [+ {vacant_count} vacant claim(s) also overlap this spot]"
        else:
            claim_note = f", all {vacant_count} claim(s) here are VACANT: {', '.join(c.claim_name for c in claims)}"

    county_note = f"\nCounty: {row.county_name}" if row.county_name else "\nCounty: not found"

    if row.nearest_city_distance_miles is not None and row.nearest_city_distance_miles < 0.1:
        city_note = f"\nLocated within: {row.nearest_city}"
    else:
        city_note = f"\nNearest city: {row.nearest_city} ({row.nearest_city_distance_miles:.1f} mi away)" if row.nearest_city else ""

    if row.nearest_river_distance_miles is not None and row.nearest_river_distance_miles < 0.1:
        river_note = f"\nOn or adjacent to: {row.nearest_river}"
    else:
        river_note = f"\nNearest named river: {row.nearest_river} ({row.nearest_river_distance_miles:.1f} mi away)" if row.nearest_river else ""

    radius_meters = mineral_search_radius_miles * 1609.34

    cursor.execute("""
        DECLARE @searchPoint GEOGRAPHY = geography::Point(?, ?, 4326);
        SELECT DISTINCT commodity_type
        FROM Silver.Mineral_Occurrences
        WHERE location.STDistance(@searchPoint) < ?
    """, latitude, longitude, radius_meters)
    raw_commodity_strings = [r.commodity_type for r in cursor.fetchall() if r.commodity_type]

    minerals_note = ""
    if raw_commodity_strings:
        individual_minerals = set()
        for raw_string in raw_commodity_strings:
            for mineral in raw_string.split(','):
                cleaned = mineral.strip()
                if cleaned:
                    individual_minerals.add(cleaned)
        unique_minerals = sorted(individual_minerals)[:15]
        minerals_note = f"\nDocumented minerals within {mineral_search_radius_miles} mi: {', '.join(unique_minerals)}"
    else:
        minerals_note = f"\nNo documented mineral occurrences within {mineral_search_radius_miles} mi"

    cursor.execute("""
        DECLARE @searchPoint GEOGRAPHY = geography::Point(?, ?, 4326);
        SELECT spring_name, temperature_c, use_description,
               location.STDistance(@searchPoint) / 1609.34 AS distance_miles
        FROM Silver.Hot_Springs
        WHERE location.STDistance(@searchPoint) < ?
        ORDER BY distance_miles
    """, latitude, longitude, radius_meters)
    springs = cursor.fetchall()
    conn.close()

    springs_note = ""
    if springs:
        spring_descriptions = [
            f"{s.spring_name} ({s.temperature_c}\u00b0C, {s.distance_miles:.1f} mi)"
            for s in springs
        ]
        springs_note = f"\nHot springs within {mineral_search_radius_miles} mi: {', '.join(spring_descriptions)}"
    else:
        springs_note = f"\nNo hot springs within {mineral_search_radius_miles} mi"

    return f"Land type: {row.land_type}{claim_note}{county_note}{city_note}{river_note}{minerals_note}{springs_note}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
