-- ============================================================
-- RockHound: Bronze Layer Schema
-- Raw ingestion tables. Preserve source data as-is, no cleansing.
-- Every table carries source_url + source_type for full provenance/lineage.
-- ============================================================

CREATE DATABASE RockHound;
GO
USE RockHound;
GO

CREATE SCHEMA Bronze;
GO
CREATE SCHEMA Silver;
GO

-- Mining claims: active, closed (full history), and closed-in-last-year
-- (the last of these is used to derive the is_recently_closed flag in Silver)
CREATE TABLE Bronze.Raw_Claims (
    claim_id VARCHAR(50),
    claim_name VARCHAR(200),
    claim_status VARCHAR(50),      -- 'Active' or 'Closed'
    claim_type VARCHAR(50),
    county VARCHAR(100),           -- note: source data has no county field populated; kept for future use
    date_closed VARCHAR(50),       -- raw text; parsed to DATE in Silver via TRY_CAST
    geometry_wkt VARCHAR(MAX),     -- raw polygon boundary as Well-Known Text
    source_url VARCHAR(500),
    source_type VARCHAR(50),       -- 'Government Agency', 'Public API', 'Community/Crowdsourced', etc.
    load_timestamp DATETIME DEFAULT GETDATE()
);

-- BLM Surface Management Agency: land ownership/type polygons
CREATE TABLE Bronze.Raw_Land_Ownership (
    parcel_id VARCHAR(50),
    land_type VARCHAR(100),        -- e.g. BLM, USFS, PRI (private), BIA, USFW
    parcel_name VARCHAR(200),
    geometry_wkt VARCHAR(MAX),
    source_url VARCHAR(500),
    source_type VARCHAR(50),
    load_timestamp DATETIME DEFAULT GETDATE()
);

-- USGS Mineral Resources Data System (MRDS): historical mineral occurrence points
CREATE TABLE Bronze.Raw_Mineral_Occurrences (
    site_id VARCHAR(50),
    mineral_name_raw VARCHAR(200), -- NOTE: this is actually the MINE SITE NAME, not the mineral itself
    latitude DECIMAL(9,6),
    longitude DECIMAL(9,6),
    commodity_type VARCHAR(1000),  -- the ACTUAL documented mineral/commodity type -- use this field for mineral search
    source_url VARCHAR(500),
    source_type VARCHAR(50),
    load_timestamp DATETIME DEFAULT GETDATE()
);
