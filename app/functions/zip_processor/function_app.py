"""Azure Function: Zip Processor (codebase intelligence).

Flow: frontend chunks the zip and uploads in parts → this function combines chunks
into the full zip (get_session_chunks), extracts using the zip library (zipfile),
then for each extracted file: chunks text, generates embeddings, and indexes into
Azure AI Search so the model can use semantic search over the codebase (e.g. React app).
No PDF or Document Intelligence; only text/code (TS, TSX, JS, JSX, CSS, JSON, MD, HTML).

Triggered by blob creation: user-content/_sessions/{upload_id}/_job.json
"""

import asyncio
import io
import json
import logging
import os
import zipfile

import azure.functions as func
from azure.identity.aio import ManagedIdentityCredential

from prepdocslib.blobmanager import AdlsBlobManager
from prepdocslib.filestrategy import UploadUserFileStrategy
from prepdocslib.listfilestrategy import File
from prepdocslib.servicesetup import (
    OpenAIHost,
    build_file_processors,
    setup_embeddings_service,
    setup_figure_processor,
    setup_image_embeddings_service,
    setup_openai_client,
    setup_search_info,
)

app = func.FunctionApp()

logger = logging.getLogger(__name__)

# Constants matching backend app.py
MAX_ZIP_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_ZIP_FILE_COUNT = 30000


def get_settings():
    """Lazy-init settings from env (same as backend)."""
    if hasattr(get_settings, "_settings"):
        return get_settings._settings

    AZURE_USERSTORAGE_ACCOUNT = os.environ.get("AZURE_USERSTORAGE_ACCOUNT")
    AZURE_USERSTORAGE_CONTAINER = os.environ.get("AZURE_USERSTORAGE_CONTAINER")
    AZURE_SEARCH_SERVICE = os.environ.get("AZURE_SEARCH_SERVICE")
    AZURE_SEARCH_INDEX = os.environ.get("AZURE_SEARCH_INDEX")
    AZURE_OPENAI_SERVICE = os.environ.get("AZURE_OPENAI_SERVICE")
    AZURE_OPENAI_CHATGPT_DEPLOYMENT = os.environ.get("AZURE_OPENAI_CHATGPT_DEPLOYMENT")
    AZURE_OPENAI_EMB_DEPLOYMENT = os.environ.get("AZURE_OPENAI_EMB_DEPLOYMENT")
    AZURE_OPENAI_EMB_MODEL = os.environ.get("AZURE_OPENAI_EMB_MODEL_NAME", "text-embedding-3-large")
    AZURE_OPENAI_EMB_DIMENSIONS = int(os.environ.get("AZURE_OPENAI_EMB_DIMENSIONS", "3072"))
    AZURE_SEARCH_FIELD_NAME_EMBEDDING = os.environ.get("AZURE_SEARCH_FIELD_NAME_EMBEDDING", "embedding")
    USE_MULTIMODAL = os.environ.get("USE_MULTIMODAL", "false").lower() == "true"
    USE_VECTORS = os.environ.get("USE_VECTORS", "true").lower() == "true"
    OPENAI_HOST = OpenAIHost(os.environ.get("OPENAI_HOST", "azure"))
    AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
    AZURE_VISION_ENDPOINT = os.environ.get("AZURE_VISION_ENDPOINT")

    if AZURE_CLIENT_ID := os.environ.get("AZURE_CLIENT_ID"):
        azure_credential = ManagedIdentityCredential(client_id=AZURE_CLIENT_ID)
    else:
        azure_credential = ManagedIdentityCredential()

    openai_client, azure_openai_endpoint = setup_openai_client(
        openai_host=OPENAI_HOST,
        azure_credential=azure_credential,
        azure_openai_service=AZURE_OPENAI_SERVICE,
        azure_openai_custom_url=os.environ.get("AZURE_OPENAI_CUSTOM_URL"),
        azure_openai_api_key=os.environ.get("AZURE_OPENAI_API_KEY_OVERRIDE"),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        openai_organization=os.environ.get("OPENAI_ORGANIZATION"),
    )

    user_blob_manager = AdlsBlobManager(
        endpoint=f"https://{AZURE_USERSTORAGE_ACCOUNT}.dfs.core.windows.net",
        container=AZURE_USERSTORAGE_CONTAINER,
        credential=azure_credential,
    )

    file_processors = build_file_processors(azure_credential=azure_credential)
    figure_processor = setup_figure_processor(
        credential=azure_credential,
        use_multimodal=USE_MULTIMODAL,
        use_content_understanding=os.environ.get("USE_CONTENT_UNDERSTANDING", "").lower() == "true",
        content_understanding_endpoint=os.environ.get("AZURE_CONTENTUNDERSTANDING_ENDPOINT"),
        openai_client=openai_client,
        openai_model=os.environ.get("AZURE_OPENAI_CHATGPT_MODEL"),
        openai_deployment=AZURE_OPENAI_CHATGPT_DEPLOYMENT if OPENAI_HOST == OpenAIHost.AZURE else None,
    )

    search_info = setup_search_info(
        search_service=AZURE_SEARCH_SERVICE,
        index_name=AZURE_SEARCH_INDEX,
        azure_credential=azure_credential,
        use_agentic_knowledgebase=os.environ.get("USE_AGENTIC_KNOWLEDGEBASE", "").lower() == "true",
        azure_openai_endpoint=azure_openai_endpoint,
        knowledgebase_name=os.environ.get("AZURE_SEARCH_KNOWLEDGEBASE_NAME"),
        azure_openai_knowledgebase_deployment=os.environ.get("AZURE_OPENAI_KNOWLEDGEBASE_DEPLOYMENT"),
        azure_openai_knowledgebase_model=os.environ.get("AZURE_OPENAI_KNOWLEDGEBASE_MODEL"),
    )

    text_embeddings_service = None
    if USE_VECTORS:
        text_embeddings_service = setup_embeddings_service(
            open_ai_client=openai_client,
            openai_host=OPENAI_HOST,
            emb_model_name=AZURE_OPENAI_EMB_MODEL,
            emb_model_dimensions=AZURE_OPENAI_EMB_DIMENSIONS,
            azure_openai_deployment=AZURE_OPENAI_EMB_DEPLOYMENT,
            azure_openai_endpoint=azure_openai_endpoint,
        )

    image_embeddings_service = setup_image_embeddings_service(
        azure_credential=azure_credential,
        vision_endpoint=AZURE_VISION_ENDPOINT,
        use_multimodal=USE_MULTIMODAL,
    )

    ingester = UploadUserFileStrategy(
        search_info=search_info,
        file_processors=file_processors,
        embeddings=text_embeddings_service,
        image_embeddings=image_embeddings_service,
        search_field_name_embedding=AZURE_SEARCH_FIELD_NAME_EMBEDDING,
        blob_manager=user_blob_manager,
        figure_processor=figure_processor,
    )

    get_settings._settings = {
        "adls_manager": user_blob_manager,
        "ingester": ingester,
    }
    return get_settings._settings


