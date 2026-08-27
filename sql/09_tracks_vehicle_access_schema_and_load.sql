-- ============================================================
-- RockHound: Vehicle Access / Tracks Layer (Phase 3, final piece)
-- Source: OpenStreetMap, tag highway=track, via the Overpass API,
-- whole-Colorado bounding box, exported as GeoJSON via Overpass Turbo.
-- See python/load_tracks.py for the exact query used.
--
-- Field coverage note: of 73,703 real Colorado track segments, surface
-- was populated on 21,158 (29%), tracktype on 11,528 (16%), 4wd_only on
-- 3,797 (5%), smoothness on 7,536 (10%). Most segments have NO explicit
-- difficulty rating -- the vehicle-matching tool (get_bedrock_geology's
-- sibling in rockhound_server.py, check_vehicle_access) must report this
-- honestly as "no data available" rather than assuming a road is safe
-- just because nothing marks it as dangerous.
--
-- Data-quality note: many segments carry tiger:reviewed=no, meaning they
-- were auto-imported from Census TIGER data years ago and never manually
-- verified by a human OSM mapper -- a real caveat on data reliability.
-- ============================================================

USE RockHound;
GO

CREATE TABLE Bronze.Raw_Tracks (
    osm_id VARCHAR(50),
    track_name VARCHAR(200),
    surface VARCHAR(50),
    tracktype VARCHAR(50),      -- widened from VARCHAR(20) -- see challenge notes,
    fourwd_only VARCHAR(50),    -- real OSM values exceeded the original narrower
    smoothness VARCHAR(50),     -- column widths (e.g. "4wd_recommended" truncated
    access VARCHAR(50),         -- to "recommende" at VARCHAR(20))
    geometry_wkt VARCHAR(MAX),
    source_url VARCHAR(500),
    source_type VARCHAR(50),
    load_timestamp DATETIME DEFAULT GETDATE()
);

CREATE TABLE Silver.Tracks (
    track_key INT IDENTITY PRIMARY KEY,
    track_name VARCHAR(200),
    surface VARCHAR(50),
    tracktype VARCHAR(50),
    fourwd_only VARCHAR(50),
    smoothness VARCHAR(50),
    access VARCHAR(50),
    path GEOGRAPHY   -- LineString -- .ReorientObject() not applicable (line geometry)
);

-- ============================================================
-- Silver transform
-- ============================================================

INSERT INTO Silver.Tracks (track_name, surface, tracktype, fourwd_only, smoothness, access, path)
SELECT
    track_name,
    surface,
    tracktype,
    fourwd_only,
    smoothness,
    access,
    geography::STGeomFromText(geometry_wkt, 4326).MakeValid()
FROM Bronze.Raw_Tracks
WHERE geometry_wkt IS NOT NULL AND geometry_wkt <> '';

CREATE SPATIAL INDEX SIX_Tracks_Path ON Silver.Tracks(path);

-- Sanity check
SELECT COUNT(*) AS total_tracks FROM Silver.Tracks;
SELECT TOP 10 track_name, surface, tracktype, fourwd_only FROM Silver.Tracks WHERE track_name <> '';

-- ============================================================
-- Dim_Vehicle: vehicle reference profiles for access matching.
-- Starts with one real, personal test case -- designed to support
-- additional vehicle profiles being added later (e.g. a true 4x4 with
-- low-range) without any schema change.
-- ============================================================

CREATE TABLE Dim_Vehicle (
    vehicle_key INT IDENTITY PRIMARY KEY,
    vehicle_name VARCHAR(100),
    ground_clearance_inches DECIMAL(4,1),
    drivetrain VARCHAR(20),
    has_low_range BIT,
    notes VARCHAR(300)
);

INSERT INTO Dim_Vehicle (vehicle_name, ground_clearance_inches, drivetrain, has_low_range, notes)
VALUES ('2020 Ford Escape', 7.9, 'AWD', 0, 'Crossover AWD, no low-range transfer case -- not a true 4x4');

-- ============================================================
-- Verification queries used to confirm both branches of the
-- check_vehicle_access tool's logic actually fire correctly, not just
-- the "no data" fallback path:
--   1. Confirmed "no data" path with two real coordinates that happened
--      to land near untagged segments.
--   2. Deliberately pulled a real point directly from a KNOWN-tagged
--      road (Forrester Road: surface=unpaved, 4wd_only=yes) to confirm
--      the actual hazard-flagging branch triggers correctly:
-- ============================================================

SELECT TOP 1 track_name, surface, fourwd_only,
       path.STPointN(1).Lat AS lat, path.STPointN(1).Long AS lon
FROM Silver.Tracks
WHERE track_name = 'Forrester Road';
-- Confirmed result: 40.942218, -106.001034 -- correctly triggered
-- "LIKELY NOT SUITABLE" with both 4wd_only='yes' and smoothness='very_bad' flagged.
