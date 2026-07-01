import { apiFetch } from "./api";

export interface ProviderCheck {
  name: string;
  provider: string;
  configured: boolean;
  status: string;
  message: string;
}

export interface ProviderStatus {
  overall: string;
  live: boolean;
  providers: Record<"embedding" | "llm" | "rerank", ProviderCheck>;
}

export async function getProviderStatus(live = false): Promise<ProviderStatus> {
  const response = await apiFetch(`/api/providers/status?live=${String(live)}`);
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || `Provider 状态查询失败：${response.status}`);
  }
  return (await response.json()) as ProviderStatus;
}

async function readErrorDetail(response: Response): Promise<string | null> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    return typeof payload.detail === "string" ? payload.detail : null;
  } catch {
    return null;
  }
}
