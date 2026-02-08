const BACKEND_URI = "";

import { ChatAppResponse, ChatAppResponseOrError, ChatAppRequest, Config, SimpleAPIResponse, HistoryListApiResponse, HistoryApiResponse } from "./models";
import { useLogin, getToken, isUsingAppServicesLogin } from "../authConfig";

export async function getHeaders(idToken: string | undefined): Promise<Record<string, string>> {
    // If using login and not using app services, add the id token of the logged in account as the authorization
    if (useLogin && !isUsingAppServicesLogin) {
        if (idToken) {
            return { Authorization: `Bearer ${idToken}` };
        }
    }

    return {};
}

export async function configApi(): Promise<Config> {
    const response = await fetch(`${BACKEND_URI}/config`, {
        method: "GET"
    });

    return (await response.json()) as Config;
}

export async function chatApi(request: ChatAppRequest, shouldStream: boolean, idToken: string | undefined, signal: AbortSignal): Promise<Response> {
    let url = `${BACKEND_URI}/chat`;
    if (shouldStream) {
        url += "/stream";
    }
    const headers = await getHeaders(idToken);
    return await fetch(url, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(request),
        signal: signal
    });
}

export async function getSpeechApi(text: string): Promise<string | null> {
    return await fetch("/speech", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            text: text
        })
    })
        .then(response => {
            if (response.status == 200) {
                return response.blob();
            } else if (response.status == 400) {
                console.log("Speech synthesis is not enabled.");
                return null;
            } else {
                console.error("Unable to get speech synthesis.");
                return null;
            }
        })
        .then(blob => (blob ? URL.createObjectURL(blob) : null));
}

export function getCitationFilePath(citation: string): string {
    // If there are parentheses at end of citation, remove part in parentheses
    const cleanedCitation = citation.replace(/\s*\(.*?\)\s*$/, "").trim();
    return `${BACKEND_URI}/content/${cleanedCitation}`;
}

export async function uploadFileApi(request: FormData, idToken: string): Promise<SimpleAPIResponse> {
    const response = await fetch("/upload", {
        method: "POST",
        headers: await getHeaders(idToken),
        body: request
    });

    if (!response.ok) {
        throw new Error(`Uploading files failed: ${response.statusText}`);
    }

    const dataResponse: SimpleAPIResponse = await response.json();
    return dataResponse;
}

export type UploadZipResponse = {
    message: string;
    jobId?: string;
    indexed?: string[];
    skipped?: string[];
    errors?: Array<{ file: string; error: string }>;
    status?: string;
};

export type UploadZipStatusResponse = {
    status: string;
    message?: string;
    files_total?: number;
    files_done?: number;
    pct_completion?: number;
    pct_indexing?: number;
    indexed_ids?: string[];
};

/** Chunk size for zip upload (4 MB) - avoids 413 from proxies */
export const ZIP_CHUNK_SIZE = 4 * 1024 * 1024;

export async function uploadZipApi(request: FormData, idToken: string): Promise<UploadZipResponse> {
    const response = await fetch("/upload-zip", {
        method: "POST",
        headers: await getHeaders(idToken),
        body: request
    });

    const data: UploadZipResponse = await response.json();
    if (!response.ok) {
        throw new Error(data.message || "Uploading zip failed");
    }
    return data;
}

/** Initialize a chunked zip upload; returns upload_id. */
export async function uploadZipInitApi(idToken: string): Promise<{ upload_id: string }> {
    const headers = await getHeaders(idToken);
    const response = await fetch("/upload-zip-init", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" }
    });
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.message || "Failed to init zip upload");
    }
    return data;
}

/** Upload a single chunk of a zip file. */
export async function uploadZipChunkApi(
    uploadId: string,
    chunkIndex: number,
    totalChunks: number,
    filename: string,
    chunkBlob: Blob,
    idToken: string
): Promise<void> {
    const headers = await getHeaders(idToken);
    const response = await fetch("/upload-zip-chunk", {
        method: "POST",
        headers: {
            ...headers,
            "Content-Type": "application/octet-stream",
            "X-Upload-Id": uploadId,
            "X-Chunk-Index": String(chunkIndex),
            "X-Total-Chunks": String(totalChunks),
            "X-Filename": filename
        },
        body: chunkBlob
    });
    const text = await response.text();
    let data: { message?: string };
    try {
        data = text ? JSON.parse(text) : {};
    } catch {
        data = {};
    }
    if (!response.ok) {
        throw new Error(data.message || `Failed to upload chunk ${chunkIndex} (${response.status})`);
    }
}

