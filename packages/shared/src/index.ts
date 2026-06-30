export type ChatRole = "user" | "assistant" | "system";

export type RagStepKind =
  | "question_analysis"
  | "rewrite"
  | "retrieval"
  | "rerank"
  | "synthesis"
  | "fallback";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
}

export interface RagSource {
  id: string;
  documentId?: string;
  documentTitle: string;
  chunkId: string;
  parentId?: string;
  excerpt: string;
  context?: string;
  contextChunkId?: string;
  contextLevel?: string;
  score?: number;
  rerankScore?: number;
}

export interface RagStep {
  id: string;
  kind: RagStepKind;
  title: string;
  detail: string;
  status: "pending" | "running" | "completed" | "warning" | "error";
  score?: number;
  createdAt: string;
}

export type ChatStreamEvent =
  | { type: "accepted"; runId: string; sessionId: string }
  | { type: "step"; step: RagStep }
  | { type: "source"; source: RagSource }
  | { type: "token"; token: string }
  | { type: "warning"; message: string }
  | { type: "error"; message: string }
  | { type: "done"; runId: string };
