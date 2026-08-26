-- ============================================================
-- RockHound: Cities & Counties Layer (Extension)
-- Source: US Census Bureau TIGER/Line Shapefiles
--   - Places (cities/towns/CDPs): Colorado-specific file
--   - Counties: national file, filtered to Colorado via STATEFP = '08'
--     (same "download nationwide, filter locally" pattern already used
--     for the mining claims and MRDS data)
-- ============================================================

USE RockHound;
GO

-- ---------- Bronze ----------
CREATE TABLE Bronze.Raw_Counties (
    county_fips VARCHAR(10),
    county_name VARCHAR(200),
    state_fips VARCHAR(2),
    geometry_wkt VARCHAR(MAX),
    source_url VARCHAR(500),
    source_type VARCHAR(50),
    load_timestamp DATETIME DEFAULT GETDATE()
);

CREATE TABLE Bronze.Raw_Places (
    place_fips VARCHAR(10),
    place_name VARCHAR(200),
    place_type VARCHAR(50),        -- incorporated place vs. census designated place (CDP)
    geometry_wkt VARCHAR(MAX),
    source_url VARCHAR(500),
    source_type VARCHAR(50),
    load_timestamp DATETIME DEFAULT GETDATE()
);

-- ---------- Silver ----------
CREATE TABLE Silver.Counties (
    county_key INT IDENTITY PRIMARY KEY,
    county_name VARCHAR(200),
    boundary GEOGRAPHY
);

TRUNCATE TABLE Silver.Counties;

INSERT INTO Silver.Counties (county_name, boundary)
SELECT
    county_name,
    geography::STGeomFromText(geometry_wkt, 4326).MakeValid()
FROM Bronze.Raw_Counties
WHERE geometry_wkt IS NOT NULL AND geometry_wkt <> '';

CREATE TABLE Silver.Cities (
    city_key INT IDENTITY PRIMARY KEY,
    city_name VARCHAR(200),
    city_type VARCHAR(50),
    boundary GEOGRAPHY
);

TRUNCATE TABLE Silver.Cities;

INSERT INTO Silver.Cities (city_name, city_type, boundary)
SELECT
    place_name,
    place_type,
    geography::STGeomFromText(geometry_wkt, 4326).MakeValid()
FROM Bronze.Raw_Places
WHERE geometry_wkt IS NOT NULL AND geometry_wkt <> '';

-- ---------- Spatial indexes (same reasoning as Phase 1 -- required for performant lookups) ----------
CREATE SPATIAL INDEX SIX_Counties_Boundary ON Silver.Counties(boundary);
GO
CREATE SPATIAL INDEX SIX_Cities_Boundary ON Silver.Cities(boundary);
GO

-- ---------- Sanity check ----------
SELECT TOP 5 county_name FROM Silver.Counties;
SELECT TOP 5 city_name, city_type FROM Silver.Cities;
