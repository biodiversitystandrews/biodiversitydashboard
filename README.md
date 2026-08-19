# University of St Andrews Biodiversity Dashboard

New maintainers should read [`docs/maintenance-handbook.md`](docs/maintenance-handbook.md) before changing data contracts, workflows, annual file handling, or generated outputs. First-time credential and automation setup is documented in [`docs/google-drive-workflows-setup.md`](docs/google-drive-workflows-setup.md).

This repository contains the data-processing pipeline, API, and browser-based dashboard used to display biodiversity records collected across the University of St Andrews estate.

The system has three main responsibilities:

1. Convert uploaded GeoPackage (`.gpkg`) files into standardised Parquet or GeoJSON data.
2. Serve records, filters, summaries, maps, and habitat data through a FastAPI application.
3. Display the data through a static Netlify frontend, including a separate polygon-comparison tool.

## Repository Structure

```text
.
|-- .github/workflows/           GitHub Actions data-processing workflows
|-- data/                        Generated Parquet, GeoJSON, and JSON dashboard data
|-- docs/                        Maintenance, workflow setup, and server documentation
|-- frontend/
|   |-- dashboard-config.js      Shared API deployment URL
|   |-- index.html               Main public dashboard
|   |-- polygon-analysis.html    Standalone polygon-comparison tool
|   `-- polygon-analysis-worker.js Background polygon calculations
|-- scripts/                     Validation and maintenance helpers
|-- tests/                       Small executable examples of data rules
|-- dashboard_standardisation.py Shared GPKG column, date, and geometry handling
|-- gpkgtoparquet.py             Main biodiversity GPKG conversion
|-- gpkgtobigdata.py             Large biodiversity GPKG conversion
|-- 2023gpkgtoparquet.py         Historical 2023 conversion
|-- interngpkgtoparquet.py       Intern dataset conversion
|-- vipgpkgtoparquet.py          VIP dataset conversion
|-- cameratrapsgpkgconversion.py Camera-trap GeoJSON conversion
|-- habitatgpkgconversiontogeojson.py
|-- habitatmanagementgpkgconversion.py
|-- habitatsummaryprocessing.py
|-- download_from_gdrive.py      Service-account Google Drive download helper
|-- main.py                      FastAPI application
|-- species list.csv             Master species lookup
|-- species_api_cache.csv        Cached species-name API results
|-- requirements.txt             Python dependencies
|-- requirements-workflows.txt   Google Drive workflow-only dependencies
|-- Procfile                     Render start command
`-- netlify.toml                 Netlify frontend configuration
```

## System Architecture

```text
Google Drive upload
        |
        v
Google Apps Script repository_dispatch event
        |
        v
GitHub Actions workflow
        |
        +-- downloads the uploaded file
        +-- standardises and converts it
        +-- commits generated data to data/
        |
        v
Render FastAPI service <---- Netlify frontend
```

The Google Apps Script is external to this repository. It monitors the Drive folder and sends a GitHub `repository_dispatch` event containing the uploaded file ID. The corresponding workflow downloads and processes that file.

## Local Development

### Requirements

- Python 3.11 is recommended.
- GDAL must be available for Fiona and GeoPandas.
- A current web browser is required for the frontend.

If you want to locally test this website without affecting the deployed one, create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Start the API from the repository root:

```powershell
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal, serve the frontend:

```powershell
cd frontend
python -m http.server 5500
```

Open:

```text
http://127.0.0.1:5500/
```

Do not open `index.html` directly with a `file:` URL. Browser origin restrictions can prevent API requests and local resources from working correctly.

Local frontend testing requires `http://localhost:5500` or `http://127.0.0.1:5500` in the FastAPI CORS origin list. Production must include the active Netlify domain.

## Data Standardisation

All biodiversity conversion scripts should use `dashboard_standardisation.py` rather than implementing their own column, date, or geometry rules.

### Supported Columns (Please update this if it changes)

