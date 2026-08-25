# Dashboard Maintenance Handbook

## About this guide

This is the working guide for whoever maintains the dashboard next. It explains
the choices behind the code and points out the parts most likely to cause
problems. The README covers local setup.

Instructions for credentials and workflow setup are in
[`google-drive-workflows-setup.md`](google-drive-workflows-setup.md).

## How an upload is processed

Staff upload source files to Google Drive. Apps Script sends the file ID to the
matching GitHub workflow. That workflow runs a converter and commits the new
file under `data/`.

The production host then restarts the API in `main.py`. Netlify serves the
frontend, which is embedded in WordPress.

## Which file does what

| Source or purpose | Conversion code | Workflow | Generated output |
|---|---|---|---|
| Current biodiversity observations | `gpkgtoparquet.py` | `update_data.yml` | `data/data.parquet` |
| All-years biodiversity observations | `gpkgtobigdata.py` | `update-bigdata.yml` | `data/bigdata.parquet` |
| Archived 2023 observations | `2023gpkgtoparquet.py` | `update_2023_data.yml` | `data/2023data.parquet` |
| VIP observations | `vipgpkgtoparquet.py` | `update_vip_data.yml` | `data/vipdata.parquet` |
| Intern observations | `interngpkgtoparquet.py` | `update_intern_data.yml` | `data/intern24_25.parquet` |
| Habitat polygons, all years | `habitatgpkgconversiontogeojson.py` | `update_habitat_data.yml` | `data/habitats_YYYY-YY.geojson` |
| Habitat management, all years | `habitatmanagementgpkgconversion.py` | `update-management-geojson.yml` | `data/management_YYYY-YY.geojson` |
| Camera traps | `cameratrapsgpkgconversion.py` | `update-cameratraps-geojson.yml` | `data/cameratraps_YYYY-YY.geojson` |
| Habitat summary ZIP | `habitatsummaryprocessing.py` | `update-habitat-summary.yml` | `data/habitat_summary.json` |
| Hotspot and estate layers | `hotspotprocessing.py` | `update-hotspots.yml` | Hotspot and boundary GeoJSON files |
| Shared observation rules | `dashboard_standardisation.py` | Imported by converters | No direct output |
| Google Drive transfer | `download_from_gdrive.py` | Used by Drive workflows | Temporary workflow input |
| Live API | `main.py` | Production API deployment | JSON API responses |
| Main dashboard | `frontend/index.html` | Netlify deployment | Embedded dashboard page |
| Polygon analysis | `frontend/polygon-analysis.html` and worker | Netlify deployment | Embedded analysis page |

Both pages read the API address from `frontend/dashboard-config.js`. CORS is
configured in `main.py` and can be extended with the
`DASHBOARD_CORS_ORIGINS` environment variable. CORS entries are frontend
addresses.

Do not edit generated files under `data/`. Fix the source or converter and run
the workflow again.

## Observation data rules

`dashboard_standardisation.py` defines the observation columns. It also handles
alternative headings and duplicate columns. Add new aliases there, not inside
one converter.

Current rules:

1. Split `year1`, `month`, and `day` fields take precedence over a combined date because they are not day/month ambiguous.
2. UK-style date text is parsed day-first; ISO year-first text remains year-first.
3. Timezone information is removed without changing the displayed calendar date.
4. Sampling year runs from May through April.
5. Point geometry is transformed to EPSG:4326 and stored as longitude/latitude.
6. Non-point observation geometry is not silently converted to a centroid.
7. Text tokens such as `NULL`, `N/A`, and `None` become genuine missing values.

After changing a rule, run the standardisation tests and inspect one output in
QGIS.

## Habitat, management and camera years

Habitat and management files may contain several sampling years. Their
converters write one GeoJSON file per year. Camera-trap data uses its existing
sampling-year label where available. Otherwise, the converter derives the year
from the calendar year and deployment month.

Each upload replaces the previous annual set for that source. Old generated
files are removed only in the workflow's temporary checkout. Nothing is
committed unless conversion succeeds, so a failed run does not delete the live
files.

## Biomscore

Biomscore is the mean score for each habitat and year. Valid values run from 0
to 3. The input may be numeric or a label such as `3 - High`. Missing values do
not count as zero.

Area is calculated in British National Grid (`EPSG:27700`). Do not calculate
area in `EPSG:4326`, because its coordinates are degrees rather than metres.

Processing stops if the CRS is missing or clearly wrong. It also stops when a
year has no usable area. Geometry repairs and zero-area features appear in the
workflow log.

To repeat habitat-summary processing, open **Actions > Update Habitat Summary
JSON from Google Drive > Run workflow** and enter the ZIP file's Drive file ID.

## Preparing habitat summary data

