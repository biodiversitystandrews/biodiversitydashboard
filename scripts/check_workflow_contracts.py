"""Check the shared safety contract for Google Drive GitHub workflows.

This intentionally uses only Python's standard library. It is not a complete
YAML validator; GitHub performs that validation. Its purpose is to catch common
maintenance mistakes such as changing an Apps Script event name, removing the
manual recovery input, or forgetting the Drive credential secret.
"""

from pathlib import Path


DRIVE_WORKFLOWS = {
    "update_data.yml": "new-gpkg-file",
    "update-bigdata.yml": "new-bigdata-gpkg-file",
    "update_2023_data.yml": "new-2023-gpkg-file",
    "update_vip_data.yml": "new-vip-gpkg-file",
    "update_intern_data.yml": "new-intern-gpkg-file",
    "update_habitat_data.yml": "new-habitat-gpkg-file",
    "update-management-geojson.yml": "new-habitat-management-gpkg-file",
    "update-cameratraps-geojson.yml": "new-cameratraps-gpkg-file",
    "update-habitat-summary.yml": "new-habitat-summary-files",
}

REQUIRED_TEXT = {
    "workflow_dispatch:": "manual recovery trigger",
    "client_payload.file_id || inputs.file_id": "automatic/manual file-ID selection",
    "secrets.GDRIVE_CREDENTIALS_DATA": "Google service-account repository secret",
    "contents: write": "permission to commit generated dashboard data",
    "timeout-minutes:": "job timeout",
    "concurrency:": "shared write-serialization setting",
}


def check_workflow(path, event_type):
    """Return human-readable contract failures for one workflow file."""
    if not path.is_file():
        return [f"missing workflow file: {path}"]

    text = path.read_text(encoding="utf-8")
    failures = []
    if f"types: [{event_type}]" not in text:
        failures.append(f"{path.name}: missing repository event {event_type!r}")
    for expected, description in REQUIRED_TEXT.items():
        if expected not in text:
            failures.append(f"{path.name}: missing {description}")
    return failures


def main():
    """Check every Drive workflow and exit non-zero if any contract is broken."""
    workflow_dir = Path(".github/workflows")
    failures = []
    for filename, event_type in DRIVE_WORKFLOWS.items():
        failures.extend(check_workflow(workflow_dir / filename, event_type))

    if failures:
        print("Workflow contract check failed:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print(f"Checked {len(DRIVE_WORKFLOWS)} Google Drive workflow contracts successfully.")


if __name__ == "__main__":
    main()

