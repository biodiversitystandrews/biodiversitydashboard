# University Server Requirements

## Purpose

This document specifies the infrastructure needed to replace the paid Render service used by the University of St Andrews Biodiversity Dashboard. It covers the FastAPI backend only. The static frontend may remain on Netlify or the University WordPress site provided it can make HTTPS requests to the API.

## Service Profile

The backend is a read-only Python web API. It loads Parquet, GeoJSON and JSON files from the deployed Git repository into memory, filters and summarises biodiversity records, and serves data to the dashboard. It does not require a database or user login.

Start command:

```text
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Health-check endpoint:

```text
GET /health
```

## Required Platform

| Item | Minimum | Recommended |
|---|---:|---:|
| Operating system | Supported 64-bit Linux | Ubuntu 22.04 or 24.04 LTS |
| CPU | 2 virtual CPU cores | 4 virtual CPU cores |
| Memory | 4 GB RAM | 8 GB RAM |
| Disk | 10 GB | 20 GB, SSD-backed |
| Python | 3.11 | Latest patched Python 3.11 |
| Availability | Best-effort during working hours | Monitored service with automatic restart |

The host must support native geospatial dependencies used by GeoPandas/Fiona, including GDAL, GEOS and PROJ. Python packages are listed in `requirements.txt`.

## Network and Security

- Provide a stable University DNS name and HTTPS certificate.
- Terminate TLS at an institutional reverse proxy or load balancer and proxy requests to Uvicorn.
- Allow inbound HTTPS (`443`) from public dashboard users.
- Allow outbound HTTPS (`443`) for source deployment and approved dependency installation.
- Run the service as an unprivileged account with read access to the deployed repository.
- Do not place Google service-account keys or GitHub tokens in the repository. GitHub Actions currently performs Google Drive processing separately and does not require those secrets on the API host.
- Restrict CORS in `main.py` to the production WordPress/Netlify origins and approved development origins.

## Deployment and Operation

The preferred deployment flow is:

1. GitHub Actions processes uploaded data and commits generated files to the main branch.
2. A webhook or scheduled deployment job pulls the new commit onto the University host.
3. Dependencies are installed in a Python virtual environment when `requirements.txt` changes.
4. The API process restarts so its in-memory data cache loads the new files.
5. The deployment checks `/health` before directing production traffic to the new process.

Run Uvicorn under `systemd`, a container platform, or another University-supported process supervisor. Configure automatic restart after failure and after host reboot. Keep deployment logs, application logs and health-check alerts for diagnosis.

## Storage and Backup

The application has no writable production database. Generated dashboard datasets are versioned in GitHub, which is the recovery source. The server needs working space for the checked-out repository, Python environment and temporary deployment files. Normal API operation should treat the deployed data as read-only.

## Acceptance Checks

Before replacing Render, IT should confirm that:

1. `GET /health` returns a successful response over the final HTTPS hostname.
2. The WordPress dashboard can call the API without CORS or mixed-content errors.
3. Filter options, map records, habitat polygons, summaries and polygon-analysis data load successfully.
4. The service restarts automatically and reloads data after a deployment.
5. A representative full dashboard load remains responsive under expected concurrent use.
6. Logs and monitoring identify failed starts, repeated server errors and unavailable health checks.

## Capacity Review

The recommended allocation is deliberately above the current minimum to leave room for dataset growth and simultaneous users. Review memory, response time and generated-data size annually. Increase resources before adding substantially larger datasets, server-side spatial analysis or multiple API worker processes.