async def process_zip_job(upload_id: str, filename: str, user_oid: str) -> None:
    """Process zip: get chunks, extract, upload each file, index, delete session."""
    settings = get_settings()
    adls_manager: AdlsBlobManager = settings["adls_manager"]
    ingester: UploadUserFileStrategy = settings["ingester"]

    data = await adls_manager.get_session_chunks(upload_id)
    if not data:
        raise ValueError(f"No chunks found for session {upload_id}")

    if len(data) > MAX_ZIP_SIZE_BYTES:
        raise ValueError(f"Zip exceeds {MAX_ZIP_SIZE_BYTES // (1024*1024)} MB limit")

    zip_basename = filename.rsplit(".", 1)[0] if "." in filename else "archive"
    supported_extensions = set(ingester.file_processors.keys())

    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        members = [m for m in zf.namelist() if not m.endswith("/")]
        if len(members) > MAX_ZIP_FILE_COUNT:
            raise ValueError(f"Zip contains too many files (max {MAX_ZIP_FILE_COUNT})")

        to_process = [
            (name, rel_path, flattened)
            for name in members
            for rel_path in [name.replace("\\", "/").lstrip("/")]
            for ext in [os.path.splitext(rel_path)[1].lower()]
            if ext in supported_extensions
            for flattened in [f"{zip_basename}__{rel_path.replace('/', '__')}"]
        ]
        files_total = len(to_process)
        indexed_ids: list[str] = []
        files_done = 0

        await adls_manager.upload_session_progress(
            upload_id=upload_id,
            status="processing",
            files_total=files_total,
            files_done=0,
            indexed_ids=[],
            user_oid=user_oid,
        )

        for name, rel_path, flattened in to_process:
            try:
                raw = zf.read(name)
                content = io.BytesIO(raw)
                content.name = flattened  # blob/key and stable id
                file_url = await adls_manager.upload_blob(content, flattened, user_oid)
                content.seek(0)
                # Preserve folder structure in index (source_path → filepath in search)
                await ingester.add_file(
                    File(
                        content=content,
                        url=file_url,
                        acls={"oids": [user_oid]},
                        source_path=rel_path,
                    ),
                    user_oid=user_oid,
                )
                indexed_ids.append(flattened)
                files_done += 1
                await adls_manager.upload_session_progress(
                    upload_id=upload_id,
                    status="processing",
                    files_total=files_total,
                    files_done=files_done,
                    indexed_ids=indexed_ids,
                    user_oid=user_oid,
                )
                logger.info("Indexed %s (%d/%d)", rel_path, files_done, files_total)
            except Exception as e:
                logger.exception("Error processing %s from zip: %s", rel_path, e)

        await adls_manager.upload_session_progress(
            upload_id=upload_id,
            status="completed",
            files_total=files_total,
            files_done=files_done,
            indexed_ids=indexed_ids,
            user_oid=user_oid,
        )

    await adls_manager.delete_session(upload_id, keep_progress=True)


# Blob path: user-content/_sessions/{upload_id}/_job.json (container = AZURE_USERSTORAGE_CONTAINER, default user-content)
@app.blob_trigger(
    arg_name="blob",
    path="user-content/_sessions/{name}/_job.json",
    connection="UserStorage",
)
def zip_processor(blob: func.InputStream) -> None:
    """Triggered when _job.json is written; processes the zip asynchronously."""
    # blob.name is e.g. "user-content/_sessions/{upload_id}/_job.json" or "_sessions/{upload_id}/_job.json"
    parts = blob.name.replace("\\", "/").strip("/").split("/")
    upload_id = parts[-2] if len(parts) >= 2 else (parts[0] if parts else "unknown")
    try:
        job = json.loads(blob.read().decode("utf-8"))
    except Exception as e:
        logger.exception("Invalid _job.json for %s: %s", upload_id, e)
        return

    filename = job.get("filename")
    user_oid = job.get("user_oid")
    if not filename or not user_oid:
        logger.error("Missing filename or user_oid in _job.json for %s", upload_id)
        return

    logger.info("Processing zip job %s for user %s", upload_id, user_oid)

    try:
        asyncio.run(process_zip_job(upload_id, filename, user_oid))
        logger.info("Completed zip job %s", upload_id)
    except Exception as e:
        logger.exception("Failed zip job %s: %s", upload_id, e)
        raise
