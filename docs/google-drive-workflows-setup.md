# Google Drive and GitHub Workflow Setup

## About this guide

Use this guide when setting up or repairing the Google Drive workflows. It
assumes no previous knowledge of the project's Google Cloud configuration.

Never put a private key, GitHub token, or credentials JSON file in the
repository. Screenshots and handover documents must not reveal secret values.

## How an Upload Reaches the Dashboard

1. A staff member places a source file in its Google Drive upload folder.
2. A time-driven Google Apps Script checks that folder.
3. Apps Script sends a GitHub `repository_dispatch` event containing the file ID.
4. The matching GitHub Actions workflow authenticates as a Google service account.
5. `download_from_gdrive.py` downloads the source file by ID.
6. A converter creates a Parquet, GeoJSON, or JSON file under `data/`.
7. GitHub Actions commits the generated file.
8. The production host redeploys the API and Netlify serves the frontend.

There are two separate credentials:

- `GITHUB_TOKEN` is stored in **Apps Script Script Properties**. It lets Apps
  Script send an event to this one GitHub repository.
- `GDRIVE_CREDENTIALS_DATA` is stored in **GitHub Actions repository secrets**.
  It is the complete Google service-account JSON and lets workflows read shared
  Drive files.

These credentials are not interchangeable. An OAuth desktop-client JSON file
cannot replace a service-account JSON key.

## Workflow and Event Reference

| Uploaded source | GitHub event type | Workflow | Main generated output |
|---|---|---|---|
| Current observations GPKG | `new-gpkg-file` | Update Parquet Data from Google Drive | `data/data.parquet` |
| Historical BigData GPKG | `new-bigdata-gpkg-file` | Update BigData Parquet from Google Drive | `data/bigdata.parquet` |
| 2023 observations GPKG | `new-2023-gpkg-file` | Update 2023 Parquet Data from Google Drive | `data/2023data.parquet` |
| VIP observations GPKG | `new-vip-gpkg-file` | Update VIP Parquet Data from Google Drive | `data/vipdata.parquet` |
| Intern observations GPKG | `new-intern-gpkg-file` | Update Intern Parquet Data from Google Drive | `data/intern24_25.parquet` |
| All-years habitat GPKG | `new-habitat-gpkg-file` | Update Habitat GeoJSON from Google Drive | `data/habitats_YYYY-YY.geojson` |
| Habitat-management GPKG | `new-habitat-management-gpkg-file` | Update Management GeoJSON from Google Drive | `data/management_YYYY-YY.geojson` |
| Camera-trap GPKG | `new-cameratraps-gpkg-file` | Update Camera Traps GeoJSON from Google Drive | `data/cameratraps_YYYY-YY.geojson` |
| Habitat-summary ZIP | `new-habitat-summary-files` | Update Habitat Summary JSON from Google Drive | `data/habitat_summary.json` |
| No Drive upload | automatic or manual | Update Biodiversity Hotspot Layers | hotspot and estate GeoJSON files |

The habitat-summary ZIP must contain files with these exact names:

```text
Habitat_Polygons University all years.gpkg
10m square habitats.gpkg
```

