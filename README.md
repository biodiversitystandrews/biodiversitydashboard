# University of St Andrews Biodiversity Dashboard

This repository contains the code behind the University estate biodiversity
dashboard. Conversion scripts prepare the uploaded records, and `main.py`
serves them to the browser pages.

Start with the [maintenance handbook](docs/maintenance-handbook.md) if you are
changing data rules or conversion code. Use the
[workflow setup guide](docs/google-drive-workflows-setup.md) when working on the
upload automation or its credentials.

## Repository layout

```text
.
|-- .github/workflows/             Data-processing workflows
|-- data/                          Generated dashboard data
|-- docs/                          Maintenance and workflow guides
|-- frontend/
|   |-- dashboard-config.js        Production API address
|   |-- index.html                 Main dashboard
|   |-- polygon-analysis.html      Polygon comparison page
|   `-- polygon-analysis-worker.js Background polygon calculations
|-- scripts/                       Validation helpers
|-- tests/                         Regression tests
|-- dashboard_standardisation.py   Shared observation-data rules
|-- gpkgtoparquet.py               Current observation converter
|-- gpkgtobigdata.py               Large historical-data converter
|-- habitatgpkgconversiontogeojson.py
|-- habitatmanagementgpkgconversion.py
|-- cameratrapsgpkgconversion.py
|-- habitatsummaryprocessing.py
|-- hotspotprocessing.py
|-- download_from_gdrive.py
|-- main.py                        FastAPI backend
|-- requirements.txt
`-- netlify.toml
```

## How data reaches the dashboard

A Google Apps Script watches each upload folder. It sends the uploaded file ID
to GitHub, where the matching workflow downloads and converts the file. The
workflow commits its output under `data/`. The production API then reloads the
new data, and Netlify serves the pages embedded in WordPress.

The Apps Script code is held outside this repository.

## Run it locally

Python 3.11 is recommended. Fiona and GeoPandas also need GDAL.

Create an environment and install the packages:

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

Serve the frontend in another terminal:

```powershell
cd frontend
python -m http.server 5500
```

Open `http://127.0.0.1:5500/`. Do not open the HTML with a `file:` URL because
the browser may block API and worker requests.

Local port 5500 and the production frontend address must be allowed by the CORS
configuration in `main.py`.

## Observation data

`dashboard_standardisation.py` contains the shared rules for observation data.
Converters should call it rather than adding their own versions.

The standardisation code accepts common alternative headings. For example,
`observer` becomes `obs` and `scientific_name` becomes `species`. If two
headings mean the same thing, their values are merged row by row.

Split `year1`, `month` and `day` fields are preferred when building `Date`.
This prevents ambiguous dates such as `05/02/2026` from being reversed. The
combined date field is only a fallback. Sampling years run from May to April.

Observation points are converted to `EPSG:4326` before longitude and latitude
are written to Parquet. Invalid or non-point observation geometry should be
reported rather than silently converted.

Scientific names are matched against `species list.csv`. Add accepted name
changes to that master list and test them before processing live data.

## Dashboard pages

`frontend/index.html` is the public dashboard. It contains the filters, summary
figures, map layers, charts and records tables.

`frontend/polygon-analysis.html` is kept separate because its random comparison
work is heavier. A drawn polygon reports records, species richness, taxa groups
and survey effort. Its Biodiversity Index is:

```text
unique species / observation records
```

The ratio helps show the effect of uneven recording effort, but it is not a
complete ecological assessment. Always interpret it beside the number of
records and survey days.

The tool can compare two areas or the same area in different years. Random
polygons of the same shape and size provide relative ranks. The removal view
shows what the dashboard totals would look like without records from the drawn
area. A species appears in the lost-species list only when no records of that
species would remain in the selected dataset. This is a data scenario, not a
prediction that the species would disappear from the estate.

Hotspot and effort grids summarise existing records in 100-metre cells. They
describe the available data and should not be treated as independent survey
evidence.

## Backend and deployment

`main.py` is the read-only FastAPI backend. It loads every Parquet in `data/`,
checks the required columns and caches the combined DataFrame until the process
restarts. Generated JSON and GeoJSON files are served from the same directory.

Both frontend pages get the API address from `frontend/dashboard-config.js`.
The CORS list contains frontend addresses, not the backend address itself.

The production API starts with:

```text
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Its health check is `GET /health`.

Netlify publishes the `frontend` folder without a build step. Keep both HTML
pages, `dashboard-config.js` and the polygon worker inside that folder.

## Data updates

Files uploaded to Google Drive are processed by workflows under
`.github/workflows/`. Generated files should not be edited by hand. Fix the
source data or converter, then rerun the workflow.

The Drive service account needs access to each upload folder. Its complete JSON
key is stored in the GitHub secret `GDRIVE_CREDENTIALS_DATA`. Apps Script keeps
its GitHub dispatch token in the Script Property `GITHUB_TOKEN`. Never commit
either credential.

See the [workflow setup guide](docs/google-drive-workflows-setup.md) for event
names, folder setup, manual runs and recovery steps.

## Checks before pushing

Run the automated checks:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q .
node scripts/check_inline_javascript.js
python scripts/check_workflow_contracts.py
```

For converter changes, process a representative GPKG and inspect the result in
QGIS. Check its dates, CRS, fields and row counts.

For frontend work, run the API and static server locally. Check the browser
console, filters, empty results and both map pages. Compare at least one polygon
total with an independent QGIS selection.

## Common problems

### The frontend cannot reach the API

Start Uvicorn and open `/health`. For a CORS error, add the exact frontend
origin, including its protocol and port, to the API configuration.

### A workflow cannot read Google Drive

Check that `GDRIVE_CREDENTIALS_DATA` contains a service-account JSON, not an
OAuth desktop credential. Share the source folder with the JSON's
`client_email`.

### GitHub rejects a workflow push

Another job may have updated `main` first. The workflow should rebase its
generated commit and retry. Do not solve this with a force-push.

### Dates appear reversed

Inspect `year1`, `month` and `day` in the source GPKG. Those fields should build
the dashboard date before an ambiguous combined date string is considered.

### Polygon analysis is slow

Try fewer random comparisons first. Confirm that
`polygon-analysis-worker.js` loaded in the browser console. Without the worker,
the page falls back to slower calculations on the main browser thread.

## Limits of the data

These are opportunistic observations rather than a controlled ecological
survey. Recording effort varies by place and time. Observer experience, access,
season and missing records can also affect the patterns shown.

The dashboard is useful for exploration and deciding where further work may be
needed. It does not replace ecological assessment or expert review.
