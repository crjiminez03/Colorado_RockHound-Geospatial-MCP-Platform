"""
RockHound MCP Server

Exposes governed, purpose-built tools over Streamable HTTP -- the AI
client never gets raw SQL access, only these specific, parameterized,
pre-approved queries against the curated Silver layer (or, for bedrock
geology and elevation, a live external API call).

Run with: python rockhound_server.py
Server listens on http://127.0.0.1:8000/mcp

Note on transport: this runs over Streamable HTTP rather than stdio because
the target MCP client (a desktop app with a remote-connector-only UI in this
build) required an HTTPS-reachable server. For local testing/demo, this was
exposed via a Cloudflare quick tunnel (`cloudflared tunnel --url
http://localhost:8000`) and verified working through the official MCP
Inspector (`npx @modelcontextprotocol/inspector`).

Architecture note: five tools (find_vacant_claims_near_mineral,
find_vacant_claims_near_location, check_land_access, check_vehicle_access,
find_mineral_locations) query only the local governed Silver layer. Two
tools (get_bedrock_geology, get_elevation) query live external APIs instead,
and are deliberately kept separate from the local-data tools to avoid
adding external-API latency/availability risk to the core governed
platform.
"""

from mcp.server import MCPServer
import pyodbc
import requests
from typing import Optional

mcp = MCPServer("RockHound")

CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    r"SERVER=localhost\SQLEXPRESS;DATABASE=RockHound;Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)

# Curated mapping of common rockhound/collector gem-variety and mineral
# species names to the parent commodity name actually used in MRDS (an
# economic-minerals database, not a gem-collector's database).
#
# CONFIRMED entries were verified directly against the real loaded data
# (see sql/10_mineral_name_verification_queries.sql) -- either the
# collector name genuinely does not appear anywhere in
# Silver.Mineral_Occurrences while the parent commodity does (Amazonite/
# Feldspar, Rhodochrosite/Manganese, Halite/Salt), or the mapping is such
# extremely well-established, universal mineralogy that no reasonable
# geologic classification would differ (Ruby/Sapphire are always
# varieties of Corundum, Aquamarine/Emerald are always varieties of
# Beryl, regardless of which database is asked).
GEM_VARIETY_TO_COMMODITY = {
    # Quartz family
    'amethyst': 'Quartz',
    'citrine': 'Quartz',
    'smoky quartz': 'Quartz',
    'rose quartz': 'Quartz',
    'rock crystal': 'Quartz',
    'chalcedony': 'Quartz',
    'agate': 'Quartz',
    'jasper': 'Quartz',
    'onyx': 'Quartz',
    'carnelian': 'Quartz',
    'bloodstone': 'Quartz',
    "tiger's eye": 'Quartz',
    'tigers eye': 'Quartz',
    'prasiolite': 'Quartz',
    'milky quartz': 'Quartz',

    # Feldspar family -- Amazonite confirmed directly against real data
    'amazonite': 'Feldspar',
    'moonstone': 'Feldspar',
    'labradorite': 'Feldspar',
    'sunstone': 'Feldspar',

    # Beryl family
    'aquamarine': 'Beryl',
    'emerald': 'Beryl',
    'morganite': 'Beryl',
    'heliodor': 'Beryl',
    'goshenite': 'Beryl',

    # Corundum family
    'ruby': 'Corundum',
    'sapphire': 'Corundum',

    # Chrysoberyl family
    'alexandrite': 'Chrysoberyl',

    # Olivine family
    'peridot': 'Olivine',

    # Zoisite family
    'tanzanite': 'Zoisite',

    # Spodumene family
    'kunzite': 'Spodumene',
    'hiddenite': 'Spodumene',

    # Garnet group species -- MRDS records these generically as "Garnet"
    'pyrope': 'Garnet',
    'almandine': 'Garnet',
    'spessartine': 'Garnet',
    'grossular': 'Garnet',
    'andradite': 'Garnet',
    'uvarovite': 'Garnet',
    'tsavorite': 'Garnet',
    'demantoid': 'Garnet',

    # Ore/economic minerals -- MRDS records the commodity, not the specific
    # mineral species that actually contains it
    'malachite': 'Copper',
    'azurite': 'Copper',
    'chalcopyrite': 'Copper',
    'galena': 'Lead',
    'sphalerite': 'Zinc',
    'carnotite': 'Uranium',
    'cassiterite': 'Tin',
    'cinnabar': 'Mercury',

    # Gypsum family -- confirmed directly against real data
    'selenite': 'Gypsum',
    'satin spar': 'Gypsum',
    'alabaster': 'Gypsum',

    # Confirmed directly against real data
    'rhodochrosite': 'Manganese',
    'halite': 'Salt',
}

