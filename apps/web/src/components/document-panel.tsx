import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, FileUp, Loader2, RefreshCw, RotateCcw, Trash2, Upload } from "lucide-react";

import {
  deleteDocument,
  getDocumentStatus,
  listDocuments,
  retryDocument,
  uploadDocument,
  type DocumentStatus,
} from "../lib/documents";

interface DocumentPanelProps {
  onError: (message: string) => void;
}

export function DocumentPanel({ onError }: DocumentPanelProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [documents, setDocuments] = useState<DocumentStatus[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    listDocuments()
      .then((items) => {
        if (!cancelled) {
          setDocuments(items);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          onError(err instanceof Error ? err.message : "文档列表查询失败");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [onError]);

  useEffect(() => {
    const processingIds = documents
      .filter((document) => document.status === "processing")
      .map((document) => document.id);
    if (processingIds.length === 0) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      void Promise.all(
        processingIds.map(async (documentId) => {
          const status = await getDocumentStatus(documentId);
          setDocuments((items) => items.map((item) => (item.id === documentId ? status : item)));
        }),
      ).catch((err) => {
        onError(err instanceof Error ? err.message : "文档状态刷新失败");
      });
    }, 2500);

    return () => window.clearInterval(timer);
  }, [documents, onError]);

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) {
      return;
    }

    setIsUploading(true);
    try {
      const status = await uploadDocument(file);
      setDocuments((items) => [status, ...items.filter((item) => item.id !== status.id)]);
    } catch (err) {
      onError(err instanceof Error ? err.message : "文档上传失败");
    } finally {
      setIsUploading(false);
    }
  };

  const refreshDocument = async (documentId: string) => {
    setRefreshingId(documentId);
    try {
      const status = await getDocumentStatus(documentId);
      setDocuments((items) => items.map((item) => (item.id === documentId ? status : item)));
    } catch (err) {
      onError(err instanceof Error ? err.message : "文档状态查询失败");
    } finally {
      setRefreshingId(null);
    }
  };

  const removeDocument = async (documentId: string) => {
    if (!window.confirm("删除该文档及其向量索引？")) {
      return;
    }
    setDeletingId(documentId);
    try {
      await deleteDocument(documentId);
      setDocuments((items) => items.filter((item) => item.id !== documentId));
    } catch (err) {
      onError(err instanceof Error ? err.message : "文档删除失败");
    } finally {
      setDeletingId(null);
    }
  };

  const retryIndexing = async (documentId: string) => {
    setRetryingId(documentId);
    try {
      const status = await retryDocument(documentId);
      setDocuments((items) => items.map((item) => (item.id === documentId ? status : item)));
    } catch (err) {
      onError(err instanceof Error ? err.message : "文档重试失败");
    } finally {
      setRetryingId(null);
    }
  };

  return (
    <section className="mb-6 border-b border-line pb-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <FileUp size={17} />
          <h2 className="text-sm font-semibold uppercase text-ink/70">Knowledge</h2>
        </div>
        <button
          className="grid size-8 place-items-center rounded-md border border-line bg-white text-ink transition hover:border-ink/25 disabled:cursor-not-allowed disabled:text-ink/35"
          disabled={isUploading}
          onClick={() => inputRef.current?.click()}
          title="上传文档"
          type="button"
        >
          {isUploading ? <Loader2 className="animate-spin" size={15} /> : <Upload size={15} />}
        </button>
      </div>

      <input
        accept=".txt,.md,.markdown,.pdf,.docx,.csv,.xlsx,text/plain,text/markdown,text/csv,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        className="hidden"
        onChange={handleFileChange}
        ref={inputRef}
        type="file"
      />

      {isLoading ? (
        <div className="flex items-center gap-2 rounded-md border border-line bg-white px-3 py-4 text-xs text-ink/55">
          <Loader2 className="animate-spin" size={14} />
          正在读取文档列表
        </div>
      ) : documents.length === 0 ? (
        <button
          className="w-full rounded-md border border-dashed border-line bg-white px-3 py-4 text-left text-xs leading-5 text-ink/55 transition hover:border-ink/25"
          disabled={isUploading}
          onClick={() => inputRef.current?.click()}
          type="button"
        >
          上传 txt、md、docx、pdf、csv 或 xlsx 后，这里会显示分块、embedding 和向量写入状态。
        </button>
      ) : (
        <div className="space-y-3">
          {documents.map((document) => (
            <article className="rounded-md border border-line bg-white p-3" key={document.id}>
              <div className="mb-2 flex items-start gap-2">
                <StatusIcon status={document.status} />
                <div className="min-w-0 flex-1">
                  <h3 className="truncate text-sm font-semibold">{document.filename}</h3>
                  <p className="text-[11px] uppercase text-ink/35">{document.status}</p>
                </div>
                <button
                  className="grid size-7 place-items-center rounded-md border border-line text-ink/60 transition hover:border-ink/25 disabled:text-ink/30"
                  disabled={refreshingId === document.id || retryingId === document.id || deletingId === document.id}
                  onClick={() => void refreshDocument(document.id)}
                  title="刷新状态"
                  type="button"
                >
                  <RefreshCw className={refreshingId === document.id ? "animate-spin" : ""} size={13} />
                </button>
                <button
                  className="grid size-7 place-items-center rounded-md border border-line text-ink/60 transition hover:border-ink/25 disabled:text-ink/30"
                  disabled={retryingId === document.id || deletingId === document.id}
                  onClick={() => void retryIndexing(document.id)}
                  title="重试向量索引"
                  type="button"
                >
                  {retryingId === document.id ? <Loader2 className="animate-spin" size={13} /> : <RotateCcw size={13} />}
                </button>
                <button
                  className="grid size-7 place-items-center rounded-md border border-line text-ink/60 transition hover:border-[#B76E64] hover:text-[#B76E64] disabled:text-ink/30"
                  disabled={deletingId === document.id}
                  onClick={() => void removeDocument(document.id)}
                  title="删除文档"
                  type="button"
                >
                  {deletingId === document.id ? <Loader2 className="animate-spin" size={13} /> : <Trash2 size={13} />}
                </button>
              </div>

              <dl className="grid grid-cols-3 gap-2 text-center text-[11px]">
                <Metric label="L1" value={document.chunk_counts.L1 ?? 0} />
                <Metric label="L2" value={document.chunk_counts.L2 ?? 0} />
                <Metric label="L3" value={document.chunk_counts.L3 ?? 0} />
              </dl>

              <div className="mt-3 space-y-1 text-[11px] leading-4 text-ink/55">
                <JobProgress metadata={document.metadata} />
                <StatusLine label="job" value={String(document.metadata.ingestion_job_status ?? "-")} />
                <StatusLine label="embedding" value={String(document.metadata.embedding_status ?? "-")} />
                <StatusLine label="vector" value={String(document.metadata.vector_status ?? "-")} />
                <StatusLine label="provider" value={String(document.metadata.embedding_provider ?? "-")} />
                <DegradedReason metadata={document.metadata} />
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-[#F3F5F0] px-2 py-1">
      <dt className="text-ink/40">{label}</dt>
      <dd className="font-semibold text-ink">{value}</dd>
    </div>
  );
}

function StatusLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-ink/40">{label}</span>
      <span className="truncate font-medium text-ink/65">{value}</span>
    </div>
  );
}

function DegradedReason({ metadata }: { metadata: Record<string, unknown> }) {
  const embeddingStatus = String(metadata.embedding_status ?? "");
  const vectorStatus = String(metadata.vector_status ?? "");
  if (embeddingStatus !== "degraded" && vectorStatus !== "degraded") {
    return null;
  }

  const reason = String(metadata.vector_message ?? metadata.embedding_message ?? "向量索引降级，查看后端日志获取详情。");
  return (
    <div className="mt-2 rounded-md border border-[#E7B68C] bg-[#FFF7ED] px-2.5 py-2 text-[11px] leading-4 text-[#7A3C12]">
      <p className="font-semibold">索引降级原因</p>
      <p className="mt-1 break-words">{reason}</p>
    </div>
  );
}

function JobProgress({ metadata }: { metadata: Record<string, unknown> }) {
  const rawProgress = Number(metadata.ingestion_progress ?? 0);
  const progress = Number.isFinite(rawProgress) ? Math.max(0, Math.min(rawProgress, 100)) : 0;
  return (
    <div className="mb-2">
      <div className="h-1.5 overflow-hidden rounded-full bg-[#E5E9E2]">
        <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${progress}%` }} />
      </div>
    </div>
  );
}

function StatusIcon({ status }: { status: string }) {
  if (status === "completed") {
    return <CheckCircle2 className="mt-0.5 shrink-0 text-accent" size={16} />;
  }
  return <AlertTriangle className="mt-0.5 shrink-0 text-warn" size={16} />;
}
