-- ============================================================
-- RockHound: Example Queries -- Diagnostic History & Final Optimized Pattern
--
-- This file documents the actual before/after of a real performance
-- investigation, kept intentionally rather than only showing the final
-- clean version -- the debugging process is the more useful artifact.
-- ============================================================

USE RockHound;
GO

-- ------------------------------------------------------------
-- STEP 1: Diagnose a field-mapping bug.
-- mineral_name is actually the MINE SITE NAME, not the mineral found there.
-- commodity_type is the field that reflects what was actually documented.
-- ------------------------------------------------------------
SELECT COUNT(*) FROM Silver.Mineral_Occurrences WHERE mineral_name LIKE '%Quartz%';    -- 11  (site names containing "Quartz")
SELECT COUNT(*) FROM Silver.Mineral_Occurrences WHERE commodity_type LIKE '%Quartz%';  -- 82  (real documented Quartz occurrences)


-- ------------------------------------------------------------
-- STEP 2: The ORIGINAL slow query pattern (DO NOT USE IN PRODUCTION).
-- This JOIN...ON STDistance(...) < X shape caused SQL Server's optimizer
-- to fall back to a nested loop scanning ~124 million estimated row
-- combinations for common minerals, observed taking 13+ minutes and
-- occasionally timing out entirely. Kept here for reference/comparison.
-- ------------------------------------------------------------
/*
DECLARE @mineral_name VARCHAR(200) = '%Quartz%';
DECLARE @max_meters FLOAT = 20.0 * 1609.34;

SELECT c.claim_name, c.county, c.is_recently_closed, c.date_closed,
       c.boundary.STDistance(mo.location) / 1609.34 AS distance_miles
FROM Silver.Claims c
JOIN (
    SELECT * FROM Silver.Mineral_Occurrences WHERE commodity_type LIKE @mineral_name
) mo ON c.boundary.STDistance(mo.location) < @max_meters
WHERE c.is_vacant = 1
ORDER BY c.is_recently_closed DESC, distance_miles;
*/


-- ------------------------------------------------------------
-- STEP 3: The FIXED, production query pattern.
-- CROSS APPLY drives the search from the (much smaller) mineral occurrence
-- side, doing a focused nearby-claims lookup per point -- this is the
-- documented pattern for reliably triggering spatial index usage for
-- "within distance" searches in SQL Server. Confirmed via execution plan:
-- brought a 13+ minute (non-terminating in practice) query down to ~36
-- seconds for Quartz (82 source points, 1,088 result rows).
-- ------------------------------------------------------------
DECLARE @mineral_name VARCHAR(200) = '%Quartz%';
DECLARE @max_meters FLOAT = 20.0 * 1609.34;

SELECT DISTINCT c.claim_name, c.county, c.is_recently_closed, c.date_closed,
       c.boundary.STDistance(mo.location) / 1609.34 AS distance_miles
FROM Silver.Mineral_Occurrences mo
CROSS APPLY (
    SELECT TOP (1000) c2.*
    FROM Silver.Claims c2
    WHERE c2.is_vacant = 1
      AND c2.boundary.STDistance(mo.location) < @max_meters
) c
WHERE mo.commodity_type LIKE @mineral_name
ORDER BY c.is_recently_closed DESC, distance_miles;


-- ------------------------------------------------------------
-- check_land_access equivalent -- point-in-polygon lookup
-- combining land ownership + claim status in one query
-- ------------------------------------------------------------
DECLARE @lat FLOAT = 39.5;
DECLARE @lon FLOAT = -105.7;

SELECT
    (SELECT TOP 1 land_type FROM Silver.Land_Parcels
     WHERE boundary.STContains(geography::Point(@lat, @lon, 4326)) = 1) AS land_type,
    (SELECT TOP 1 claim_name FROM Silver.Claims
     WHERE boundary.STContains(geography::Point(@lat, @lon, 4326)) = 1) AS claim_name,
    (SELECT TOP 1 is_vacant FROM Silver.Claims
     WHERE boundary.STContains(geography::Point(@lat, @lon, 4326)) = 1) AS is_vacant;