The standardisation layer recognises common variants of:

| Standard field | Examples accepted |
|---|---|
| `Date` | `date`, `date_obs`, `date observed`, `date_observed` |
| `species` | `species name`, `scientific_name`, `scientific name` |
| `Taxa` | `taxa` |
| `obs` | `observer`, `observer name`, `observer_name` |
| `photoid` | `photo_id` |
| `year` | `school_year` |
| `year1` | `calendar_year`, `cal_year` |
| `comment` | `comments` |
| `longitude` | `long`, `lon`, `lng` |
| `latitude` | `lat` |

Column names are stripped, normalised, and mapped to the standard names. Duplicate semantic columns, such as `obs` and `observer`, are merged by taking the first non-missing value in each row.

Text values such as an empty string, `nan`, `none`, `null`, `n/a`, and `na` are treated as missing values where appropriate.


### Date Handling (Please update this if it changes)

When valid `year1`, `month`, and `day` columns are present, they are the preferred source for constructing `Date`. This avoids reversing ambiguous day/month values such as `05/02/2026`.

The combined `Date` field is used as a fallback when split fields are absent or incomplete. Timezone-aware values are converted to a consistent timezone-naive representation for dashboard use.

After parsing, the pipeline recalculates:

- `year1`: calendar year
- `month`: calendar month
- `day`: calendar day
- `year`: ecological sampling year, running from May to April

### Geometry Handling

Point geometry is transformed to `EPSG:4326` before longitude and latitude are extracted. The dashboard stores geographic locations as numeric `longitude` and `latitude` fields in Parquet output.

Missing, invalid, and non-point geometry must be reported by the relevant conversion script. A conversion should not silently invent coordinates.

### Species Information

The Latin scientific name in `species` is the matching key for the master `species list.csv` file. English names and taxonomic information should be obtained from the master list or the existing API cache.

Unknown species must be reported clearly. Changes to accepted scientific names should be made in the master species list and tested before processing production data.

## Main Dashboard

The public dashboard is `frontend/index.html`. It provides:

- Species, observer, taxa, year, and month filters
- Total records and biodiversity summaries
- Biodiversity, habitat, management, and camera-trap map layers
- Annual and temporal summaries
- Species and observer charts
- Paginated records and species tables
- Rectangle-based geographic filtering

The main dashboard does not run the expensive random-polygon comparison. It links to the standalone analysis page so casual users cannot accidentally start a long calculation while browsing ordinary summaries.

## Polygon Comparison Tool

The standalone tool is `frontend/polygon-analysis.html`.

The user draws a focal polygon and the tool calculates:

- Observation records
- Unique species, also called species richness
- Biodiversity Index
- Taxa groups
- Survey days
- A species summary table
- A records table

Single-area mode preserves the original workflow. Two-area mode accepts two
sequential polygons and presents their summaries side by side. Each polygon has
an independent observation-year filter. **Compare Same Area by Year** creates
Polygon 2 in exactly the same location for a like-for-like comparison between
years. **Copy Shape to Another Area** creates Polygon 2 with the same shape and
size and lets the user drag it to a different comparison location; its analysis
starts only after the user selects **Use This Location** in the non-blocking map
confirmation bar. Before confirming, the user can zoom, pan, or drag Polygon 2
again. **Undo Move** returns the copy to its previous position without running
an analysis. Changing either Data Year selector does not
start analysis automatically. **Apply Updated Years to Existing Polygons**
recalculates both results while retaining their current shapes and locations.
The map uses the full page width and both
complete polygon analyses are then displayed side by side below it, including
rankings, hotspot overlap, removal KPIs, record/species tables and CSV exports.
Once both results are available, the page reports Polygon 2 minus Polygon 1 for the
Biodiversity Index, records, unique species, taxa groups, survey days, and
observers. Positive values mean Polygon 2 is higher and negative values mean it
is lower; these observational differences are not by themselves evidence of a
change in ecological condition.