/** Complete chunked zip upload and process. */
export async function uploadZipCompleteApi(
    uploadId: string,
    filename: string,
    idToken: string
): Promise<UploadZipResponse> {
    const headers = await getHeaders(idToken);
    const response = await fetch("/upload-zip-complete", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ upload_id: uploadId, filename })
    });
    const text = await response.text();
    let data: UploadZipResponse;
    try {
        data = text ? (JSON.parse(text) as UploadZipResponse) : { message: "Processing started." };
    } catch {
        throw new Error(
            response.ok ? "Invalid response from server" : `Upload failed: ${response.status} ${response.statusText}`
        );
    }
    if (!response.ok) {
        throw new Error(data.message || `Failed to complete zip upload (${response.status})`);
    }
    return data;
}

/** Poll status of async zip processing job. */
export async function uploadZipStatusApi(
    uploadId: string,
    idToken: string
): Promise<UploadZipStatusResponse> {
    const headers = await getHeaders(idToken);
    const response = await fetch(`/upload-zip-status?upload_id=${encodeURIComponent(uploadId)}`, {
        method: "GET",
        headers
    });
    const data = (await response.json()) as UploadZipStatusResponse;
    if (!response.ok) {
        throw new Error("error" in data ? String(data.error) : "Failed to get status");
    }
    return data;
}

export async function deleteUploadedFileApi(filename: string, idToken: string): Promise<SimpleAPIResponse> {
    const headers = await getHeaders(idToken);
    const response = await fetch("/delete_uploaded", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ filename })
    });

    if (!response.ok) {
        throw new Error(`Deleting file failed: ${response.statusText}`);
    }

    const dataResponse: SimpleAPIResponse = await response.json();
    return dataResponse;
}

export async function listUploadedFilesApi(idToken: string): Promise<string[]> {
    const response = await fetch(`/list_uploaded`, {
        method: "GET",
        headers: await getHeaders(idToken)
    });

    if (!response.ok) {
        throw new Error(`Listing files failed: ${response.statusText}`);
    }

    const dataResponse: string[] = await response.json();
    return dataResponse;
}

export async function postChatHistoryApi(item: any, idToken: string): Promise<any> {
    const headers = await getHeaders(idToken);
    const response = await fetch("/chat_history", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(item)
    });

    if (!response.ok) {
        throw new Error(`Posting chat history failed: ${response.statusText}`);
    }

    const dataResponse: any = await response.json();
    return dataResponse;
}

export async function getChatHistoryListApi(count: number, continuationToken: string | undefined, idToken: string): Promise<HistoryListApiResponse> {
    const headers = await getHeaders(idToken);
    let url = `${BACKEND_URI}/chat_history/sessions?count=${count}`;
    if (continuationToken) {
        url += `&continuationToken=${continuationToken}`;
    }

    const response = await fetch(url.toString(), {
        method: "GET",
        headers: { ...headers, "Content-Type": "application/json" }
    });

    if (!response.ok) {
        throw new Error(`Getting chat histories failed: ${response.statusText}`);
    }

    const dataResponse: HistoryListApiResponse = await response.json();
    return dataResponse;
}

export async function getChatHistoryApi(id: string, idToken: string): Promise<HistoryApiResponse> {
    const headers = await getHeaders(idToken);
    const response = await fetch(`/chat_history/sessions/${id}`, {
        method: "GET",
        headers: { ...headers, "Content-Type": "application/json" }
    });

    if (!response.ok) {
        throw new Error(`Getting chat history failed: ${response.statusText}`);
    }

    const dataResponse: HistoryApiResponse = await response.json();
    return dataResponse;
}

export async function deleteChatHistoryApi(id: string, idToken: string): Promise<any> {
    const headers = await getHeaders(idToken);
    const response = await fetch(`/chat_history/sessions/${id}`, {
        method: "DELETE",
        headers: { ...headers, "Content-Type": "application/json" }
    });

    if (!response.ok) {
        throw new Error(`Deleting chat history failed: ${response.statusText}`);
    }
}
