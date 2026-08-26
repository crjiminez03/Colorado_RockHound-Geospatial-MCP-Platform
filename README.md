# RockHound — Colorado Rockhounding Intelligence Platform

A governed, spatially-aware data platform that answers a real question: "Where can I legally go rockhounding in Colorado, and what am I likely to find?" Built end-to-end from raw federal and state government data through a Medallion Architecture (Bronze/Silver-style layering) into a governed **MCP (Model Context Protocol) server** — allowing an AI agent to answer rockhounding questions grounded in real, curated, trustworthy spatial data rather than raw or unverified sources.

**Repo structure:** SQL scripts in [`/sql`](./sql), Python code in [`/python`](./python) — see those folders for the actual implementation.

---

## The Goal

Combine multiple independent public datasets — mining claim status, land ownership, and historical mineral occurrence records — into a single queryable platform, then expose that data to an AI system through a governed interface that only surfaces specific, safe, pre-approved queries rather than raw database access. This mirrors the same "AI-ready, governed data product" pattern increasingly asked for in modern data engineering roles.

**Specific question this answers:** "Find vacant/lapsed mining claims near documented occurrences of a mineral, and tell me whether I'm actually allowed to be there."

---

## Architecture

```mermaid
flowchart TD
    A["BLM Mining Claims<br/>(Active + Closed + Closed-Recent)"] --> D
    B["BLM Surface Management Agency<br/>(Land Ownership)"] --> D
    C["USGS MRDS<br/>(Mineral Occurrences)"] --> D

    D["BRONZE LAYER<br/>Raw ingestion, full provenance<br/>(source_url + source_type)"] --> E

    E["SILVER LAYER<br/>Cleansed, deduplicated<br/>Native geography types, MakeValid()<br/>Colorado-filtered"] --> F

    F["Spatial Indexes +<br/>CROSS APPLY Query Layer"] --> G

    G["MCP SERVER<br/>Streamable HTTP"] --> H["find_vacant_claims_near_mineral()"]
    G --> I["check_land_access()"]

    H --> J["MCP Inspector / AI Client"]
    I --> J
```

---

## Real Data Sources (all public, all free)

| Source | What it provides | Records (Colorado, filtered) |
|---|---|---|
| BLM MLRS Mining Claims — Not Closed | Active mining claims | 14,699 |
| BLM MLRS Mining Claims — Closed (full history) | Historical/vacant claims | 288,158 |
| BLM MLRS Mining Claims — Closed (last year) | Recency flag source | 1,165 |
| BLM Colorado Surface Management Agency | Land ownership (BLM, USFS, private, tribal, etc.) | 21,175 |
| USGS Mineral Resources Data System (MRDS) | Historical documented mineral occurrences | 17,669 |
| US Census TIGER/Line — Counties | County boundaries (national file, Colorado-filtered) | 64 |
| US Census TIGER/Line — Places | City/town/CDP boundaries, Colorado-specific | varies |
| Colorado Geological Survey — Geothermal Map v3 (Hot Springs) | Hot spring locations, temperature, use type, geothermometer estimates | 93 (matches official published count) |

All source records carry `source_url` and `source_type` (e.g., "Government Agency") for full data lineage and provenance tracking — a governance pattern built in intentionally, not an afterthought.

---

## Tech Stack

- **SQL Server** — native `geography` spatial data type, spatial indexing, `STDistance`/`STIntersects`/`STContains`, `MakeValid()`
- **Python** — `geopandas`, `pandas`, `pyodbc`, `shapely`
- **MCP Python SDK** (`mcp.server`) — Streamable HTTP transport
- **MCP Inspector** — official tooling for testing/verifying MCP servers
- **Cloudflare Tunnel** — local HTTPS exposure for remote MCP client testing

---

## Tools & Platforms Used

A detailed breakdown of what was used for what, since the actual development environment is part of the real story here.

