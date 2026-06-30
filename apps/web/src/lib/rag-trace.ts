import type { Source, Step } from "./types";

interface RunSummary {
  id: string;
  session_id: string;
  question: string;
  status: string;
  mode: string;
  created_at: string;
  finished_at: string | null;
}

interface RunTrace {
  run: RunSummary;
  steps: Step[];
  sources: Source[];
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function loadLatestTrace(sessionId: string): Promise<RunTrace | null> {
  const runsResponse = await fetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}/runs`);
  if (!runsResponse.ok) {
    return null;
  }
  const runsPayload = (await runsResponse.json()) as { runs: RunSummary[] };
  const latestRun = runsPayload.runs[0];
  if (!latestRun) {
    return null;
  }

  const traceResponse = await fetch(`${API_BASE_URL}/api/chat/runs/${latestRun.id}/trace`);
  if (!traceResponse.ok) {
    return null;
  }
  return (await traceResponse.json()) as RunTrace;
}
