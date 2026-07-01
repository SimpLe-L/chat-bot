import type { ChatStreamEvent } from "@nebulai/shared";
import { API_BASE_URL } from "./api";

export interface StreamChatInput {
  message: string;
  sessionId?: string;
  signal?: AbortSignal;
  onEvent: (event: ChatStreamEvent) => void;
}

export async function streamChat(input: StreamChatInput): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      session_id: input.sessionId,
      message: input.message,
      options: {
        show_steps: true,
      },
    }),
    signal: input.signal,
    credentials: "include",
  });

  if (!response.ok || !response.body) {
    throw new Error(`问答接口请求失败：${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const event = parseSseFrame(frame);
      if (event) {
        input.onEvent(event);
      }
    }
  }
}

export async function cancelChatRun(runId: string): Promise<void> {
  await fetch(`${API_BASE_URL}/api/chat/runs/${runId}/cancel`, {
    method: "POST",
    credentials: "include",
  });
}

function parseSseFrame(frame: string): ChatStreamEvent | null {
  const dataLine = frame
    .split("\n")
    .find((line) => line.startsWith("data:"));

  if (!dataLine) {
    return null;
  }

  return JSON.parse(dataLine.slice(5).trim()) as ChatStreamEvent;
}
