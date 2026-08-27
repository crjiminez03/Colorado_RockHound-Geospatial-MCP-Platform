-- ============================================================
-- RockHound: Mineral Name Verification Queries (Phase 3, addendum)
-- Reference/diagnostic queries only -- no new schema or tables in this
-- file. This documents the real verification process used to build the
-- gem-variety-to-commodity name mapping in rockhound_server.py
-- (GEM_VARIETY_TO_COMMODITY / GEM_VARIETY_TO_COMMODITY_LOWER_CONFIDENCE),
-- and the diagnostic query used to catch a real bug in
-- find_mineral_locations. Same role as 04_example_queries.sql: showing
-- the real diagnostic process, not just the final fixed code.
-- ============================================================

USE RockHound;
GO

-- ============================================================
-- Verification #1: Amazonite (Colorado's state mineral) does not exist
-- anywhere in MRDS by that name -- confirms the underlying data uses
-- "Feldspar" (the parent mineral), not the collector's variety name.
-- Same real pattern later confirmed for Rhodochrosite -> "Manganese"
-- and Halite -> "Salt". This is WHY the gem-variety mapping exists.
-- ============================================================

SELECT DISTINCT commodity_type
FROM Silver.Mineral_Occurrences
WHERE commodity_type LIKE '%feldspar%'
   OR commodity_type LIKE '%amazon%'
   OR commodity_type LIKE '%gem%';
-- Confirmed: "Amazonite" appears nowhere; "Feldspar" and "Gemstone" do.

SELECT DISTINCT commodity_type
FROM Silver.Mineral_Occurrences
WHERE commodity_type LIKE '%rhodochrosite%'
   OR commodity_type LIKE '%manganese%';
-- Confirmed: "Rhodochrosite" appears nowhere; "Manganese" does (Leadville,
-- Alma/Park County, and other real Colorado localities correctly surface
-- once searched under the parent commodity name).

-- ============================================================
-- Verification #2: batch check of several Colorado rockhounding classics
-- with genuinely uncertain parent-commodity mappings, checked together
-- rather than guessed one at a time.
-- ============================================================

SELECT DISTINCT commodity_type
FROM Silver.Mineral_Occurrences
WHERE commodity_type LIKE '%rhodonite%'
   OR commodity_type LIKE '%turquoise%'
   OR commodity_type LIKE '%wulfenite%'
   OR commodity_type LIKE '%chrysocolla%'
   OR commodity_type LIKE '%pyrite%'
   OR commodity_type LIKE '%halite%'
   OR commodity_type LIKE '%topaz%'
   OR commodity_type LIKE '%molybdenum%'
   OR commodity_type LIKE '%sulfur%'
   OR commodity_type LIKE '%salt%';
-- Result: "Halite" itself never appears, but "Salt" does -- confirmed
-- mapping. "Pyrite" partially appears as a substring of "Sulfur-Pyrite"
-- -- no explicit mapping needed, substring LIKE matching already finds
-- it. Rhodonite, Turquoise, Wulfenite, Chrysocolla, and Topaz all
-- returned zero literal matches with no confirmed parent commodity
-- either -- these became LOWER-CONFIDENCE educated guesses in the
-- Python mapping (or, for Topaz specifically, were left unmapped
-- entirely due to genuinely conflicting reasoning about what its
-- parent commodity would be).

-- ============================================================
-- Diagnostic: the real cause of the "Cheraw" bug in find_mineral_locations.
-- An earlier version of the tool referenced Silver.Cities' spatial column
-- as "location" (copy-paste from a pattern used elsewhere in this
-- project), but Cities' actual column name is "boundary". Since Cities
-- has no column literally named "location", SQL Server silently resolved
-- the reference to the CTE's own "location" column instead of raising an
-- error -- so every city was scored at distance zero from itself, and
-- TOP 1 returned an arbitrary row with no real relationship to the
-- actual search point. Confirmed by testing a known location (Mt.
-- Princeton / Chaffee County) and getting an obviously wrong, distant
-- result (Cheraw, Otero County) back.
-- ============================================================

-- The buggy pattern (illustrative only -- do not run):
-- SELECT TOP 1 city_name FROM Silver.Cities ORDER BY location.STDistance(capped.location)
-- Silently resolved "location" (left side) to capped.location, computing
-- distance-to-self (always zero) for every single city.

-- The fix: use the real column name.
-- SELECT TOP 1 city_name FROM Silver.Cities ORDER BY boundary.STDistance(capped.location)

-- Quick sanity check anyone can run to confirm Cities' real column names:
SELECT TOP 1 * FROM Silver.Cities;
-- Confirms the spatial column is named "boundary", not "location".
