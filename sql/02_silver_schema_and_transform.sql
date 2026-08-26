-- ============================================================
-- RockHound: Silver Layer Schema + Transformation
-- Cleansed, deduplicated, converted to native SQL Server spatial types.
--
-- Key fixes applied here (see README "Real Engineering Challenges Solved"):
--   1. .MakeValid() repairs invalid/self-intersecting polygon geometry from
--      real-world government GIS data, which otherwise causes runtime errors
--      like: "24144: This operation cannot be completed because the instance
--      is not valid."
--   2. Deduplication: the "closed" and "closed-in-last-year" claim sources
--      overlap. ROW_NUMBER() keeps whichever version of each claim has a
--      populated date_closed value, so the more informative record wins.
-- ============================================================

USE RockHound;
GO

-- ---------- Silver.Claims ----------
CREATE TABLE Silver.Claims (
    claim_key INT IDENTITY PRIMARY KEY,
    claim_name VARCHAR(200),
    is_vacant BIT,
    is_recently_closed BIT,
    date_closed DATE,
    claim_type VARCHAR(50),
    county VARCHAR(100),
    boundary GEOGRAPHY
);

TRUNCATE TABLE Silver.Claims;

WITH ranked_claims AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY claim_name
            ORDER BY CASE WHEN date_closed IS NOT NULL AND date_closed <> '' THEN 0 ELSE 1 END
        ) AS rn
    FROM Bronze.Raw_Claims
    WHERE geometry_wkt IS NOT NULL AND geometry_wkt <> ''
)
INSERT INTO Silver.Claims (claim_name, is_vacant, is_recently_closed, date_closed, claim_type, county, boundary)
SELECT
    claim_name,
    CASE WHEN claim_status = 'Closed' THEN 1 ELSE 0 END,
    CASE WHEN TRY_CAST(date_closed AS DATE) >= DATEADD(YEAR, -1, GETDATE()) THEN 1 ELSE 0 END,
    TRY_CAST(date_closed AS DATE),
    claim_type,
    county,
    geography::STGeomFromText(geometry_wkt, 4326).MakeValid()   -- <-- geometry repair
FROM ranked_claims
WHERE rn = 1;

-- ---------- Silver.Land_Parcels ----------
CREATE TABLE Silver.Land_Parcels (
    parcel_key INT IDENTITY PRIMARY KEY,
    land_type VARCHAR(100),
    parcel_name VARCHAR(200),
    boundary GEOGRAPHY
);

TRUNCATE TABLE Silver.Land_Parcels;

INSERT INTO Silver.Land_Parcels (land_type, parcel_name, boundary)
SELECT
    land_type,
    parcel_name,
    geography::STGeomFromText(geometry_wkt, 4326).MakeValid()   -- <-- geometry repair
FROM Bronze.Raw_Land_Ownership
WHERE geometry_wkt IS NOT NULL AND geometry_wkt <> '';

-- ---------- Silver.Mineral_Occurrences ----------
CREATE TABLE Silver.Mineral_Occurrences (
    mineral_occurrence_key INT IDENTITY PRIMARY KEY,
    mineral_name VARCHAR(200),      -- site name (kept for display/reference)
    commodity_type VARCHAR(1000),   -- ACTUAL mineral/commodity -- query this field, not mineral_name
    location GEOGRAPHY
);

TRUNCATE TABLE Silver.Mineral_Occurrences;

INSERT INTO Silver.Mineral_Occurrences (mineral_name, commodity_type, location)
SELECT
    mineral_name_raw,
    commodity_type,
    geography::Point(latitude, longitude, 4326)
FROM Bronze.Raw_Mineral_Occurrences
WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

-- ---------- Sanity check: confirm spatial data loaded validly ----------
-- If this returns rows, the geometries are valid and joining correctly.
SELECT TOP 10
    c.claim_name,
    c.is_vacant,
    lp.land_type
FROM Silver.Claims c
JOIN Silver.Land_Parcels lp ON c.boundary.STIntersects(lp.boundary) = 1;