Prepare the 10-metre-square file by intersecting each year's habitat polygons
with the University 10-metre grid in QGIS. Check the result on the map before
uploading it. The full procedure is in
[`maintenance-handbook.md`](maintenance-handbook.md#preparing-habitat-summary-data).

Hotspots normally run after successful observation or habitat workflows. They
can also be run manually and do not need a Google Drive file ID.

## Keep these details somewhere private

Keep the following operational details in an approved University password
manager or restricted handover record, not in GitHub:

- Google Cloud project name and project ID.
- Service-account email and current key creation date.
- Link to each Apps Script project and the Google account that owns its trigger.
- Input and Processed folder IDs for every source type.
- GitHub token owner, expiry date, and repository restriction.
- GitHub repository owner/name.
- Production API and Netlify project owners.

A Google Drive folder URL normally ends in `/folders/FOLDER_ID`. A file URL
normally contains `/d/FILE_ID/`. Copy only that ID when configuring a script or
manually running a workflow.

## Create the Google service account

Skip creation if the team already has a maintained service account such as a
GitHub Actions Drive reader. Reuse it and rotate its key when necessary.

1. Sign in to Google Cloud using the team-owned biodiversity account.
2. Select the existing dashboard project. Create a dedicated team-owned project
   only if none exists; do not use a student's personal project.
3. Open **APIs & Services > Library**, find **Google Drive API**, and enable it.
4. Open **IAM & Admin > Service Accounts**.
5. Create or select a service account, for example
   `github-actions-drive-reader`.
6. A broad Google Cloud project role is not required merely to read Drive files.
   Access to the source data comes from Drive sharing permissions.
7. Open the service account's **Keys** tab.
8. Select **Add key > Create new key > JSON**.
9. Store the downloaded file temporarily in a secure location. Google does not
   allow the same private key file to be downloaded again later.

The JSON must include at least:

```text
type = service_account
project_id
private_key_id
private_key
client_email
client_id
token_uri
```

If the JSON instead has an `installed` or `web` section, it is an OAuth client
file and is the wrong credential type.

## Share the Drive inputs

1. Open the service-account JSON and copy its `client_email`. It ends with
   `.iam.gserviceaccount.com` and is not the ordinary biodiversity Google email.
2. Share every monitored input folder with that email as **Viewer**.
3. Confirm newly uploaded files inherit access from the folder. If a workflow
   receives a 403 or 404 while downloading, share the individual file as a test.
4. The Apps Script owner needs edit access to both the input and Processed
   folders because Apps Script moves accepted uploads between them.

The workflow only reads uploaded files, so do not grant the service account
Editor access unless a future workflow genuinely requires writes to Drive.

## Add the Google JSON to GitHub

1. Open the dashboard repository on GitHub.
2. Go to **Settings > Secrets and variables > Actions**.
3. Under **Repository secrets**, select **New repository secret**.
4. Set the name exactly to:

   ```text
   GDRIVE_CREDENTIALS_DATA
   ```

5. Paste the entire service-account JSON object as the value, including its
   opening and closing braces. Do not paste only `private_key` or `client_email`.
6. Save the secret. GitHub will show its name and update date but never reveal
   its value again.

Do not add `gdrive-credentials.json`, `credentials.json`, or the downloaded key
to Git. If a key is ever committed, delete/disable it in Google Cloud immediately,
remove it from the repository history as required, and generate a replacement.

## Create the GitHub dispatch token

Apps Script needs a credential capable of calling:

```text
POST /repos/OWNER/REPOSITORY/dispatches
```

The current setup uses a fine-grained personal access token:

1. Sign in to GitHub using the team-owned biodiversity account.
2. Create a **fine-grained personal access token**.
3. Restrict repository access to only the biodiversity dashboard repository.
4. Grant **Contents: Read and write**. This is required for the repository
   dispatch endpoint; do not grant unrelated repository permissions.
5. Choose a finite expiry date and record a reminder before it expires.
6. If the repository belongs to an organization, complete any required
   organization approval step.
7. Copy the token immediately and store it securely.

A GitHub App would avoid tying this access to one user, but the existing Apps
Script expects a fine-grained token.

## Configure Apps Script

Each monitored Drive input normally has a script with four source-specific
settings:

```javascript
const repoOwner = "biodiversitystandrews";
const repoName = "biodiversitydashboard";
const inputFolderId = "INPUT_FOLDER_ID";
const processedFolderId = "PROCESSED_FOLDER_ID";
const eventType = "EVENT_TYPE_FROM_THE_TABLE_ABOVE";
```

The dispatch request must send the uploaded file ID:

```javascript
const payload = {
  event_type: eventType,
  client_payload: { file_id: fileId }
};

const response = UrlFetchApp.fetch(
  `https://api.github.com/repos/${repoOwner}/${repoName}/dispatches`,
  {
    method: "post",
    contentType: "application/json",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${githubToken}`
    },
    payload: JSON.stringify(payload)
  }
);

if (response.getResponseCode() !== 204) {
  throw new Error(`GitHub rejected the dispatch: ${response.getResponseCode()}`);
}
```

Store the token without putting it in source code:

1. In Apps Script, open **Project Settings**.
2. Under **Script Properties**, add:

   ```text
   Property: GITHUB_TOKEN
   Value: the complete fine-grained GitHub token
   ```

3. The script reads it with:

   ```javascript
   const githubToken = PropertiesService
     .getScriptProperties()
     .getProperty("GITHUB_TOKEN");
   ```

4. Run `processNewFiles` once from the editor and approve the requested Drive
   and external-request permissions.

## Install the Apps Script timer

1. In Apps Script, select **Triggers** (the clock/alarm icon).
2. Select **Add Trigger**.
3. Choose the function `processNewFiles`.
4. Choose **Time-driven** as the event source.
5. Choose a suitable minutes timer, normally every 5 or 10 minutes.
6. Save and authorize the trigger.
7. Confirm the trigger is owned by a team account that will remain available.

Installable triggers always run as the account that created them. Copying a
script project does not transfer that person's trigger automatically.

## Test an automatic upload

Test one source at a time:

1. Upload a small valid source file to the relevant input folder.
2. Run `processNewFiles` manually or wait for its timer.
3. Open **Apps Script > Executions** and confirm it sent the event without error.
4. Open **GitHub > Actions** and confirm the matching workflow appeared.
5. Open the run and inspect each step, especially download, conversion, tests,
   and commit/push.
6. Confirm the expected file under `data/` changed.
7. Confirm the production API redeployed and `/health` responds.
8. Confirm the public dashboard displays the expected year/count/summary.

Apps Script currently moves a file to Processed once GitHub accepts the event,
not once processing succeeds. A green Apps Script execution therefore does not
prove the GitHub workflow succeeded. Always inspect GitHub Actions after setup
changes or credential rotation.

## Manually Run a Drive Workflow

Drive workflows can also be started manually:

1. Open **GitHub > Actions**.
2. Select the workflow by name.
3. Select **Run workflow**.
4. Leave the branch as `main` unless testing a deliberate branch.
5. Paste the source file's Google Drive `file_id`.
6. Select **Run workflow** and monitor the run.

The file must still be accessible to the service-account `client_email`.

For **Update Biodiversity Hotspot Layers**, select **Run workflow** without a
file ID. Hotspots should normally be run last because they use the current
Parquet and habitat outputs.

## Rebuild all generated data

Do not routinely run every workflow. For a full rebuild, use this order and
wait for each workflow to finish because generated-data writes are serialized:

1. Current observations.
2. BigData observations.
3. 2023 observations.
4. VIP observations.
5. Intern observations.
6. All-years habitats.
7. Habitat management.
8. Camera traps.
9. Habitat summary ZIP.
10. Biodiversity hotspot layers.

Skip a historical source if it is deliberately retired. Before adding or
rebuilding Parquets, confirm that datasets do not overlap unintentionally.

## Credential Rotation

### Rotate the Google service-account key

1. Create a new JSON key for the same service account.
2. Replace the `GDRIVE_CREDENTIALS_DATA` GitHub secret with the entire new JSON.
3. Manually run one small Drive workflow and confirm download succeeds.
4. Delete/disable the old key in Google Cloud only after the test passes.
5. Update the private key-rotation record.

Creating another key does not automatically invalidate existing keys. Old keys
continue working until they are disabled or deleted.

### Rotate the GitHub token

1. Create a replacement fine-grained token with the same single-repository and
   Contents read/write restriction.
2. Replace `GITHUB_TOKEN` in every relevant Apps Script project's Script Properties.
3. Send one test upload and confirm a GitHub workflow appears.
4. Revoke the old token after every script has been updated.

## Troubleshooting

### No GitHub workflow appears

- Check Apps Script **Executions** for 401, 403, or 404 errors.
- Confirm `repoOwner`, `repoName`, and `event_type` exactly match the repository
  and workflow table.
- Confirm the workflow file is under `.github/workflows/` on the default branch.
- Confirm the GitHub token has not expired and has organization approval.
- Confirm the token has access only to the intended repository with Contents
  read/write permission.

### Workflow says the service-account JSON is malformed

`GDRIVE_CREDENTIALS_DATA` must be the entire JSON object. It must contain
`client_email`, `private_key`, and `token_uri`. OAuth desktop credentials are not
valid for `service_account.Credentials.from_service_account_file`.

### Workflow cannot download the Drive file

- Confirm the manual/dispatch payload contains the file ID, not a folder ID.
- Share the source folder or individual file with the service-account email.
- Confirm Google Drive API is enabled in the service account's Cloud project.
- Confirm the file was not deleted after Apps Script moved it to Processed.

### Workflow succeeds but the website does not change

- Confirm a generated file was committed; a run may report “No changes”.
- Confirm the production API deployed the new commit and restarted its data cache.
- Confirm Netlify points at the correct repository/branch and frontend directory.
- Inspect the API response directly before blaming the table or map display.
- For habitat summaries, confirm `data/habitat_summary.json` contains
  `"schema_version": 2`; otherwise it is a stale legacy artifact.

## Reference links

- Google Cloud: create/delete service-account keys:
  <https://docs.cloud.google.com/iam/docs/keys-create-delete>
- Google Cloud: create service accounts:
  <https://docs.cloud.google.com/iam/docs/service-accounts-create>
- Google Drive: enable the Drive API:
  <https://developers.google.com/workspace/drive/api/guides/enable-sdk>
- Google Drive: sharing permissions:
  <https://developers.google.com/workspace/drive/api/guides/manage-sharing>
- Google Apps Script: installable/time-driven triggers:
  <https://developers.google.com/apps-script/guides/triggers/installable>
- GitHub: repository-dispatch endpoint and token permission:
  <https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event>
- GitHub Actions secrets:
  <https://docs.github.com/en/actions/concepts/security/secrets>
