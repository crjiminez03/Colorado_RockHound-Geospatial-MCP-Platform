-- ============================================================
-- RockHound: Rivers Layer (Phase 2)
-- Source: USGS National Hydrography Dataset (NHD), NHDFlowline feature class
-- Downloaded via https://apps.nationalmap.gov/downloader/ with a Colorado
-- state filter, delivered as three separate shapefile parts due to a size
-- limit (merged in load_rivers.py).
--
-- Filtered to NAMED streams/rivers only, using TWO feature type codes:
--   FType 460 (StreamRiver) -- standard single-line stream/river segments
--   FType 558 (ArtificialPath) -- the centerline NHD uses to represent
--     connectivity through a river/lake wide enough to be mapped as a
--     polygon area rather than a simple line
--
-- An earlier version filtered to FType 460 only, which silently excluded
-- most of the actual length of every major Colorado river (Colorado River,
-- South Platte, Arkansas River, etc. wherever they're wide enough to need
-- polygon representation) -- caught by grouping loaded data by river_name
-- and finding major rivers had implausibly short total lengths (e.g.
-- Colorado River: ~51 km) compared to well-known minor creeks. Including
-- both FTypes brought Colorado River to a realistic ~492 km, Arkansas
-- River to ~583 km, South Platte to ~560 km -- all consistent with their
-- real-world scale through the state.
-- ============================================================

USE RockHound;
GO

CREATE TABLE Bronze.Raw_Rivers (
    permanent_id VARCHAR(50),
    river_name VARCHAR(200),
    length_km DECIMAL(10,4),
    reachcode VARCHAR(20),
    ftype VARCHAR(10),
    geometry_wkt VARCHAR(MAX),
    source_url VARCHAR(500),
    source_type VARCHAR(50),
    load_timestamp DATETIME DEFAULT GETDATE()
);

CREATE TABLE Silver.Rivers (
    river_key INT IDENTITY PRIMARY KEY,
    river_name VARCHAR(200),
    length_km DECIMAL(10,4),
    path GEOGRAPHY   -- LineString/MultiLineString -- .ReorientObject() intentionally
                      -- NOT applied here, since ring-orientation inversion is a
                      -- polygon-specific issue and doesn't apply to line geometries
);

-- ============================================================
-- Fix: geopandas exports 3D line geometries from this source as
-- "LINESTRING Z (...)" / "MULTILINESTRING Z (...)", a WKT tag format
-- SQL Server's geography parser does not recognize (raises error 24142,
-- "Expected '(' at position 11. The input has 'Z'"). Strip the tag before
-- parsing -- the Z (elevation) values themselves are harmless once the
-- tag is removed, geography simply ignores the extra dimension.
-- ============================================================

UPDATE Bronze.Raw_Rivers
SET geometry_wkt = REPLACE(REPLACE(geometry_wkt, 'LINESTRING Z ', 'LINESTRING '), 'MULTILINESTRING Z ', 'MULTILINESTRING ')
WHERE geometry_wkt LIKE '%Z (%';

-- ============================================================
-- Silver transform
-- ============================================================

TRUNCATE TABLE Silver.Rivers;

INSERT INTO Silver.Rivers (river_name, length_km, path)
SELECT
    river_name,
    length_km,
    geography::STGeomFromText(geometry_wkt, 4326).MakeValid()
FROM Bronze.Raw_Rivers
WHERE geometry_wkt IS NOT NULL AND geometry_wkt <> '';

CREATE SPATIAL INDEX SIX_Rivers_Path ON Silver.Rivers(path);

-- ============================================================
-- Sanity check pattern: raw TOP-N by single segment length is misleading
-- for rivers, since NHD splits every river into many short segments (often
-- at confluences/road crossings) sharing the same river_name. GROUP BY
-- river_name with SUM(length_km) gives real total river length instead.
-- ============================================================

SELECT river_name, COUNT(*) AS segment_count, SUM(length_km) AS total_length_km
FROM Silver.Rivers
GROUP BY river_name
ORDER BY total_length_km DESC;
