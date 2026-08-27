-- ============================================================
-- RockHound: Trailheads Layer (Phase 3)
-- Source: OpenStreetMap, tag highway=trailhead, queried via the Overpass
-- API for the entire Colorado bounding box, exported as GeoJSON via
-- Overpass Turbo (https://overpass-turbo.eu/) -- see python/load_trailheads.py
-- for the exact query used and the reasoning for using Turbo's export
-- rather than scripting the Overpass API directly for this one-time pull.
--
-- Field coverage note: of 552 real Colorado trailheads, name was populated
-- on 469 (85%), operator on 87 (16%), fee on 42 (8%). Elevation and
-- vehicle-access tags (ele, 4wd_only, access, motor_vehicle) exist on this
-- data but on fewer than 5% of records -- not reliable enough to treat as
-- real dataset coverage. Phase 3's elevation and vehicle-access goals still
-- need their own dedicated data sources, not assumed to be covered here.
-- ============================================================

USE RockHound;
GO

CREATE TABLE Bronze.Raw_Trailheads (
    osm_id VARCHAR(50),
    trail_name VARCHAR(200),
    operator VARCHAR(200),
    has_fee VARCHAR(10),
    latitude DECIMAL(9,6),
    longitude DECIMAL(9,6),
    source_url VARCHAR(500),
    source_type VARCHAR(50),
    load_timestamp DATETIME DEFAULT GETDATE()
);

CREATE TABLE Silver.Trailheads (
    trailhead_key INT IDENTITY PRIMARY KEY,
    trail_name VARCHAR(200),
    operator VARCHAR(200),
    has_fee BIT,
    location GEOGRAPHY
);

-- ============================================================
-- Silver transform
-- ============================================================

INSERT INTO Silver.Trailheads (trail_name, operator, has_fee, location)
SELECT
    trail_name,
    operator,
    CASE WHEN has_fee = 'yes' THEN 1 ELSE 0 END,
    geography::Point(latitude, longitude, 4326)
FROM Bronze.Raw_Trailheads
WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

CREATE SPATIAL INDEX SIX_Trailheads_Location ON Silver.Trailheads(location);

-- Sanity check
SELECT TOP 10 trail_name, operator FROM Silver.Trailheads WHERE trail_name <> '';

-- ============================================================
-- Real data-quality bug found and fixed this phase: a Phase 1 loading
-- script (load_bronze.py, MRDS mineral occurrences) used pandas, which
-- represents missing numeric-like values as NaN. When cast to a Python
-- string, this became the literal text "nan" rather than a true NULL --
-- so "nan" was silently stored as if it were a real commodity/mineral
-- name in Silver.Mineral_Occurrences. This went undetected through all
-- of Phase 1 and most of Phase 2 (1,564 affected rows) until it finally
-- appeared in a check_land_access result alongside real minerals like
-- "Gold" and "Silver" -- plausible enough to not be immediately obvious
-- as a bug. Confirmed via COUNT(*) (1,564 exact matches), confirmed no
-- messier mixed-string cases existed (a LIKE '%nan%' check after the
-- fix returned zero rows), and fixed at the Silver data layer rather
-- than patched at the application/tool level, so every future query
-- against this table inherits the fix automatically.
-- ============================================================

UPDATE Silver.Mineral_Occurrences
SET commodity_type = NULL
WHERE commodity_type = 'nan';