### Data Sources (where the raw data came from)
| Source | Access Method | Use Case |
|---|---|---|
| [BLM Colorado GIS Data Portal](https://www.blm.gov/site-page/services-geospatial-gis-data-colorado) | Direct download (Shapefile/GeoJSON) | Colorado-specific Surface Management Agency (land ownership) data |
| BLM National GIS Hub (ArcGIS Hub) | Direct download (GeoJSON / File Geodatabase) | Mining claims (Active, Closed, Closed-Last-Year) — note: these particular downloads turned out to be *national* scope despite being found via a Colorado-focused search, which is why the Colorado bounding-box filter exists in `load_bronze.py` |
| [USGS MRDS](https://mrdata.usgs.gov/mrds/) | Direct download (CSV, "Flattened" format) | Historical mineral occurrence records — also nationwide by default, filtered to Colorado via the `state` column |

### Database & Query Development
| Tool | Use Case |
|---|---|
| **SQL Server Express** (local instance, named `SQLEXPRESS`) | The actual database engine — chosen because it's free and already commonly available for a personal project |
| **SQL Server Management Studio (SSMS)** | Schema creation, data verification, query development and testing, and — critically — **execution plan analysis** (Ctrl+M) used to diagnose the spatial index performance issue |

### Python Development
| Tool | Use Case |
|---|---|
| **Python 3.14** | Data ingestion scripting (`load_bronze.py`) and the MCP server itself (`rockhound_server.py`) |
| **pip** | Package management — `geopandas`, `pandas`, `pyodbc`, `shapely`, `mcp` |
| **PowerShell** | Running all Python scripts, file/folder management, and — notably — used directly to *write* source files via here-strings (`@'...'@ \| Set-Content`) when a text-editor save issue caused repeated stale-file problems mid-build |
| **winget** (Windows Package Manager) | Installing Python, the ODBC Driver 18 for SQL Server, and `cloudflared` |

### MCP-Specific Tooling
| Tool | Use Case |
|---|---|
| **MCP Python SDK** (`mcp` package, `mcp.server`) | Building the actual governed MCP server and its two tools |
| **MCP Inspector** (`npx @modelcontextprotocol/inspector`) | The official tool used to test and verify the server's tools work correctly — this became the primary demo/verification method after a specific consumer AI client's remote-connector flow turned out to require OAuth client registration that was out of scope for this project |
| **Cloudflare Tunnel** (`cloudflared`) | Exposed the local Streamable HTTP server over a temporary public HTTPS URL, since some MCP client integrations require HTTPS even for local development/testing |

### Version Control & Hosting
| Tool | Use Case |
|---|---|
| **GitHub** | Hosting this repository as part of a broader data engineering portfolio |



Two governed tools, deliberately scoped rather than exposing raw SQL access to an AI system:

**`find_vacant_claims_near_mineral(mineral_name, max_distance_miles, max_results)`**
Finds vacant/lapsed claims near documented historical occurrences of a given mineral, flagging which claims closed most recently (freshest opportunities), which county each falls in, and sorting by proximity. Results are capped (default 50) with a note when more exist, for both usability and performance reasons -- see the performance investigation in "Real Engineering Challenges Solved."

**`check_land_access(latitude, longitude, mineral_search_radius_miles)`**
Given a coordinate, returns a complete site report: land ownership type, every active mining claim covering that point (since any one active claim means "do not dig," and multiple claims commonly overlap in dense historic districts), a summarized vacant-claim count, the county, the nearest city and its distance, documented minerals within a configurable radius (deduplicated at the individual-mineral level, not the raw-record level), and any hot springs within that same radius -- since hot springs and mineral-rich water are geologically related.

Both tools query only the curated Silver layer through fixed, parameterized queries — the AI never gets arbitrary database access, only these specific, safe, purpose-built answers.

---

## Real Engineering Challenges Solved

This section exists because the debugging process is arguably the most representative part of the whole project — real data engineering isn't a clean first pass. See [`/sql/04_example_queries.sql`](./sql/04_example_queries.sql) for the actual diagnostic queries used to find and fix these.

1. **Invalid spatial geometry.** Real-world government GIS polygon data included self-intersecting/invalid geometries that caused runtime failures in SQL Server's strict `geography` type (`24144: instance is not valid`). Fixed with `.MakeValid()` applied during the Bronze-to-Silver transformation — see [`/sql/02_silver_schema_and_transform.sql`](./sql/02_silver_schema_and_transform.sql).

2. **A silent data-mapping bug.** The mineral search was initially matching against `mineral_name` (a mine's site name, e.g. "Silver King Mine") rather than `commodity_type` (what was actually documented as found there) — a correctness bug caught by comparing row counts: 11 site-name matches for "Quartz" vs. 82 real commodity matches.

3. **A real performance/query-plan problem.** A straightforward `JOIN ... ON STDistance(...) < X` pattern caused queries to silently take 13+ minutes for common minerals, because SQL Server's optimizer wasn't using the spatial index for that join shape — confirmed via execution plan analysis showing 124M+ estimated row operations on a nested loop join. Fixed by restructuring the query around `CROSS APPLY` (the documented pattern for reliably triggering spatial index usage in nearest-neighbor searches), bringing the same query down to ~36 seconds. See [`/sql/04_example_queries.sql`](./sql/04_example_queries.sql).

4. **National-scope data filtering.** Several "Colorado" datasets from federal sources were actually nationwide (one active-claims file was 579,730 rows before filtering to Colorado's 14,699). Filtered via bounding-box intersection during ingestion rather than loading and discarding downstream — see `COLORADO_BBOX_WKT` in [`/python/load_bronze.py`](./python/load_bronze.py).

5. **MCP client integration.** Discovered that the target MCP client's remote-connector flow expected OAuth client registration even for unauthenticated local servers. Worked around by running the server over Streamable HTTP with a Cloudflare quick tunnel for HTTPS, and validated functionality through the official MCP Inspector tool rather than a single consumer app's specific auth requirements.

6. **Inverted polygon ring orientation, affecting three separate tables.** Shapefile- and File-Geodatabase-sourced polygons (Counties, Cities, and the large historical Claims dataset) were sometimes stored with reversed ring winding order -- SQL Server's `geography` type interpreted these as "everywhere except X" rather than "X," which `.MakeValid()` does not detect or fix (it only repairs self-intersections, not orientation). Diagnosed by checking `STArea()` for implausibly large values (a genuine, correctly-oriented Colorado county should never approach ~510,000,000 sq km -- Earth's total surface area). Fixed with a conditional `.ReorientObject()` based on an area threshold. A first attempt at this fix used the wrong unit (`STArea()` returns square *meters*, not square kilometers), which incorrectly flipped several genuinely large, correctly-oriented counties -- caught and corrected by re-validating against all 64 real Colorado counties.

7. **A recurring parameter-count bug class, and a structural fix.** Repeating `geography::Point(?, ?, 4326)` inline multiple times within a single query made it easy to miscount the required parameter list, causing two separate "wrong parameter count" runtime errors. Fixed structurally by computing the coordinate point once via a SQL `DECLARE @searchPoint GEOGRAPHY = ...` variable and referencing it throughout the query, reducing most queries to just 2 real parameters and eliminating the bug class going forward rather than just fixing the immediate instance.

8. **A data-completeness design gap, not a bug.** `check_land_access` originally returned a single arbitrary claim via `TOP 1` with no explicit ordering. Testing against a real, known claim ("Rocket Six," verified against a friend's actual mining claim data) revealed that 14 separate claims -- 6 active, 8 vacant -- legitimately overlap that one coordinate, which is normal for a dense historic Colorado mining district. The fix wasn't a bug patch but a deliberate design decision: list every active claim by name (since any one of them means "do not dig"), and summarize vacant claims as a count rather than silently picking one and hiding the rest.

9. **A multi-stage performance investigation on a per-row enrichment lookup.** After adding a county lookup to enrich mineral-search results, common minerals (Quartz: ~24,570 raw matches) began timing out via the MCP tool call. Debugging ruled out several plausible causes in turn: capping with `TOP (N)` at the SQL level actually made things *dramatically worse* (4+ minutes vs. ~6 seconds uncapped) due to a SQL Server optimizer regression when `TOP` is combined with `ORDER BY` on an expensive computed column; capping in Python after fetching didn't help either, since the real cost was still being paid inside SQL Server before results were returned; and rewriting the county lookup as a correlated subquery, a `JOIN`, and an `OUTER APPLY` were all equally slow (~4 minutes), proving the bottleneck was the sheer number of spatial lookups (one per raw match), not query syntax. The actual fix: a two-phase query -- fast distance-only matching and capping first, then a spatial county lookup only on the small final result set (<=50 rows) instead of on every raw match. This is a good example of systematic elimination of plausible-but-wrong hypotheses being the real work of performance debugging, not a single clever fix found immediately.

10. **Finding an undocumented data source (Phase 2).** A public-facing Colorado Geological Survey hot springs web map (an Esri Web AppBuilder app) didn't expose its underlying data source anywhere in its UI. Rather than falling back to manually transcribing a narrative PDF report, the real REST Feature Service was tracked down by browsing the agency's public ArcGIS REST services directory (`cgsarcimage.mines.edu/arcgis/rest/services`) folder by folder, then confirming the correct layer by inspecting its field list before writing any load code. This turned a planned manual-entry data source into a fully automated one, and surfaced richer data (real geothermometer chemistry estimates, flow rate, use type) than the PDF alone would have.

11. **A field-level deduplication bug.** A "documented minerals nearby" feature deduplicated on entire comma-separated commodity strings (e.g. `"Beryllium, Tantalum"` vs. `"Tantalum, Beryllium, REE"`), so the same individual mineral could still appear multiple times in the output if it showed up across different multi-mineral site records -- correct SQL-level `DISTINCT`, wrong level of granularity. Fixed by splitting each record's commodity list into individual mineral names and deduplicating at that level instead, verified by confirming a real test location's mineral list dropped from 28 entries with visible repeats to 15 genuinely distinct minerals.

---

## Example Output

```
> find_vacant_claims_near_mineral(mineral_name="Quartz", max_distance_miles=20)

Showing closest 50 of 24570 total matches:
AVENGER #15, Park County - 0.7 mi from documented Quartz
GAMBLE NO 1, Park County - 2.9 mi from documented Quartz
SARAH K #45, Chaffee County - 4.6 mi from documented Quartz
...

> check_land_access(latitude=38.7431, longitude=-106.1742, mineral_search_radius_miles=15)

Land type: PRI
County: Chaffee
Nearest city: Buena Vista (4.7 mi away)
Documented minerals within 15.0 mi: Beryllium, Bismuth, Clay, Cobalt, Construction, Copper, Dimension, Feldspar, Fluorine-Fluorite, Geothermal, Gold, Granite, Graphite, Iron, Kyanite
Hot springs within 15.0 mi: Mt. Princeton Hot Springs (84.00°C, 0.7 mi), Cottonwood (62.00°C, 5.3 mi), Browns Canyon (27.00°C, 8.6 mi)
```

Note the cross-source validation in the second example: "Geothermal" appears independently in the USGS mineral database at the same location where the Colorado Geological Survey's hot springs data shows Mt. Princeton Hot Springs (84°C) -- two independently sourced government datasets agreeing on the same real-world geological feature, without any code written specifically to check for that agreement.

---

## Repo Contents

```
RockHound/
├── README.md
├── sql/
│   ├── 01_bronze_schema.sql          -- Bronze table DDL
│   ├── 02_silver_schema_and_transform.sql  -- Silver DDL + MakeValid() + dedup logic
│   ├── 03_spatial_indexes.sql        -- Spatial index creation
│   ├── 04_example_queries.sql        -- Diagnostic + optimized query patterns
│   ├── 05_cities_counties_schema_and_load.sql  -- County/city boundary layer
│   └── 06_hot_springs_schema_and_load.sql      -- Hot springs layer (Phase 2)
└── python/
    ├── load_bronze.py                -- Bronze ingestion (Colorado-filtered, fast bulk insert)
    ├── load_hot_springs.py           -- Hot springs loader (live REST API query, Phase 2)
    └── rockhound_server.py           -- MCP server with governed tools
```

---

## Roadmap

- **Phase 2 (in progress):**
  - ✅ Hot springs (Colorado Geological Survey, live REST API) — done, integrated into `check_land_access`
  - ⏳ Rivers/streams (USGS NHD, placer deposit potential) — data source confirmed, Colorado filtering not yet applied
  - ⏳ Bedrock/geologic formation data (Macrostrat live API) — confirmed accessible, not yet scoped in detail
- **Phase 3 (scoped, not yet built):** Trailhead/parking entry points, elevation data, and vehicle-specific road access matching (ground clearance / 4WD requirements vs. a specific vehicle profile).

---

## Data Attribution

Data provided by the Bureau of Land Management (BLM) and U.S. Geological Survey (USGS), used in accordance with their public data terms. This is a personal project and is not affiliated with or endorsed by BLM or USGS. Data is provided "as is" and may contain errors or omissions — always verify claim status and land access independently before visiting any site in person.

---

## Other Projects

- **[Data Engineering & Systems Architecture Portfolio](https://github.com/crjiminez03/Data-Engineering-Systems-Architecture-Portfolio)** — A production-grade Medallion Architecture platform built on Microsoft Fabric, including PySpark/Delta Lake pipelines, Copilot Studio AI agents, KQL Eventhouse analytics, and full CI/CD via Azure DevOps.
