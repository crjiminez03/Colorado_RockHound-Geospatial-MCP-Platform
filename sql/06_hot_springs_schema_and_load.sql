-- ============================================================
-- RockHound: Hot Springs Layer (Phase 2)
-- Source: Colorado Geological Survey, CO_Geothermal_Map_v3_MapPackage
-- Layer 3: Hot Spring Use Type -- queried live via ArcGIS REST API,
-- no file download required (see /python/load_hot_springs.py).
--
-- 93 real, confirmed records -- matches the official published count
-- of known thermal areas in Colorado (CGS Publication MS-14).
-- ============================================================

USE RockHound;
GO

CREATE TABLE Bronze.Raw_Hot_Springs (
    hot_spring_id VARCHAR(50),
    spring_name VARCHAR(200),
    other_name VARCHAR(200),
    spring_type VARCHAR(100),      -- 'Thermal Spring', 'Well', 'Artesian Well', etc.
    county VARCHAR(100),
    latitude DECIMAL(9,6),
    longitude DECIMAL(9,6),
    temperature_c DECIMAL(6,2),
    flow_rate_raw VARCHAR(50),     -- raw text, may contain '-' for missing
    use_code VARCHAR(50),          -- raw use type code (e.g. 'Bd', 'SH,GH')
    sio2_geothermometer_c VARCHAR(50),   -- raw text, may be blank/negative
    na_k_ca_geothermometer_c VARCHAR(50),
    source_url VARCHAR(500),
    source_type VARCHAR(50),
    load_timestamp DATETIME DEFAULT GETDATE()
);

CREATE TABLE Silver.Hot_Springs (
    hot_spring_key INT IDENTITY PRIMARY KEY,
    spring_name VARCHAR(200),
    other_name VARCHAR(200),
    spring_type VARCHAR(100),
    county VARCHAR(100),
    temperature_c DECIMAL(6,2),
    flow_rate_lps DECIMAL(8,2),        -- NULL if unknown, cleaned from raw text
    use_description VARCHAR(200),       -- decoded from use_code using the CGS legend
    sio2_geothermometer_c DECIMAL(6,2), -- NULL if blank/unknown
    na_k_ca_geothermometer_c DECIMAL(6,2),
    location GEOGRAPHY
);

-- ============================================================
-- Silver transform: decodes Use_ codes to readable labels,
-- safely parses raw text fields (flow rate, geothermometer
-- estimates) into real decimals, treating '-' and blanks as NULL.
-- ============================================================

TRUNCATE TABLE Silver.Hot_Springs;

INSERT INTO Silver.Hot_Springs
    (spring_name, other_name, spring_type, county, temperature_c,
     flow_rate_lps, use_description, sio2_geothermometer_c,
     na_k_ca_geothermometer_c, location)
SELECT
    spring_name,
    other_name,
    spring_type,
    county,
    temperature_c,
    TRY_CAST(NULLIF(NULLIF(TRIM(flow_rate_raw), ''), '-') AS DECIMAL(8,2)),
    CASE TRIM(use_code)
        WHEN 'A'        THEN 'Agriculture'
        WHEN 'AC'       THEN 'Aquaculture'
        WHEN 'Acs'      THEN 'Aquaculture, Stock Tank'
        WHEN 'Bd'       THEN 'Bathing, developed'
        WHEN 'Bd,SH'    THEN 'Bathing developed, Space Heating'
        WHEN 'Bd,SH,GH' THEN 'Bathing developed, Space Heating, Green House'
        WHEN 'Bnd'      THEN 'Bathing'
        WHEN 'Bnd,A'    THEN 'Bathing not developed, Agriculture'
        WHEN 'MW'       THEN 'Mineral Water'
        WHEN 'N'        THEN 'None'
        WHEN 'SH'       THEN 'Space Heating'
        WHEN 'SH,GH'    THEN 'Green House'
        WHEN 'Unk'      THEN 'Unknown'
        ELSE 'Unknown'
    END,
    TRY_CAST(NULLIF(NULLIF(TRIM(sio2_geothermometer_c), ''), '-') AS DECIMAL(6,2)),
    TRY_CAST(NULLIF(NULLIF(TRIM(na_k_ca_geothermometer_c), ''), '-') AS DECIMAL(6,2)),
    geography::Point(latitude, longitude, 4326)
FROM Bronze.Raw_Hot_Springs
WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

CREATE SPATIAL INDEX SIX_HotSprings_Location ON Silver.Hot_Springs(location);

-- Sanity check -- hottest springs first
SELECT TOP 10 spring_name, spring_type, county, temperature_c, use_description
FROM Silver.Hot_Springs
ORDER BY temperature_c DESC;
