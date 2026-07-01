import { apiFetch } from "./api";

export interface DocumentStatus {
  id: string;
  filename: string;
  status: string;
  chunk_counts: Record<string, number>;
  metadata: Record<string, unknown>;
}

export interface DocumentUploadResult {
  id: string;
  filename: string;
  status: string;
  message: string;
  chunk_counts: Record<string, number>;
}

export interface DocumentListResult {
  documents: DocumentStatus[];
}

export async function uploadDocument(file: File): Promise<DocumentStatus> {
  const form = new FormData();
  form.append("file", file);

  const response = await apiFetch("/api/documents", {
    method: "POST",
    body: form,
  });

  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || `文档上传失败：${response.status}`);
  }

  const uploaded = (await response.json()) as DocumentUploadResult;
  return getDocumentStatus(uploaded.id);
}

export async function listDocuments(): Promise<DocumentStatus[]> {
  const response = await apiFetch("/api/documents");
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || `文档列表查询失败：${response.status}`);
  }
  const payload = (await response.json()) as DocumentListResult;
  return payload.documents;
}

export async function getDocumentStatus(documentId: string): Promise<DocumentStatus> {
  const response = await apiFetch(`/api/documents/${documentId}`);
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || `文档状态查询失败：${response.status}`);
  }
  return (await response.json()) as DocumentStatus;
}

export async function deleteDocument(documentId: string): Promise<void> {
  const response = await apiFetch(`/api/documents/${documentId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || `文档删除失败：${response.status}`);
  }
}

export async function retryDocument(documentId: string): Promise<DocumentStatus> {
  const response = await apiFetch(`/api/documents/${documentId}/retry`, {
    method: "POST",
  });
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || `文档重试失败：${response.status}`);
  }
  return (await response.json()) as DocumentStatus;
}

async function readErrorDetail(response: Response): Promise<string | null> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    return typeof payload.detail === "string" ? payload.detail : null;
  } catch {
    return null;
  }
}
