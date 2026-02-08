import React, { useState, ChangeEvent, useRef, useEffect } from "react";
import { Callout, Label, Text } from "@fluentui/react";
import { Button } from "@fluentui/react-components";
import { Add24Regular, Delete24Regular } from "@fluentui/react-icons";
import { useMsal } from "@azure/msal-react";
import { useTranslation } from "react-i18next";

import {
    SimpleAPIResponse,
    uploadFileApi,
    UploadZipResponse,
    UploadZipStatusResponse,
    deleteUploadedFileApi,
    listUploadedFilesApi,
    uploadZipInitApi,
    uploadZipChunkApi,
    uploadZipCompleteApi,
    uploadZipStatusApi,
    ZIP_CHUNK_SIZE
} from "../../api";
import { useLogin, getToken } from "../../authConfig";
import styles from "./UploadFile.module.css";

interface Props {
    className?: string;
    disabled?: boolean;
}

export const UploadFile: React.FC<Props> = ({ className, disabled }: Props) => {
    // State variables to manage the component behavior
    const [isCalloutVisible, setIsCalloutVisible] = useState<boolean>(false);
    const [isUploading, setIsUploading] = useState<boolean>(false);
    const [isLoading, setIsLoading] = useState<boolean>(true);
    const [deletionStatus, setDeletionStatus] = useState<{ [filename: string]: "pending" | "error" | "success" }>({});
    const [uploadedFile, setUploadedFile] = useState<SimpleAPIResponse>();
    const [uploadedFileError, setUploadedFileError] = useState<string>();
    const [uploadedZipResult, setUploadedZipResult] = useState<UploadZipResponse | null>(null);
    const [uploadedZipError, setUploadedZipError] = useState<string>();
    const [isUploadingZip, setIsUploadingZip] = useState<boolean>(false);
    const [uploadZipProgress, setUploadZipProgress] = useState<string | null>(null);
    const [uploadZipStatus, setUploadZipStatus] = useState<UploadZipStatusResponse | null>(null);
    const [uploadedFiles, setUploadedFiles] = useState<string[]>([]);
    const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const { t } = useTranslation();

    useEffect(() => {
        return () => {
            if (pollTimeoutRef.current) {
                clearTimeout(pollTimeoutRef.current);
            }
        };
    }, []);

    if (!useLogin) {
        throw new Error("The UploadFile component requires useLogin to be true");
    }

    const client = useMsal().instance;

    // Handler for the "Manage file uploads" button
    const handleButtonClick = async () => {
        setIsCalloutVisible(!isCalloutVisible); // Toggle the Callout visibility

        // Update uploaded files by calling the API
        try {
            const idToken = await getToken(client);
            if (!idToken) {
                throw new Error("No authentication token available");
            }
            listUploadedFiles(idToken);
        } catch (error) {
            console.error(error);
            setIsLoading(false);
        }
    };

    const listUploadedFiles = async (idToken: string) => {
        listUploadedFilesApi(idToken).then(files => {
            setIsLoading(false);
            setDeletionStatus({});
            setUploadedFiles(files);
        });
    };

    const handleRemoveFile = async (filename: string) => {
        setDeletionStatus({ ...deletionStatus, [filename]: "pending" });

        try {
            const idToken = await getToken(client);
            if (!idToken) {
                throw new Error("No authentication token available");
            }

            await deleteUploadedFileApi(filename, idToken);
            setDeletionStatus({ ...deletionStatus, [filename]: "success" });
            listUploadedFiles(idToken);
        } catch (error) {
            setDeletionStatus({ ...deletionStatus, [filename]: "error" });
            console.error(error);
        }
    };

    // Handler for the form submission (file upload)
    const handleUploadFile = async (e: ChangeEvent<HTMLInputElement>) => {
        e.preventDefault();
        if (!e.target.files || e.target.files.length === 0) {
            return;
        }
        setIsUploading(true); // Start the loading state
        const file: File = e.target.files[0];
        const formData = new FormData();
        formData.append("file", file);

        try {
            const idToken = await getToken(client);
            if (!idToken) {
                throw new Error("No authentication token available");
            }
            const response: SimpleAPIResponse = await uploadFileApi(formData, idToken);
            setUploadedFile(response);
            setIsUploading(false);
            setUploadedFileError(undefined);
            listUploadedFiles(idToken);
        } catch (error) {
            console.error(error);
            setIsUploading(false);
            setUploadedFileError(t("upload.uploadedFileError"));
        }
    };

    const handleUploadZip = async (e: ChangeEvent<HTMLInputElement>) => {
        e.preventDefault();
        if (!e.target.files || e.target.files.length === 0) return;
        const file = e.target.files[0];
        if (!file.name.toLowerCase().endsWith(".zip")) {
            setUploadedZipError(t("upload.zipOnly"));
            return;
        }
        setIsUploadingZip(true);
        setUploadedZipError(undefined);
        setUploadedZipResult(null);
        setUploadZipProgress(null);
        try {
            const idToken = await getToken(client);
            if (!idToken) throw new Error("No authentication token available");

            const totalChunks = Math.ceil(file.size / ZIP_CHUNK_SIZE);
            const { upload_id } = await uploadZipInitApi(idToken);

            for (let i = 0; i < totalChunks; i++) {
                setUploadZipProgress(t("upload.uploadingZipChunk", { current: i + 1, total: totalChunks }));
                const start = i * ZIP_CHUNK_SIZE;
                const end = Math.min(start + ZIP_CHUNK_SIZE, file.size);
                const chunkBlob = file.slice(start, end);
                await uploadZipChunkApi(upload_id, i, totalChunks, file.name, chunkBlob, idToken);
            }

            setUploadZipProgress(t("upload.processingZip"));
            const result = await uploadZipCompleteApi(upload_id, file.name, idToken);
            setUploadedZipResult(result);
            setUploadZipStatus(null);

            const jobId = result.jobId ?? upload_id;
            const pollIntervalMs = 2000;
            const maxPollMinutes = 15;
            const maxPolls = (maxPollMinutes * 60 * 1000) / pollIntervalMs;
            let pollCount = 0;

            const pollStatus = async () => {
                if (pollCount >= maxPolls) {
                    setIsUploadingZip(false);
                    setUploadZipProgress(null);
                    setUploadZipStatus(null);
                    listUploadedFiles(idToken);
                    return;
                }
                try {
                    const status = await uploadZipStatusApi(jobId, idToken);
                    setUploadZipStatus(status);
                    if (status.status === "completed") {
                        setIsUploadingZip(false);
                        setUploadZipProgress(null);
                        setUploadZipStatus(null);
                        listUploadedFiles(idToken);
                        return;
                    }
                    pollCount++;
                    pollTimeoutRef.current = setTimeout(pollStatus, pollIntervalMs);
                } catch {
                    pollCount++;
                    pollTimeoutRef.current = setTimeout(pollStatus, pollIntervalMs);
                }
            };
            pollTimeoutRef.current = setTimeout(pollStatus, pollIntervalMs);
        } catch (error) {
            console.error(error);
            setUploadedZipError(t("upload.uploadedFileError"));
            setIsUploadingZip(false);
            setUploadZipProgress(null);
            setUploadZipStatus(null);
        }
        e.target.value = "";
    };

    return (
        <div className={`${styles.container} ${className ?? ""}`}>
            <div>
                <Button id="calloutButton" icon={<Add24Regular />} disabled={disabled} onClick={handleButtonClick}>
                    {t("upload.manageFileUploads")}
                </Button>

                {isCalloutVisible && (
                    <Callout
                        role="dialog"
                        gapSpace={0}
                        className={styles.callout}
                        target="#calloutButton"
                        onDismiss={() => setIsCalloutVisible(false)}
                        setInitialFocus
                    >
                        <form encType="multipart/form-data">
                            <div>
                                <Label>{t("upload.fileLabel")}</Label>
                                <input
                                    accept=".txt, .md, .json, .png, .jpg, .jpeg, .bmp, .heic, .tiff, .pdf, .docx, .xlsx, .pptx, .html, .ts, .tsx, .js, .jsx"
                                    className={styles.chooseFiles}
                                    type="file"
                                    onChange={handleUploadFile}
                                />
                            </div>
                            <div style={{ marginTop: "1em" }}>
                                <Label>{t("upload.zipLabel")}</Label>
                                <input
                                    accept=".zip"
                                    className={styles.chooseFiles}
                                    type="file"
                                    onChange={handleUploadZip}
                                />
                                {(isUploadingZip && uploadZipProgress) && <Text>{uploadZipProgress}</Text>}
                                {isUploadingZip && uploadZipStatus && (
                                    <Text block>
                                        {uploadZipStatus.status === "queued" && uploadZipStatus.message && (
                                            <span>{uploadZipStatus.message}</span>
                                        )}
                                        {uploadZipStatus.status === "processing" && (
                                            <>
                                                {uploadZipStatus.pct_completion != null && (
                                                    <span>{uploadZipStatus.pct_completion}% complete</span>
                                                )}
                                                {uploadZipStatus.files_done != null && uploadZipStatus.files_total != null && (
                                                    <span> ({uploadZipStatus.files_done}/{uploadZipStatus.files_total} files)</span>
                                                )}
                                                {uploadZipStatus.pct_indexing != null && (
                                                    <span> · {uploadZipStatus.pct_indexing}% indexed</span>
                                                )}
                                                {uploadZipStatus.indexed_ids && uploadZipStatus.indexed_ids.length > 0 && (
                                                    <div style={{ marginTop: "4px", fontSize: "12px", maxHeight: "80px", overflow: "auto" }}>
                                                        Index IDs: {uploadZipStatus.indexed_ids.slice(-10).join(", ")}
                                                        {uploadZipStatus.indexed_ids.length > 10 && ` (+${uploadZipStatus.indexed_ids.length - 10} more)`}
                                                    </div>
                                                )}
                                            </>
                                        )}
                                    </Text>
                                )}
                                {uploadedZipError && <Text>{uploadedZipError}</Text>}
                                {uploadedZipResult && !isUploadingZip && (
                                    <Text>
                                        {uploadedZipResult.message}
                                        {uploadedZipResult.indexed?.length ? ` (${uploadedZipResult.indexed.length} indexed)` : ""}
                                    </Text>
                                )}
                            </div>
                        </form>

                        {/* Show a loading message while files are being uploaded */}
                        {isUploading && <Text>{t("upload.uploadingFiles")}</Text>}
                        {!isUploading && uploadedFileError && <Text>{uploadedFileError}</Text>}
                        {!isUploading && uploadedFile && <Text>{uploadedFile.message}</Text>}

                        {/* Display the list of already uploaded */}
                        <h3>{t("upload.uploadedFilesLabel")}</h3>

                        {isLoading && <Text>{t("upload.loading")}</Text>}
                        {!isLoading && uploadedFiles.length === 0 && <Text>{t("upload.noFilesUploaded")}</Text>}
                        {uploadedFiles.map((filename, index) => {
                            return (
                                <div key={index} className={styles.list}>
                                    <div className={styles.item}>{filename}</div>
                                    {/* Button to remove a file from the list */}
                                    <Button
                                        icon={<Delete24Regular />}
                                        onClick={() => handleRemoveFile(filename)}
                                        disabled={deletionStatus[filename] === "pending" || deletionStatus[filename] === "success"}
                                    >
                                        {!deletionStatus[filename] && t("upload.deleteFile")}
                                        {deletionStatus[filename] == "pending" && t("upload.deletingFile")}
                                        {deletionStatus[filename] == "error" && t("upload.errorDeleting")}
                                        {deletionStatus[filename] == "success" && t("upload.fileDeleted")}
                                    </Button>
                                </div>
                            );
                        })}
                    </Callout>
                )}
            </div>
        </div>
    );
};