# LOWER-CONFIDENCE entries: educated guesses based on standard economic
# geology reasoning (what commodity a mineral is typically reported
# under), NOT individually confirmed against the real loaded data the
# way every entry above was. Kept in a separate dictionary so the tool
# can flag these differently and be upfront that the mapping might be
# wrong -- if a lower-confidence search comes back empty, that could
# mean either "genuinely not documented" or "recorded under yet another
# name we haven't identified," and the tool says so explicitly rather
# than implying the same certainty as a confirmed mapping.
#
# NOT included here: "Topaz" -- despite Colorado having famous topaz
# localities (Pikes Peak, Devil's Head), there was genuinely conflicting
# reasoning about its likely parent commodity (possibly its own name,
# possibly Tin/Tungsten given its common pegmatite association) and no
# confident guess was made -- searched literally as typed instead.
GEM_VARIETY_TO_COMMODITY_LOWER_CONFIDENCE = {
    'wulfenite': 'Molybdenum',   # PbMoO4 -- Molybdenum is the defining economic metal
    'chrysocolla': 'Copper',     # common secondary copper mineral, parallels confirmed Malachite/Azurite
    'turquoise': 'Copper',       # commonly occurs in copper deposits, less certain than Chrysocolla
    'rhodonite': 'Manganese',    # parallels confirmed Rhodochrosite -- both manganese minerals
    'apatite': 'Phosphate',      # defining phosphate mineral; Crystal Peak, CO is a known locality
    'zircon': 'Zirconium',       # defining zirconium mineral; Pikes Peak batholith is a known locality
}


def resolve_gem_variety(mineral_name: str):
    """Check if mineral_name is a known gem-variety/species name with a
    different underlying MRDS commodity name. Returns (search_term,
    translation_note) -- translation_note is empty string if no
    translation occurred. Checks the CONFIRMED dictionary first, then
    the LOWER-CONFIDENCE one, with different wording for each so the
    user knows how much to trust the translation."""
    key = mineral_name.strip().lower()
    if key in GEM_VARIETY_TO_COMMODITY:
        real_commodity = GEM_VARIETY_TO_COMMODITY[key]
        note = f"Note: '{mineral_name}' is a variety/species of {real_commodity}, which is the name MRDS actually records -- searched as '{real_commodity}' instead.\n"
        return real_commodity, note
    if key in GEM_VARIETY_TO_COMMODITY_LOWER_CONFIDENCE:
        real_commodity = GEM_VARIETY_TO_COMMODITY_LOWER_CONFIDENCE[key]
        note = (f"Note: '{mineral_name}' is not tracked by that name in MRDS. Based on standard "
                f"geology (not verified against this specific dataset), it may be recorded under "
                f"'{real_commodity}' -- searched as that instead. If this returns nothing, the "
                f"mineral may genuinely not be documented here, or may be recorded under a "
                f"different name than this guess.\n")
        return real_commodity, note
    return mineral_name, ""


def get_connection():
    return pyodbc.connect(CONN_STR)


