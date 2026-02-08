# Zip Processor (Async Background Processing)

When users upload large zip files (e.g. 30,000+ files), the HTTP request would time out (Container Apps default ~240 seconds). To avoid this, zip processing runs **asynchronously** via an Azure Function:

1. **Backend** `POST /upload-zip-complete`: Validates chunks, writes `_job.json` to blob, returns 200 immediately.
2. **Azure Function** `zip-processor`: Triggered when `_job.json` is created; processes the zip, indexes files, deletes session.

## Architecture

```
Frontend → init → chunk → chunk → ... → complete
                           ↓
              Backend writes _job.json to _sessions/{upload_id}/
                           ↓
              Azure Function (blob trigger) runs
                           ↓
              Process zip, index to AI Search, delete session
```

## Prerequisites

- `USE_USER_UPLOAD` enabled (user upload + login)
- User storage account (AZURE_USERSTORAGE_ACCOUNT, AZURE_USERSTORAGE_CONTAINER)

## Setup

### 1. Add zip-processor to azure.yaml

The zip-processor service is enabled in `azure.yaml`. If commented out, uncomment it to enable deployment.

### 2. Provision the Function App

When `USE_USER_UPLOAD` is true, the Bicep template (`infra/app/zip-processor.bicep`) automatically provisions:

- Function App with Flex Consumption plan
- Blob trigger on user storage: path `user-content/_sessions/{name}/_job.json`
- `UserStorage__accountName` = user storage account (identity-based connection)
- App settings from main template (search, OpenAI, user storage, etc.)
- Managed identity with:
  - Storage Blob Data Contributor on user storage
  - Search Index Data Contributor
  - OpenAI Cognitive Services User
  - Vision (if multimodal) and Content Understanding (if media describer)

### 3. Blob path

The blob trigger path must match where the backend writes `_job.json`. Default container is `user-content`. If you use a different `AZURE_USERSTORAGE_CONTAINER`, update the path in `zip_processor/function_app.py`:

```python
@app.blob_trigger(
    arg_name="blob",
    path="YOUR_CONTAINER/_sessions/{name}/_job.json",
    connection="UserStorage",
)
```

### 4. Deploy

After provisioning:

```bash
azd deploy zip-processor
```

Or deploy everything:

```bash
azd up
```

## Manual Azure Portal Setup (if not using Bicep)

1. Create a Function App (Python 3.10+, Consumption plan).
2. Add app settings: copy from backend (AZURE_SEARCH_SERVICE, AZURE_OPENAI_*, AZURE_USERSTORAGE_ACCOUNT, AZURE_USERSTORAGE_CONTAINER, etc.).
3. Add `UserStorage__accountName` = your user storage account name (identity-based blob connection).
4. Enable System-assigned managed identity; grant **Storage Blob Data Contributor** on the user storage account.
5. Deploy the zip_processor code (`azd deploy zip-processor` or manual publish).

## Frontend

The frontend shows: *"Processing started. Your files will be indexed shortly. This may take several minutes for large archives."*  
The uploaded files list will refresh when the user reopens "Manage file uploads" after processing completes.

## See it happen (end-to-end)

To see the blob trigger fire when `_job.json` is created and the zip get processed:

1. **Deploy** (if not already):
   ```bash
   azd up
   ```
   Ensure `USE_USER_UPLOAD` is true and user storage + zip-processor are deployed.

2. **Open the app** in the browser (the URL from `azd up` or your deployed frontend).

3. **Sign in** if the app uses authentication.

4. **Upload a zip** (e.g. a small React app or any folder zipped):
   - Go to **Manage file uploads** (or the upload area in the UI).
   - Choose a `.zip` file. The frontend will:
     - `POST /upload-zip-init` → get `upload_id`
     - `POST /upload-zip-chunk` for each chunk
     - `POST /upload-zip-complete` with `{ upload_id, filename }`
   - The backend writes `_job.json` to blob at `_sessions/{upload_id}/_job.json` and returns immediately.

5. **Watch the trigger and processing**:
   - **Azure Portal** → your resource group → **Function App** (zip-processor) → **Functions** → select the blob-triggered function → **Monitor** or **Log stream**.
   - You should see an invocation when `_job.json` is created, then logs as the zip is combined, extracted, and files are indexed.

6. **Optional: run backend + frontend locally** (still using Azure blob and the deployed Function):
   - `./app/start.ps1` (Windows) or `./app/start.sh` (Linux/Mac), then `cd app/frontend && npm run dev`.
   - Upload a zip from the local UI; the backend (using env from `azd env get-values`) writes `_job.json` to Azure blob, and the **deployed** zip-processor runs in Azure. Watch logs in Portal as above.
