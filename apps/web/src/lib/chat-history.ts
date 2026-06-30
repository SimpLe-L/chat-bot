import type { ChatRole } from "@nebulai/shared";

import type { Conversation, Message } from "./types";

interface ChatSessionSummary {
  id: string;
  title: string;
  updated_at: string;
  message_count: number;
}

interface ChatMessageRecord {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function loadConversations(): Promise<Conversation[]> {
  const response = await fetch(`${API_BASE_URL}/api/chat/sessions`);
  if (!response.ok) {
    throw new Error(`会话列表查询失败：${response.status}`);
  }
  const payload = (await response.json()) as { sessions: ChatSessionSummary[] };
  const conversations = await Promise.all(payload.sessions.map(loadConversation));
  return conversations.filter((conversation): conversation is Conversation => conversation !== null);
}

export async function createConversationSession(title = "新的知识库问答"): Promise<Conversation> {
  const response = await fetch(`${API_BASE_URL}/api/chat/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ title }),
  });
  if (!response.ok) {
    throw new Error(`会话创建失败：${response.status}`);
  }
  const session = (await response.json()) as ChatSessionSummary;
  return {
    id: session.id,
    title: session.title,
    updatedAt: session.updated_at,
    messages: [],
  };
}

export async function renameConversation(sessionId: string, title: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ title }),
  });
  if (!response.ok) {
    throw new Error(`会话重命名失败：${response.status}`);
  }
}

export async function deleteConversation(sessionId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(`会话删除失败：${response.status}`);
  }
}

async function loadConversation(session: ChatSessionSummary): Promise<Conversation | null> {
  const response = await fetch(`${API_BASE_URL}/api/chat/sessions/${session.id}/messages`);
  if (!response.ok) {
    return null;
  }
  const payload = (await response.json()) as { messages: ChatMessageRecord[] };
  return {
    id: session.id,
    title: session.title,
    updatedAt: session.updated_at,
    messages: payload.messages.map(toMessage),
  };
}

function toMessage(record: ChatMessageRecord): Message {
  return {
    id: record.id,
    role: toChatRole(record.role),
    content: record.content,
    createdAt: record.created_at,
  };
}

function toChatRole(role: string): ChatRole {
  return role === "user" || role === "assistant" || role === "system" ? role : "assistant";
}