@mcp.tool()
def find_vacant_claims_near_mineral(mineral_name: str, max_distance_miles: float = 5.0, max_results: int = 50,
                                      latitude: Optional[float] = None, longitude: Optional[float] = None,
                                      search_radius_miles: float = 2.0) -> str:
    """Find vacant/closed mining claims near documented historical occurrences of a given mineral.
    Returns the closest matches, capped at max_results (default 50).

    Optional latitude/longitude: when provided, narrows the search to only consider
    mineral occurrences within search_radius_miles (default 2.0) of that point, rather
    than searching the entire state -- useful for "what can I find near my claim"
    rather than "where can I find this anywhere in Colorado."

    Gem-variety name support: recognizes common collector names that don't appear
    literally in MRDS (an economic-minerals database that records the parent mineral
    or commodity, not the gem variety or specific species) and searches the real
    underlying name instead. See GEM_VARIETY_TO_COMMODITY (confirmed against real
    data) and GEM_VARIETY_TO_COMMODITY_LOWER_CONFIDENCE (educated guesses, flagged
    as such in the output). Not exhaustive.

    Bug history: latitude/longitude were originally typed as plain "float = None",
    which passed Python's own syntax checks but failed MCP's strict argument
    validation at runtime (the type hint alone says "must be a real number",
    the default value doesn't override that for validation purposes) -- any
    call omitting coordinates failed with a validation error. Fixed by typing
    them as Optional[float] instead.

    Performance history: a plain JOIN on STDistance() took 13+ minutes for
    common minerals due to the spatial index not being used for that join
    shape -- fixed with CROSS APPLY. A later per-row county lookup then
    became the new bottleneck at scale (4+ minutes for ~24,570 raw Quartz
    matches, regardless of query syntax). Fixed with a two-phase approach:
    fast distance-only matching and capping first, then county lookup only
    on the small final result set instead of on every raw match.
    """
    search_term, translation_note = resolve_gem_variety(mineral_name)

    conn = get_connection()
    cursor = conn.cursor()
    max_meters = max_distance_miles * 1609.34

    if latitude is not None and longitude is not None:
        radius_meters = search_radius_miles * 1609.34
        cursor.execute("""
            DECLARE @searchPoint GEOGRAPHY = geography::Point(?, ?, 4326);
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
              AND mo.location.STDistance(@searchPoint) < ?
            ORDER BY c.is_recently_closed DESC, distance_miles
        """, latitude, longitude, max_meters, f"%{search_term}%", radius_meters)
    else:
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
        """, max_meters, f"%{search_term}%")

    all_rows = cursor.fetchall()

    if not all_rows:
        conn.close()
        if latitude is not None:
            return f"{translation_note}No vacant claims found near {search_term} occurrences within {search_radius_miles} miles of that location."
        return f"{translation_note}No vacant claims found near {search_term} occurrences within {max_distance_miles} miles."

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
        results.append(f"{r.claim_name}{county_note} - {r.distance_miles:.1f} mi from documented {search_term}{recency_note}")
    header = f"Showing closest {len(rows)} of {len(all_rows)} total matches:\n" if len(all_rows) > max_results else f"Showing all {len(rows)} matches:\n"
    return translation_note + header + "\n".join(results)


@mcp.tool()
def find_vacant_claims_near_location(latitude: float, longitude: float, radius_miles: float = 5.0, max_results: int = 50) -> str:
    """Find vacant (previously-claimed, now open) mining claims within a radius of a
    specific coordinate -- a location-based claim search, complementing
    find_vacant_claims_near_mineral's mineral-based search. Useful for "what's open
    near this specific spot" (e.g., near an existing claim) rather than "where can I
    find mineral X statewide."

    Also reports documented minerals within the same radius, automatically -- no
    mineral name needs to be entered. Reuses the same individual-mineral
    deduplication logic already proven in check_land_access (splitting comma-
    separated commodity lists into individual names before deduplicating, and
    filtering out the literal "nan" string artifact from a Phase 1 data-quality bug).

    Does not filter claims by mineral -- for mineral-specific vacant-claim searches,
    use find_vacant_claims_near_mineral instead (which also supports optional
    latitude/longitude for the same kind of location narrowing).

    For broader area context (nearest city, river, trailhead, hot springs) at the
    same coordinate, pair this with check_land_access.

    Coordinate note: each claim's reported latitude/longitude is the center of its
    bounding envelope (boundary.EnvelopeCenter()), not a survey-precise point --
    since most lode claims are simple, roughly rectangular shapes, this lands
    inside or very near the actual claim in nearly all cases, and is intended for
    trip planning (e.g. plotting claims on a map before a prospecting visit), not
    legal/survey purposes. Added directly from a real request: a user and a real
    claim holder wanted to plot nearby vacant claims on a map to plan an actual
    prospecting trip, and manually pulling coordinates via a one-off SQL query
    each time wasn't sustainable.

    Performance design: applies the same two-phase, capped-then-enriched pattern
    already proven throughout this project from the start -- fast distance-only
    matching and capping first, then county enrichment only on the small final
    result set, rather than risk recreating the correlated-subquery timeout found
    earlier in find_mineral_locations.
    """
    conn = get_connection()
    cursor = conn.cursor()
    radius_meters = radius_miles * 1609.34

    cursor.execute("""
        DECLARE @searchPoint GEOGRAPHY = geography::Point(?, ?, 4326);
        SELECT TOP (500) claim_key, claim_name, is_recently_closed, date_closed,
               boundary.STDistance(@searchPoint) / 1609.34 AS distance_miles,
               boundary.EnvelopeCenter().Lat AS claim_lat,
               boundary.EnvelopeCenter().Long AS claim_lon
        FROM Silver.Claims
        WHERE is_vacant = 1
          AND boundary.STDistance(@searchPoint) < ?
        ORDER BY distance_miles
    """, latitude, longitude, radius_meters)
    all_rows = cursor.fetchall()

    claims_section = ""
    if not all_rows:
        claims_section = f"No vacant claims found within {radius_miles} miles of that location.\n"
    else:
        rows = all_rows[:max_results]

        county_by_key = {}
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

        results = []
        for r in rows:
            recency_note = f" [CLOSED RECENTLY: {r.date_closed}]" if r.is_recently_closed else ""
            county = county_by_key.get(r.claim_key)
            county_note = f", {county} County" if county else ""
            results.append(f"{r.claim_name}{county_note} - {r.distance_miles:.1f} mi away ({r.claim_lat:.6f}, {r.claim_lon:.6f}){recency_note}")
        header = f"Showing closest {len(rows)} of {len(all_rows)} total vacant claims within {radius_miles} mi (coordinates are each claim's approximate center, for trip planning):\n" if len(all_rows) > max_results else f"Showing all {len(rows)} vacant claims within {radius_miles} mi (coordinates are each claim's approximate center, for trip planning):\n"
        claims_section = header + "\n".join(results) + "\n"

    cursor.execute("""
        DECLARE @searchPoint GEOGRAPHY = geography::Point(?, ?, 4326);
        SELECT DISTINCT commodity_type
        FROM Silver.Mineral_Occurrences
        WHERE location.STDistance(@searchPoint) < ?
    """, latitude, longitude, radius_meters)
    raw_commodity_strings = [r.commodity_type for r in cursor.fetchall() if r.commodity_type]
    conn.close()

    minerals_section = ""
    if raw_commodity_strings:
        individual_minerals = set()
        for raw_string in raw_commodity_strings:
            for mineral in raw_string.split(','):
                cleaned = mineral.strip()
                if cleaned and cleaned.lower() != 'nan':
                    individual_minerals.add(cleaned)
        unique_minerals = sorted(individual_minerals)[:20]
        minerals_section = f"\nDocumented minerals within {radius_miles} mi: {', '.join(unique_minerals)}"
    else:
        minerals_section = f"\nNo documented mineral occurrences within {radius_miles} mi"

    return claims_section + minerals_section


@mcp.tool()
def find_mineral_locations(mineral_name: str, latitude: Optional[float] = None, longitude: Optional[float] = None,
                             radius_miles: Optional[float] = None, max_results: int = 50) -> str:
    """Find general areas (nearest town + county) where a mineral has been documented --
    a trip-planning tool for "where should I even start looking," not a claim-status
    check. Does NOT check claim availability -- use find_vacant_claims_near_mineral or
    check_land_access afterward once you've picked a promising area, to see the real
    claim situation before visiting.

    Works statewide by default (leave latitude/longitude/radius_miles blank), or narrows
    to a radius around a specific point if all three are provided.

    Gem-variety name support: recognizes common collector names that don't appear
    literally in MRDS and searches the real underlying name instead. See
    GEM_VARIETY_TO_COMMODITY (confirmed against real data) and
    GEM_VARIETY_TO_COMMODITY_LOWER_CONFIDENCE (educated guesses, flagged as such
    in the output). Not exhaustive.

    Performance history: an earlier version enriched each capped raw occurrence
    with a nearest-city lookup AND a county lookup via correlated scalar
    subqueries -- structurally similar to the ORIGINAL slow pattern that caused
    the Quartz 13+ minute timeout in find_vacant_claims_near_mineral, just
    recreated here. Confirmed via real timeouts on statewide searches for common
    minerals (Moonstone, Galena, Amazonite/Feldspar). Fixed by switching to
    CROSS APPLY/OUTER APPLY (the proven pattern) and reducing the raw cap from
    500 to 200 to further cut total lookup volume.

    Bug history: an earlier version referenced Silver.Cities' spatial column as
    "location" instead of "boundary" in the nearest-city lookup, silently
    resolving to the outer CTE's own column and returning an arbitrary, wrong
    nearest city (confirmed: Cheraw, Otero County, for a Mt. Princeton/Chaffee
    County search). Fixed by correcting the column reference. Also affected by
    the same Optional[float] validation bug described in
    find_vacant_claims_near_mineral.

    Honesty note: 200 is a SAMPLE of raw occurrences for common minerals, not
    every one -- reported explicitly rather than implying completeness.
    """
    search_term, translation_note = resolve_gem_variety(mineral_name)

    conn = get_connection()
    cursor = conn.cursor()

    if latitude is not None and longitude is not None and radius_miles is not None:
        radius_meters = radius_miles * 1609.34
        cursor.execute("""
            DECLARE @searchPoint GEOGRAPHY = geography::Point(?, ?, 4326);
            WITH capped AS (
                SELECT TOP (200) location
                FROM Silver.Mineral_Occurrences
                WHERE commodity_type LIKE ?
                  AND location.STDistance(@searchPoint) < ?
            )
            SELECT city.city_name AS nearest_city, county.county_name AS county_name
            FROM capped
            CROSS APPLY (
                SELECT TOP 1 city_name FROM Silver.Cities ORDER BY boundary.STDistance(capped.location)
            ) city
            OUTER APPLY (
                SELECT TOP 1 county_name FROM Silver.Counties WHERE boundary.STContains(capped.location) = 1
            ) county
        """, latitude, longitude, f"%{search_term}%", radius_meters)
    else:
        cursor.execute("""
            WITH capped AS (
                SELECT TOP (200) location
                FROM Silver.Mineral_Occurrences
                WHERE commodity_type LIKE ?
            )
            SELECT city.city_name AS nearest_city, county.county_name AS county_name
            FROM capped
            CROSS APPLY (
                SELECT TOP 1 city_name FROM Silver.Cities ORDER BY boundary.STDistance(capped.location)
            ) city
            OUTER APPLY (
                SELECT TOP 1 county_name FROM Silver.Counties WHERE boundary.STContains(capped.location) = 1
            ) county
        """, f"%{search_term}%")

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        location_note = f" within {radius_miles} miles of that location" if latitude is not None else " anywhere in Colorado"
        return f"{translation_note}No documented occurrences of {search_term} found{location_note}."

    place_counts = {}
    for r in rows:
        if r.nearest_city:
            key = (r.nearest_city, r.county_name or "Unknown County")
            place_counts[key] = place_counts.get(key, 0) + 1

    if not place_counts:
        return f"{translation_note}Found {len(rows)} documented {search_term} occurrences, but could not determine nearby towns for any of them."

    sorted_places = sorted(place_counts.items(), key=lambda x: x[1], reverse=True)[:max_results]

    scope_note = f"within {radius_miles} mi of the given location" if latitude is not None else "statewide (based on a sample of up to 200 documented occurrences)"
    lines = [f"{translation_note}Areas with documented {search_term} occurrences ({scope_note}), by nearest town:"]
    for (city, county), count in sorted_places:
        lines.append(f"  - {city}, {county} -- {count} occurrence(s) in this sample")
    lines.append(f"\nThis shows WHERE {search_term} has been documented, not claim availability -- use find_vacant_claims_near_mineral or check_land_access next to see the real claim situation in a promising area before visiting.")
    return "\n".join(lines)


@mcp.tool()
def check_land_access(latitude: float, longitude: float, mineral_search_radius_miles: float = 2.0) -> str:
    """Check land ownership, claim status, county, nearest city, nearest named
    river, nearest trailhead, documented minerals, and nearby hot springs at a
    given coordinate -- a complete site report before heading out.

    Note: nearest river and nearest trailhead use the same efficient pattern
    as nearest city (ORDER BY STDistance with the spatial index) rather than
    a full radius scan, since "how far to the nearest one" is the useful
    question -- not an exhaustive list of every one within X miles.

    Note: hot springs and minerals use a radius scan (mineral_search_radius_miles)
    since those are sparse enough that "everything nearby" is more useful than
    "just the closest one."

    Mineral dedup note: commodity_type stores comma-separated mineral lists
    per site record. Deduplicating on the whole string still allowed the same
    individual mineral to appear multiple times if it showed up in different
    multi-mineral records. Fixed by splitting each record's commodity list
    into individual mineral names before deduplicating.

    Data-quality note: commodity_type previously contained the literal string
    "nan" on 1,564 rows -- a Phase 1 pandas artifact (str(NaN) == "nan") that
    silently passed through as if it were a real mineral name. Fixed at the
    Silver data layer (converted to true NULL), not patched here, so this
    tool and any future query against the same table are both covered.
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
             ORDER BY path.STDistance(@searchPoint)) AS nearest_river_distance_miles,
            (SELECT TOP 1 trail_name FROM Silver.Trailheads
             ORDER BY location.STDistance(@searchPoint)) AS nearest_trailhead,
            (SELECT TOP 1 location.STDistance(@searchPoint) / 1609.34 FROM Silver.Trailheads
             ORDER BY location.STDistance(@searchPoint)) AS nearest_trailhead_distance_miles
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

    if row.nearest_trailhead_distance_miles is not None and row.nearest_trailhead_distance_miles < 0.1:
        trailhead_note = f"\nAt trailhead: {row.nearest_trailhead}"
    else:
        trailhead_note = f"\nNearest trailhead: {row.nearest_trailhead} ({row.nearest_trailhead_distance_miles:.1f} mi away)" if row.nearest_trailhead else ""

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
                if cleaned and cleaned.lower() != 'nan':
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

    return f"Land type: {row.land_type}{claim_note}{county_note}{city_note}{river_note}{trailhead_note}{minerals_note}{springs_note}"


