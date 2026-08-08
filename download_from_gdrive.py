"""Download one Google Drive file using the dashboard service account.

GitHub Actions supplies the Drive file ID from a repository-dispatch payload and
writes the service-account secret to ``gdrive-credentials.json`` before invoking
this script. The uploaded file must be shared with the service account's
``client_email`` or Google Drive will return a permission error.
"""

import argparse
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DEFAULT_CREDENTIALS = Path("gdrive-credentials.json")


def build_drive_service(credentials_path=DEFAULT_CREDENTIALS):
    """Authenticate from a service-account JSON file and return the Drive client."""
    credentials_file = Path(credentials_path)
    if not credentials_file.is_file():
        raise FileNotFoundError(f"Google Drive credentials not found: {credentials_file}")
    credentials = service_account.Credentials.from_service_account_file(
        credentials_file,
        scopes=SCOPES,
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def download_file(file_id, destination, credentials_path=DEFAULT_CREDENTIALS):
    """Stream one Drive file to disk and report progress for the workflow log."""
    if not str(file_id).strip():
        raise ValueError("Google Drive file ID is empty.")

    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    service = build_drive_service(credentials_path)
    request = service.files().get_media(fileId=file_id)

    # MediaIoBaseDownload writes in chunks, avoiding a second full copy in memory.
    with destination_path.open("wb") as output:
        downloader = MediaIoBaseDownload(output, request)
        complete = False
        while not complete:
            status, complete = downloader.next_chunk()
            if status is not None:
                print(f"Download {int(status.progress() * 100)}%.")
    print(f"Downloaded Google Drive file to: {destination_path}")


def parse_arguments():
    """Read the repository-dispatch file ID and local destination path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_id", help="Google Drive file ID supplied by Apps Script.")
    parser.add_argument("destination", help="Local filename used by the conversion workflow.")
    parser.add_argument(
        "--credentials",
        default=str(DEFAULT_CREDENTIALS),
        help="Service-account JSON path (default: gdrive-credentials.json).",
    )
    return parser.parse_args()


def main():
    """Download the requested file and allow failures to stop GitHub Actions."""
    args = parse_arguments()
    download_file(args.file_id, args.destination, args.credentials)


if __name__ == "__main__":
    main()
