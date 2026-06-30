import type { ChatMessage, RagSource, RagStep } from "@nebulai/shared";

export type Message = ChatMessage;
export type Source = RagSource;
export type Step = RagStep;

export interface Conversation {
  id: string;
  title: string;
  updatedAt: string;
  messages: Message[];
}

