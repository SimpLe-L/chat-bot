import type { AppendMessage, ThreadMessageLike } from "@assistant-ui/react";

import type { Message } from "./types";

export const assistantUiIntegration = {
  packageName: "@assistant-ui/react",
  strategy: "external-store-runtime",
  status: "runtime-mounted",
} as const;

export function toAssistantUiMessages(messages: Message[], isStreaming: boolean): ThreadMessageLike[] {
  return messages.map((message) => {
    if (message.role === "user") {
      return {
        id: message.id,
        role: "user",
        content: message.content,
        createdAt: new Date(message.createdAt),
      };
    }

    return {
      id: message.id,
      role: "assistant",
      content: message.content,
      createdAt: new Date(message.createdAt),
      status:
        isStreaming && message === messages.at(-1)
          ? { type: "running" }
          : { type: "complete", reason: "stop" },
    };
  });
}

export function getTextFromAssistantAppendMessage(message: AppendMessage): string {
  const content: unknown = message.content;

  if (typeof content === "string") {
    return content.trim();
  }

  if (!Array.isArray(content)) {
    return "";
  }

  return content
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("\n\n")
    .trim();
}