The habitat-summary workflow expects a ZIP archive containing these exact files:

```text
Habitat_Polygons University all years.gpkg
10m square habitats.gpkg
```

Prepare `10m square habitats.gpkg` in QGIS. Intersect the University 10-metre
grid with the habitat polygons for each year. The result needs one feature for
each habitat found in a square. The summary uses these features to count
occupied squares; it cannot calculate that count from the all-years file alone.

This step stays manual because drawing errors are easier to spot on a map than
to repair safely in code. Before uploading the ZIP, check the following in
QGIS:

1. Both required files are present and use the exact filenames above.
2. Every expected sampling year is present in both files.
3. The sampling-year and habitat-category fields contain the expected values.
4. Geometry is valid and there are no unintended empty or zero-area polygons.
5. The `broad` habitat category is populated where possible; missing values are displayed as `Unknown` by the dashboard.
6. Biomscore values are either numeric scores from 0 to 3 or labels beginning with one of those scores.
7. The 10-metre intersection contains records for every year that should show non-zero **No. 10m Squares** and **Squares (%)** values.

The processor calculates the table from the checked inputs. It stops rather
than publishing zeros when a year, usable geometry or valid area is missing.

Automated validation does not replace the QGIS review. Geometry repair may
prevent a crash, but it cannot tell whether an ecological boundary was drawn in
the right place. Correct mapping errors in QGIS and recreate the intersection.

## How the API loads data

`main.py` loads every `data/*.parquet` file in alphabetical order. It keeps the
source filename and preserves an input ID as `source_record_id`. Each combined
row then receives a dashboard `id`. The data stays cached until the API
restarts.

Every added Parquet contributes to the dashboard totals. Check that it does not
overlap an existing dataset. The API does not remove similar rows because some
repeated observations are legitimate.

## Things likely to go wrong

### Google Apps Script archives too early

Apps Script moves an upload to Processed as soon as GitHub accepts the request.
It does not wait for the workflow to finish. If processing fails, retrieve the
file from Processed and upload it again after fixing the cause.

### Multi-layer observation GeoPackages

Some historical converters choose the populated layer with the most features.
That may be wrong if a package contains a larger unrelated layer. Check the
workflow log when the selected layer looks suspicious.

### Dataset overlap

All Parquets are concatenated. Similar rows are not automatically duplicates.
Agree what counts as one observation with the data owner before adding
deduplication.

### External taxonomy services

English-name fallback uses ITIS, NCBI and GBIF. An outage can make those lookups
slow or incomplete. Cached names and the master list still work, so a failed
lookup should not remove an otherwise valid observation.

### Invalid GIS geometry

Habitat conversion repairs invalid polygons where possible. Repeated repair
warnings usually mean the source also needs correcting in GIS.

### Dependency changes

`requirements.txt` uses version ranges. Review them periodically. Change one
dependency family at a time and test it with representative data.

### Memory growth

The API keeps all Parquet records in memory. Watch memory use as the files grow.
Move filtering to a database or query engine before the combined data becomes
too large for the server.

## Workflow safeguards

Workflows that commit data share one concurrency group, so only one can push at
a time. Jobs stop after 45 minutes. Before pushing, a workflow rebases its
generated commit onto the latest `main`. A real same-file conflict still needs
manual review.

Do not force-push from a data workflow. Keep the Drive service-account JSON only
in the `GDRIVE_CREDENTIALS_DATA` repository secret.

## Making a change

1. Pull the latest `main` branch and confirm `git status` is clean.
2. Identify the owning converter and workflow using the table above.
3. Change shared rules in shared modules instead of copying logic.
4. Add or update a regression test that demonstrates the changed behaviour.
5. Run `python -m unittest discover -s tests -v`.
6. Run `python -m compileall -q .` and the inline JavaScript checker.
7. Process representative real and deliberately awkward input files locally.
8. Inspect GIS outputs in QGIS and verify dates, CRS, fields, counts, and annual splits.
9. Commit code separately from generated test output.
10. Watch the GitHub Actions run and deployed `/health` endpoint after pushing.

## Comments

Use comments for decisions or constraints that are not obvious from the code.
Do not narrate simple assignments. Public helpers should have short docstrings.
Record data-owner decisions here and beside the relevant implementation.

## Handover

- Confirm the biodiversity GitHub and Google accounts can be accessed by the responsible team.
- Confirm repository secrets and Apps Script properties exist without exposing their values.
- Confirm ownership of the production API, Netlify site, and WordPress page.
- Provide the current Drive folder IDs and Apps Script project links through an approved private channel.
- Demonstrate one successful upload and one failed-workflow recovery.
- Review open risks and any deliberately retained legacy scripts with the next maintainer.