@mcp.tool()
def check_vehicle_access(latitude: float, longitude: float, vehicle_name: str = "2020 Ford Escape") -> str:
    """Check whether the nearest mapped track/road at a coordinate is likely
    suitable for a given vehicle, based on OpenStreetMap tags (surface,
    tracktype, 4wd_only, smoothness, access) and a vehicle's real profile
    (ground clearance, drivetrain, low-range availability) from Dim_Vehicle.

    Honesty note: most track segments (roughly 70-95% depending on the tag)
    have NO explicit difficulty rating in OSM. This tool reports that
    honestly as "no data available" rather than assuming a road is safe
    just because nothing marks it as dangerous -- OSM tagging coverage is
    real but partial, confirmed by checking actual field coverage across
    all 73,703 loaded track segments before building this logic. Verified
    against a real known-tagged road (Forrester Road: surface=unpaved,
    4wd_only=yes, smoothness=very_bad) to confirm the hazard-flagging
    branch actually fires correctly, not just the "no data" fallback.

    This is advisory only, based on crowdsourced data of variable quality
    (some segments are auto-imported from Census TIGER data and never
    manually verified) -- always verify road conditions locally before
    attempting a route, especially for a vehicle without low-range 4WD.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT vehicle_name, ground_clearance_inches, drivetrain, has_low_range, notes
        FROM Dim_Vehicle
        WHERE vehicle_name = ?
    """, vehicle_name)
    vehicle = cursor.fetchone()
    if not vehicle:
        conn.close()
        return f"No vehicle profile found for '{vehicle_name}'. Check Dim_Vehicle for available profiles."

    cursor.execute("""
        DECLARE @searchPoint GEOGRAPHY = geography::Point(?, ?, 4326);
        SELECT TOP 1 track_name, surface, tracktype, fourwd_only, smoothness, access,
               path.STDistance(@searchPoint) / 1609.34 AS distance_miles
        FROM Silver.Tracks
        ORDER BY path.STDistance(@searchPoint)
    """, latitude, longitude)
    track = cursor.fetchone()
    conn.close()

    if not track:
        return "No mapped track/road data found near this location."

    name = track.track_name or "(unnamed track)"
    header = f"Nearest mapped track: {name} ({track.distance_miles:.1f} mi away)\nVehicle: {vehicle.vehicle_name} ({vehicle.ground_clearance_inches}\" clearance, {vehicle.drivetrain}, {'has' if vehicle.has_low_range else 'no'} low-range)\n"

    if track.access and track.access.lower() in ('private', 'no'):
        return header + f"LEGAL ACCESS ISSUE: tagged access='{track.access}' -- may not be legally accessible regardless of vehicle capability."

    concerns = []
    if track.fourwd_only and 'yes' in track.fourwd_only.lower():
        concerns.append(f"tagged 4wd_only='{track.fourwd_only}'")
    if track.tracktype and track.tracktype.lower() in ('grade4', 'grade5'):
        concerns.append(f"tracktype='{track.tracktype}' (poor/unmaintained surface)")
    if track.smoothness and track.smoothness.lower() in ('very_bad', 'horrible', 'very_horrible', 'impassable'):
        concerns.append(f"smoothness='{track.smoothness}'")

    if concerns and not vehicle.has_low_range:
        return header + f"LIKELY NOT SUITABLE for this vehicle: {'; '.join(concerns)}. This vehicle has no low-range transfer case."

    if track.smoothness and track.smoothness.lower() == 'bad':
        return header + "CAUTION: smoothness rated 'bad' -- borderline for a vehicle without low-range 4WD."

    if not any([track.surface, track.tracktype, track.fourwd_only, track.smoothness]):
        return header + "NO DIFFICULTY DATA AVAILABLE for this specific segment -- OSM coverage on these tags is partial (most Colorado tracks are untagged for difficulty). Proceed with caution and verify locally before attempting."

    return header + f"No red flags in available tags (surface='{track.surface or 'unknown'}', tracktype='{track.tracktype or 'unknown'}'). Likely passable, but always verify locally."


