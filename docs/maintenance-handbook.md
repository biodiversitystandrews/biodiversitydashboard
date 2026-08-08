# Dashboard Maintenance Handbook

## Who This Is For

This handbook is for future maintainers, including students who may be new to Python, JavaScript, GIS, GitHub Actions, or deployment. Start here before changing a converter or workflow. The README explains how to run the system; this document explains why the parts are arranged as they are and what can go wrong.

## System in One Paragraph

Staff place source files in Google Drive. A time-triggered Google Apps Script sends the Drive file ID to GitHub using a `repository_dispatch` event. A matching GitHub Actions workflow downloads the file, runs one conversion script, and commits generated Parquet, GeoJSON, or JSON files. Render restarts the FastAPI service from `main.py`, while Netlify serves the static files under `frontend/`. The WordPress page embeds that frontend.

## File and Workflow Ownership

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
| Hotspot and estate layers | `hotspotprocessing.py` | `update-hotspots.yml` | Three generated GeoJSON files |
| Shared observation rules | `dashboard_standardisation.py` | Imported by converters | No direct output |
| Google Drive transfer | `download_from_gdrive.py` | Used by Drive workflows | Temporary workflow input |
| Live API | `main.py` | Render deployment | JSON API responses |
| Main dashboard | `frontend/index.html` | Netlify deployment | Embedded dashboard page |
| Polygon analysis | `frontend/polygon-analysis.html` and worker | Netlify deployment | Embedded analysis page |

Both frontend pages read the backend address from `frontend/dashboard-config.js`. When Render is replaced, change the production URL there and update the API CORS origins in `main.py` or the `DASHBOARD_CORS_ORIGINS` environment variable.

Generated files under `data/` should not be manually edited. Correct the source or converter, rerun the relevant workflow, and let the workflow replace them.

## Observation Data Contract

`dashboard_standardisation.py` is the authoritative contract for observation columns. Alternative headings are normalised and duplicate semantic columns are merged row by row. Add a new alternative name there instead of adding one-off renames to individual converters.

Important rules:

1. Split `year1`, `month`, and `day` fields take precedence over a combined date because they are not day/month ambiguous.
2. UK-style date text is parsed day-first; ISO year-first text remains year-first.
3. Timezone information is removed without changing the displayed calendar date.
4. Sampling year runs from May through April.
5. Point geometry is transformed to EPSG:4326 and stored as longitude/latitude.
6. Non-point observation geometry is not silently converted to a centroid.
7. Text tokens such as `NULL`, `N/A`, and `None` become genuine missing values.

When changing these rules, run the standardisation tests and inspect a representative output in QGIS.

## Habitat, Management, and Camera Years

The source habitat and management files may contain several sampling years. Their converters validate the year field and write one annual GeoJSON per year. Camera-trap records may already contain a sampling-year label; otherwise the converter derives May-April sampling year from calendar year and deployment month.

Each of these workflows treats its upload as the current master dataset. It removes previously generated annual files only inside the temporary workflow checkout, runs the converter, and commits the replacement set only if conversion succeeds. A failed conversion therefore cannot delete production files.

## Biomscore

Biomscore is the arithmetic mean of valid scores from 0 to 3 for each habitat and year. The parser accepts numeric values and labels beginning with a score, such as `3 - High`. Missing or invalid values are excluded from the mean and must not be converted to zero.

Habitat area is always calculated after projecting polygons to British National Grid (`EPSG:27700`). Never calculate area directly from `EPSG:4326`: its coordinates are degrees, not metres, and the resulting hectare values can round to zero. Processing deliberately fails if CRS metadata is missing, coordinates are inconsistent with a geographic CRS, or an annual area total is zero. It also reports repaired invalid polygons and zero-area features in the workflow log.

If habitat-summary processing needs to be repeated, open **Actions > Update Habitat Summary JSON from Google Drive > Run workflow** and enter the ZIP file's Google Drive file ID. The normal Google Drive upload trigger continues to work automatically.

## API Data Loading

`main.py` loads every `data/*.parquet` file in alphabetical order and records the source filename. It validates required columns, preserves any source ID as `source_record_id`, then assigns one globally unique dashboard `id`. The combined DataFrame and large polygon payload are cached until the API process restarts.

Adding a Parquet file therefore adds its rows to all dashboard totals. Before adding one, confirm that it does not overlap an existing dataset. The API deliberately does not delete apparent duplicates because repeated observations may be legitimate.

## Known Risks and Recovery

### Google Apps Script archives too early

The current external Apps Script moves an upload to the Processed folder immediately after GitHub accepts the dispatch request, not after the workflow succeeds. If a workflow fails, retrieve that file from Processed, fix the cause, and upload it again. A future improvement would delay archiving until GitHub reports success.

### Multi-layer observation GeoPackages

Several historical observation converters select the populated layer with the most features. This works for current files but may choose the wrong layer if a future package contains a larger non-observation layer. Inspect workflow logs, and prefer an explicit layer or required-column scoring if this input format changes.

### Dataset overlap

All Parquets are concatenated. Similar-looking rows within a source are not automatically duplicates. Define an agreed observation identity and source ownership policy with the data owner before implementing deduplication.

### External taxonomy services

English-name fallback calls ITIS, NCBI, and GBIF. Network outages make these lookups slow or incomplete, although cached and master-list names still work. Do not make API lookup success a requirement for retaining an otherwise valid observation.

### Invalid GIS geometry

Habitat conversion repairs invalid polygonal geometry where possible. Review warnings in Actions logs; repeated repairs usually indicate that the source should also be corrected in GIS.

### Dependency changes

`requirements.txt` uses supported version ranges. Dependabot or a maintainer should review these ranges periodically. Update one dependency family at a time, run tests, then process representative data before deployment.

### Memory growth

The API holds all Parquet records in memory. Monitor memory as files grow. Move filtering to a database or query engine before the combined dataset no longer fits comfortably in the server allocation.

## Workflow Safety

All workflows that commit generated data share one GitHub concurrency group. This serialises pushes and avoids two uploads racing to update `main`. Jobs also have a 45-minute timeout. A workflow rebases its generated commit onto the latest branch before pushing; a genuine same-file conflict still stops safely for manual review.

Never use force-push in a data workflow. Never commit credentials. The Drive service-account JSON belongs only in the `GDRIVE_CREDENTIALS_DATA` repository secret.

## Safe Change Procedure

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

## Commenting Style

Comments should explain intent, precedence, assumptions, or a surprising constraint. Avoid comments that merely restate a line of code. Public helpers should have short docstrings describing inputs, output, and important failure behaviour. If a rule comes from a data-owner decision, record that decision here as well as near the implementation.

## Before Handing Over

- Confirm the biodiversity GitHub and Google accounts can be accessed by the responsible team.
- Confirm repository secrets and Apps Script properties exist without exposing their values.
- Confirm Render or its University replacement, Netlify, and WordPress ownership.
- Provide the current Drive folder IDs and Apps Script project links through an approved private channel.
- Demonstrate one successful upload and one failed-workflow recovery.
- Review open risks and any deliberately retained legacy scripts with the next maintainer.