Every polygon also reports a removal scenario calculated by the backend using
the same KPI function as the main dashboard. It compares the selected annual or
all-years dataset before removal with the dataset remaining after records whose
exact coordinates fall inside the polygon are excluded. This describes a data
removal scenario and must not be presented as a prediction that development
would physically remove every recorded species. The results include a table of
species for which no records would remain in the selected dashboard dataset.
The removal table reports the
with-area value, without-area value, and change for observation records, unique
species, Shannon diversity, and Gini-Simpson diversity.

### Biodiversity Index

The project-defined Biodiversity Index is:

```text
unique species / observation records
```

This ratio provides a simple adjustment for unequal numbers of records. It must not be interpreted as a complete ecological assessment. Areas with very few observations can receive unstable or misleading values, so survey effort must always be shown beside the index.

### Stratified Random-Polygon Comparison

The focal polygon is compared with randomly translated polygons of the same shape and size across the mapped University Estate. Random centroids are stratified by the habitat `broad` classification. Every habitat stratum is represented when the requested sample size allows it, and remaining placements are allocated in proportion to mapped habitat area. Every translated polygon must remain wholly within the combined habitat estate boundary.

The comparison uses a deterministic seed derived from the focal geometry, habitat year, and requested sample count. Repeating the same analysis therefore produces the same comparison locations and ranks. If an unusually large shape cannot be placed the requested number of times, the interface reports the achieved sample count instead of silently claiming a complete comparison.

The focal polygon is then reported as a percentile. A high Biodiversity Index percentile means the focal result is higher than most random comparison areas. A high record-count percentile means the area has received more recording effort than most comparison areas.

Only a limited number of random polygons are drawn as map previews. All accepted polygons are still included in the calculations.

### Hotspot Overlap

`hotspotprocessing.py` summarises records into 100-metre estate grid cells and creates:

- `data/biodiversity_hotspots.geojson`
- `data/survey_effort_hotspots.geojson`
- `data/university_estate_boundary.geojson`

The final file is a pre-unioned version of the habitat estate boundary. Producing it in GeoPandas avoids expensive browser-side geometry unions and gives random-placement checks one authoritative estate outline. The polygon tool calculates the percentage of the focal polygon overlapping high and moderate biodiversity cells and high survey-effort cells. The main dashboard can display both generated layers. Hotspot layers are descriptive summaries of the available observations, not independent ecological survey evidence.

### Relative Biodiversity Categories

The colour categories show relative biodiversity value compared with sufficiently surveyed random areas of the same shape and size:

| Colour | Meaning |
|---|---|
| Red | Lower relative biodiversity value |
| Amber | Moderate relative biodiversity value |
| Green | Higher relative biodiversity value |
| Grey | Insufficient survey data for a reliable interpretation |

The interface should distinguish biodiversity value from evidence confidence. Low survey effort must not be presented as evidence of low biodiversity value.

Hotspot files currently combine all observation years. Annual polygon results
therefore omit hotspot-overlap percentages rather than labelling all-years cells
as annual evidence.

Grey requires at least five records across at least two distinct survey days. High requires a combined Biodiversity Index and species-richness score of at least 75, with both component percentiles at least 60. Moderate begins at a combined score of 40. These project thresholds must be reviewed with ecological specialists before being used in formal decision-making.

The observation-effort grid uses the same traffic-light direction: red for lower effort, amber for moderate effort and green for higher effort. Lower effort identifies a need for more recording; it is not evidence of lower biodiversity.

The Biodiversity Index and observation-effort grids each use 50% fill opacity
and separate fixed map panes. Consequently, displaying both grids produces the
same blended view regardless of which checkbox is selected first.

## API

The API is implemented in `main.py`. Important endpoints include:

| Endpoint | Purpose |
|---|---|
| `/health` | Service health check |
| `/api/filter-options` | Available dashboard filter values |
| `/api/records` | Paginated filtered records |
| `/api/record_page` | Locate the page containing one record |
| `/api/map_data` | Filtered map points or aggregated overview locations |
| `/api/polygon-analysis-data` | Cached unfiltered fields required by the polygon tool |
| `/api/polygon-removal-summary` | KPIs before and after excluding records inside a polygon |
| `/api/hotspots/biodiversity` | Precomputed biodiversity hotspot cells |
| `/api/hotspots/effort` | Precomputed survey-effort hotspot cells |
| `/api/summary/diversity` | Richness and diversity statistics |
| `/api/summary/annual_trends` | Annual summary statistics |
| `/api/summary/species_distribution` | Species distribution summary |
| `/api/summary/temporal_trends` | Monthly record totals |
| `/api/habitat_polygons` | Habitat GeoJSON |
| `/api/estate-boundary` | Pre-unioned University Estate boundary |
| `/api/summary/habitat` | Habitat summary JSON |

The Annual Habitat Trends view defaults to **Total** in the Habitat dropdown and
**Biomscore** in the Metric dropdown. It reads annual means from the habitat
summary, uses a 0-3 chart scale, and replaces the area table with annual average
Biomscore values. Users can select an individual habitat or switch the Metric
dropdown to either area measure.

The DataFrame is loaded once and cached in memory for the lifetime of the API process. Deploying newly committed data causes Render to restart and rebuild this cache.

When a map query contains more than 10,000 records, `/api/map_data` groups them into approximately 100-metre cells by taxa. This keeps the estate overview responsive without changing totals or summary statistics. Clicking an aggregate marker applies its exact cell bounds as the existing geographic filter and reloads the underlying full records. Queries below the threshold return precise individual markers.

## Automated Data Updates

Workflows under `.github/workflows/` process different input datasets. The normal sequence is:

1. A file is placed in the appropriate Google Drive upload folder.
2. Google Apps Script reads the file ID.
3. Apps Script sends a GitHub `repository_dispatch` event.
4. GitHub Actions writes the service-account JSON secret to a temporary credentials file.
5. `download_from_gdrive.py` downloads the file.
6. The relevant conversion script creates Parquet, GeoJSON, or JSON output.
7. GitHub Actions commits changed generated files.
8. Render and Netlify deploy the updated repository.

Habitat polygons, habitat management and camera-trap uploads are converted into annual files. Management records use their sampling-year field. Camera-trap records use an existing sampling-year label when supplied; otherwise the converter derives the May-April sampling year from calendar year and deployment month. Each upload is treated as the current master dataset, so previously generated annual files are removed before the replacement set is written.

Habitat-summary Biomscore is the arithmetic mean of valid 0-3 polygon scores for each habitat and year. The processor accepts numeric scores and labels beginning with the score, such as `3 - High`. Missing or invalid scores are excluded from the mean and are never silently converted to zero. Polygon areas are reprojected to British National Grid (`EPSG:27700`) before square metres and hectares are calculated. Missing, inconsistent, or zero-area annual geometry stops the workflow instead of publishing a misleading table of zeros.

The hotspot workflow also listens for successful completion of the Parquet and habitat-update workflows. This `workflow_run` trigger is required because commits pushed with GitHub's built-in `GITHUB_TOKEN` do not trigger an ordinary chained `push` workflow. The hotspot workflow can also be run manually from the Actions tab.

The uploaded Drive file must be shared with the service account's `client_email`. This is not the ordinary Google account email that owns the folder.

### Required Secrets

Repository secrets must include the service-account JSON expected by the workflow, currently named:

```text
GDRIVE_CREDENTIALS_DATA
```

The Google Apps Script project stores its GitHub access token in Script Properties, normally under:

```text
GITHUB_TOKEN
```

Never commit either credential, `gdrive-credentials.json`, an OAuth client secret, or a service-account private key.

## Deployment

### Render API

Render starts the backend with the command in `Procfile`:

```text
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Check the deployed API with:

```text
https://<render-service>/health
```

### Netlify Frontend

`netlify.toml` publishes the `frontend` directory without a build step. Both `index.html` and `polygon-analysis.html` must therefore be inside `frontend/`.

The production Netlify address must be included in `main.py` under the CORS origin list. The frontend API base URL must point to the active Render service.

Requirements for replacing the Render API with University infrastructure are documented in [`docs/university-server-requirements.md`](docs/university-server-requirements.md).

## Testing

Before deploying conversion changes:

1. Run the conversion against representative populated and empty GPKGs.
2. Include alternative column names, duplicate semantic columns, missing optional fields, mixed date formats, timezone dates, invalid numerics, missing geometry, and incorrect CRS cases.
3. Inspect output columns and data types.
4. Check dates and coordinates manually in QGIS.
5. Confirm that invalid or unmatched records are reported as intended.
6. Confirm that existing production records are not unexpectedly removed.

Before deploying frontend changes:

1. Start the API and frontend locally.
2. Check the browser console and network panel for failed requests.
3. Test all filters and clear-filter behaviour.
4. Test empty result sets.
5. Test map navigation on desktop and mobile-sized windows.
6. Test polygon comparisons with 100, 250, 500, and 1,000 samples.
7. Compare focal polygon totals against an independent QGIS selection.
8. Confirm that the main dashboard remains responsive while the polygon page is unused.

## Troubleshooting

### `ERR_CONNECTION_REFUSED`

The frontend cannot reach the local API. Start Uvicorn on port 8000 and verify `/health`.

### CORS Error

Add the exact frontend origin, including protocol and port, to the `origins` list in `main.py`. Do not use a wildcard with credentialed requests.

### Google service-account format error

`GDRIVE_CREDENTIALS_DATA` must contain the complete service-account JSON object, including `type`, `project_id`, `private_key`, `client_email`, and `token_uri`. OAuth desktop-client JSON is not interchangeable with service-account JSON.

### GitHub Action push rejected

Another process committed to the branch after the workflow checked it out. The workflow should pull or rebase safely before pushing, or retry from the latest branch state.

### Netlify attempts to install Python packages

Confirm that `netlify.toml` sets `base = "frontend"`, publishes `.`, and uses no Python build command. Python and GDAL belong to the Render backend, not the static Netlify deployment.

### Dashboard shows incorrect dates

Inspect `year1`, `month`, and `day` in the source GPKG. The standardisation layer should construct dates from these split fields before falling back to an ambiguous combined date string.

### Polygon calculation is slow

Use fewer random comparisons while testing. The production implementation uses a cached and pre-compressed compact API response, a pre-unioned estate boundary, a browser spatial grid, bounding-box candidate checks, a Web Worker, batched progress updates, and a limited number of preview polygons. Check the browser console to confirm that `polygon-analysis-worker.js` loaded; if it did not, the slower main-thread fallback is used.

## Maintenance Principles

- Keep data-format rules centralised in `dashboard_standardisation.py`.
- Do not duplicate date parsing across conversion scripts.
- Preserve raw source files outside the repository when auditability is required.
- Treat library deprecation warnings as maintenance tasks before they become errors.
- Test dependency upgrades before changing production versions.
- Keep secrets outside Git and rotate compromised credentials immediately.
- Document methodological changes before changing public interpretations or thresholds.
- Use Git history rather than retaining unused duplicate scripts indefinitely.

## Methodological Limitations

Dashboard records are opportunistic observations rather than a fully controlled ecological survey. Apparent biodiversity patterns can be affected by:

- Unequal recording effort
- Observer experience
- Seasonal differences
- Access and visibility
- Habitat coverage
- Changes in species names or taxonomy
- Missing or inaccurate records

The dashboard supports exploration and prioritisation. It does not replace an ecological impact assessment, protected-species survey, planning process, or expert review.
