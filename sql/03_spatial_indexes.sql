-- ============================================================
-- RockHound: Spatial Indexes
--
-- Without these, spatial join/distance queries against the full Claims
-- and Mineral_Occurrences tables are extremely slow (observed: 13+ minutes
-- for common minerals like Quartz before indexing + query restructuring).
--
-- Note: creating the index alone is NOT sufficient -- the query pattern
-- also has to be one SQL Server's optimizer can actually use the index for.
-- See 04_example_queries.sql for the JOIN vs. CROSS APPLY comparison that
-- made the difference in practice.
-- ============================================================

USE RockHound;
GO

CREATE SPATIAL INDEX SIX_Claims_Boundary
ON Silver.Claims(boundary);
GO

CREATE SPATIAL INDEX SIX_MineralOccurrences_Location
ON Silver.Mineral_Occurrences(location);
GO

-- Confirm both indexes exist
SELECT name FROM sys.spatial_indexes WHERE name LIKE 'SIX_%';