@mcp.tool()
def get_bedrock_geology(latitude: float, longitude: float) -> str:
    """Look up bedrock/geologic formation information at a coordinate via the
    live Macrostrat API (macrostrat.org) -- a community geologic database.

    Unlike the local-data tools in this server, this queries an external live
    API on each call rather than the local governed Silver layer, since
    Macrostrat's data is naturally point-queried rather than bulk-loadable
    in a way that fits the Bronze/Silver pattern. Kept as a separate tool
    (not folded into check_land_access) to avoid adding external-API
    latency/failure risk to the core local-data tools.

    Note: multiple overlapping geologic map results are common and expected
    -- Macrostrat aggregates maps from many source datasets at different
    scales/resolutions that can genuinely overlap the same coordinate.
    Results are deduplicated by (rock unit name, lithology) pair.
    """
    url = f"https://macrostrat.org/api/v2/geologic_units/map?lat={latitude}&lng={longitude}&format=geojson"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        return f"Could not reach Macrostrat API: {e}"

    features = payload.get("success", {}).get("data", {}).get("features", [])
    if not features:
        return "No bedrock geology data available from Macrostrat for this location."

    seen = set()
    units = []
    for feature in features:
        props = feature.get("properties", {})
        name = props.get("name", "Unknown unit")
        lith = props.get("lith", "")
        age = props.get("best_int_name") or props.get("t_int_name", "")
        key = (name, lith)
        if key in seen:
            continue
        seen.add(key)
        units.append((name, lith, age))

    lines = [f"Bedrock geology at this location ({len(units)} mapped unit(s), from overlapping source maps at different scales):"]
    for name, lith, age in units:
        lith_note = f" -- lithology: {lith}" if lith else ""
        age_note = f" ({age})" if age else ""
        lines.append(f"  - {name}{age_note}{lith_note}")
    return "\n".join(lines)


@mcp.tool()
def get_elevation(latitude: float, longitude: float) -> str:
    """Look up ground elevation at a coordinate via the live Open-Elevation API
    (open-elevation.com), a free, open-source, community-run elevation service.

    Kept as a separate tool, not folded into check_land_access, for the same
    reason as get_bedrock_geology: this queries an external live API on each
    call rather than the local governed Silver layer, so it's deliberately
    isolated to avoid adding external-API latency/availability risk to the
    core local-data tools -- even though this particular lookup is much
    simpler than bedrock's multi-feature response, the architectural
    principle (external API calls stay separate) applies regardless of
    how simple any one external call happens to be.
    """
    url = f"https://api.open-elevation.com/api/v1/lookup?locations={latitude},{longitude}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        return f"Could not reach Open-Elevation API: {e}"

    results = payload.get("results", [])
    if not results:
        return "No elevation data available for this location."

    elevation_m = results[0].get("elevation")
    if elevation_m is None:
        return "No elevation data available for this location."

    elevation_ft = elevation_m * 3.28084
    return f"Elevation at this location: {elevation_m:.0f} m ({elevation_ft:.0f} ft)"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
