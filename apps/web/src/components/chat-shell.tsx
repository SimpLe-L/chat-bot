import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  type ExternalStoreAdapter,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import { Bot, FileText, Pencil, Plus, Square, Trash2 } from "lucide-react";
import type { ChatStreamEvent } from "@nebulai/shared";

import { cancelChatRun, streamChat } from "../lib/chat-stream";
import {
  createConversationSession,
  deleteConversation,
  loadConversations,
  renameConversation,
} from "../lib/chat-history";
import { loadLatestTrace } from "../lib/rag-trace";
import {
  assistantUiIntegration,
  getTextFromAssistantAppendMessage,
  toAssistantUiMessages,
} from "../lib/assistant-ui-adapter";
import type { Conversation, Message, Source, Step } from "../lib/types";
import { Composer } from "./composer";
import { DocumentPanel } from "./document-panel";
import { MessageList } from "./message-list";
import { ProviderPanel } from "./provider-panel";
import { RagTimeline } from "./rag-timeline";

const now = () => new Date().toISOString();
const initialConversationId = "local-initial-conversation";
const initialAssistantMessageId = "local-initial-assistant-message";
const initialCreatedAt = "2026-06-30T00:00:00.000Z";

const createConversation = (
  overrides: Partial<Pick<Conversation, "id" | "updatedAt">> & {
    assistantMessageId?: string;
    createdAt?: string;
  } = {},
): Conversation => ({
  id: overrides.id ?? crypto.randomUUID(),
  title: "新的知识库问答",
  updatedAt: overrides.updatedAt ?? now(),
  messages: [
    {
      id: overrides.assistantMessageId ?? crypto.randomUUID(),
      role: "assistant",
      content: "你好，我是 nebulai bot。",
      createdAt: overrides.createdAt ?? now(),
    },
  ],
});

const createInitialConversation = () =>
  createConversation({
    id: initialConversationId,
    assistantMessageId: initialAssistantMessageId,
    createdAt: initialCreatedAt,
    updatedAt: initialCreatedAt,
  });

export function ChatShell() {
  const [conversations, setConversations] = useState<Conversation[]>([createInitialConversation()]);
  const [activeId, setActiveId] = useState(() => conversations[0].id);
  const [steps, setSteps] = useState<Step[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeRunIdRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadConversations()
      .then((items) => {
        if (!cancelled && items.length > 0) {
          setConversations(items);
          setActiveId(items[0].id);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId) ?? conversations[0],
    [activeId, conversations],
  );

  useEffect(() => {
    if (isStreaming || !activeConversation?.id) {
      return;
    }
    let cancelled = false;
    loadLatestTrace(activeConversation.id)
      .then((trace) => {
        if (!cancelled && trace) {
          setSteps(trace.steps);
          setSources(trace.sources);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [activeConversation?.id, isStreaming]);

  const updateActiveConversation = useCallback((updater: (conversation: Conversation) => Conversation) => {
    setConversations((items) =>
      items.map((item) => (item.id === activeConversation.id ? updater(item) : item)),
    );
  }, [activeConversation.id]);

  const appendMessage = useCallback((message: Message) => {
    updateActiveConversation((conversation) => ({
      ...conversation,
      title:
        conversation.messages.length <= 1 && message.role === "user"
          ? message.content.slice(0, 26)
          : conversation.title,
      updatedAt: now(),
      messages: [...conversation.messages, message],
    }));
  }, [updateActiveConversation]);

  const patchAssistantMessage = useCallback((messageId: string, token: string) => {
    updateActiveConversation((conversation) => ({
      ...conversation,
      updatedAt: now(),
      messages: conversation.messages.map((message) =>
        message.id === messageId
          ? {
            ...message,
            content: message.content + token,
          }
          : message,
      ),
    }));
  }, [updateActiveConversation]);

  const handleStreamEvent = useCallback((event: ChatStreamEvent, assistantMessageId: string) => {
    if (event.type === "accepted" && event.runId) {
      activeRunIdRef.current = event.runId;
      return;
    }

    if (event.type === "step" && event.step) {
      setSteps((items) => [...items, event.step]);
      return;
    }

    if (event.type === "source" && event.source) {
      setSources((items) => [...items, event.source]);
      return;
    }

    if (event.type === "token" && event.token) {
      patchAssistantMessage(assistantMessageId, event.token);
      return;
    }

    if (event.type === "warning" && event.message) {
      setSteps((items) => [
        ...items,
        {
          id: crypto.randomUUID(),
          kind: "fallback",
          title: "降级提示",
          detail: event.message ?? "",
          status: "warning",
          createdAt: now(),
        },
      ]);
    }
  }, [patchAssistantMessage]);

  const handleSubmit = useCallback(async (content: string) => {
    if (isStreaming || !content.trim()) {
      return;
    }

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content,
      createdAt: now(),
    };
    const assistantMessage: Message = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "",
      createdAt: now(),
    };

    setError(null);
    setSteps([]);
    setSources([]);
    appendMessage(userMessage);
    appendMessage(assistantMessage);
    setIsStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;
    activeRunIdRef.current = null;

    try {
      await streamChat({
        message: content,
        sessionId: activeConversation.id,
        signal: controller.signal,
        onEvent: (event) => handleStreamEvent(event, assistantMessage.id),
      });
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError(err instanceof Error ? err.message : "问答接口异常");
      }
    } finally {
      abortRef.current = null;
      activeRunIdRef.current = null;
      setIsStreaming(false);
    }
  }, [activeConversation.id, appendMessage, handleStreamEvent, isStreaming]);

  const stopStreaming = useCallback(async () => {
    if (activeRunIdRef.current) {
      await cancelChatRun(activeRunIdRef.current).catch(() => undefined);
    }
    abortRef.current?.abort();
    activeRunIdRef.current = null;
    setIsStreaming(false);
  }, []);

  const createNewChat = async () => {
    const conversation = await createConversationSession().catch(() => createConversation());
    if (conversation.messages.length === 0) {
      conversation.messages = createConversation().messages;
    }
    setConversations((items) => [conversation, ...items]);
    setActiveId(conversation.id);
    setSteps([]);
    setSources([]);
    setError(null);
  };

  const renameConversationById = async (conversationId: string) => {
    const conversation = conversations.find((item) => item.id === conversationId);
    if (!conversation) {
      return;
    }
    const nextTitle = window.prompt("会话标题", conversation.title)?.trim();
    if (!nextTitle || nextTitle === conversation.title) {
      return;
    }
    setConversations((items) =>
      items.map((item) =>
        item.id === conversationId ? { ...item, title: nextTitle, updatedAt: now() } : item,
      ),
    );
    await renameConversation(conversationId, nextTitle).catch((err) => {
      setError(err instanceof Error ? err.message : "会话重命名失败");
    });
  };

  const deleteConversationById = async (deletedId: string) => {
    if (isStreaming && deletedId === activeConversation.id) {
      return;
    }
    const remaining = conversations.filter((conversation) => conversation.id !== deletedId);
    const nextConversations = remaining.length > 0 ? remaining : [createConversation()];
    setConversations(nextConversations);
    if (deletedId === activeConversation.id) {
      setActiveId(nextConversations[0].id);
      setSteps([]);
      setSources([]);
    }
    setError(null);
    await deleteConversation(deletedId).catch((err) => {
      setError(err instanceof Error ? err.message : "会话删除失败");
    });
  };

  const assistantUiMessages = useMemo(
    () => toAssistantUiMessages(activeConversation.messages, isStreaming),
    [activeConversation.messages, isStreaming],
  );
  const assistantStore = useMemo<ExternalStoreAdapter<ThreadMessageLike>>(
    () => ({
      messages: assistantUiMessages,
      convertMessage: (message) => message,
      isDisabled: isStreaming,
      isRunning: isStreaming,
      onNew: async (message) => {
        const content = getTextFromAssistantAppendMessage(message);
        if (content) {
          await handleSubmit(content);
        }
      },
      onCancel: stopStreaming,
      unstable_capabilities: {
        copy: true,
      },
    }),
    [assistantUiMessages, isStreaming, handleSubmit, stopStreaming],
  );
  const assistantRuntime = useExternalStoreRuntime(assistantStore);

  return (
    <AssistantRuntimeProvider runtime={assistantRuntime}>
      <main className="h-screen overflow-hidden bg-[#EEF1ED] text-ink lg:grid lg:grid-cols-[280px_minmax(0,1fr)_380px]">
        <aside className="hidden h-screen min-h-0 border-r border-[#D9DED6] bg-[#E7ECE6] px-4 py-5 lg:flex lg:flex-col">
          <div className="mb-5 flex shrink-0 items-center gap-3 px-1">
            <div className="grid size-10 place-items-center rounded-md bg-ink text-white shadow-soft">
              <Bot size={20} />
            </div>
            <div>
              <h1 className="text-lg font-semibold tracking-tight">nebulai bot</h1>
              <p className="text-xs text-ink/55">Private RAG workspace</p>
            </div>
          </div>

          <button
            className="mb-5 flex h-10 w-full items-center justify-center gap-2 rounded-md bg-accent px-3 text-sm font-medium text-white transition hover:bg-[#256B58] focus:outline-none focus:ring-2 focus:ring-accent/25"
            onClick={() => void createNewChat()}
            type="button"
          >
            <Plus size={16} />
            新建问答
          </button>

          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
            {conversations.map((conversation) => (
              <div
                className={`group flex w-full items-center gap-1 rounded-md px-2 py-2 text-left text-sm transition ${conversation.id === activeConversation.id
                  ? "bg-white text-ink shadow-soft"
                  : "text-ink/65 hover:bg-white/65"
                  }`}
                key={conversation.id}
              >
                <button
                  className="min-w-0 flex-1 px-1 text-left"
                  onClick={() => setActiveId(conversation.id)}
                  type="button"
                >
                  <span className="block truncate font-medium">{conversation.title}</span>
                  <span className="block text-xs text-ink/45">
                    {new Date(conversation.updatedAt).toLocaleTimeString("zh-CN", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                </button>
                <div className="flex shrink-0 items-center gap-1 opacity-70 transition group-hover:opacity-100 group-focus-within:opacity-100">
                  <button
                    className="grid size-7 place-items-center rounded-md border border-transparent text-ink/50 transition hover:border-[#D6DDD2] hover:bg-white hover:text-ink"
                    onClick={() => void renameConversationById(conversation.id)}
                    title="重命名会话"
                    type="button"
                  >
                    <Pencil size={13} />
                  </button>
                  <button
                    className="grid size-7 place-items-center rounded-md border border-transparent text-ink/50 transition hover:border-[#D6DDD2] hover:bg-white hover:text-ink disabled:cursor-not-allowed disabled:text-ink/25"
                    disabled={isStreaming && conversation.id === activeConversation.id}
                    onClick={() => void deleteConversationById(conversation.id)}
                    title={isStreaming && conversation.id === activeConversation.id ? "生成中不能删除当前会话" : "删除会话"}
                    type="button"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </aside>

        <section className="flex h-screen min-h-0 min-w-0 flex-col bg-[#F7F8F5]">
          <header className="flex min-h-16 shrink-0 items-center justify-between gap-4 border-b border-[#DDE2DA] bg-[#F9FAF7]/95 px-5 backdrop-blur sm:px-6">
            <div className="min-w-0">
              <h2 className="truncate text-base font-semibold tracking-tight">{activeConversation.title}</h2>
              <p className="mt-1 truncate text-xs text-ink/50">
                {assistantUiIntegration.status} · {assistantUiMessages.length} messages
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {isStreaming ? (
                <button
                  className="inline-flex h-9 items-center gap-2 rounded-md border border-[#D6DDD2] bg-white px-3 text-sm transition hover:border-ink/25"
                  onClick={stopStreaming}
                  type="button"
                >
                  <Square size={15} />
                  停止
                </button>
              ) : null}
              <button
                className="grid size-9 place-items-center rounded-md border border-[#D6DDD2] bg-white transition hover:border-ink/25"
                onClick={() => void renameConversationById(activeConversation.id)}
                title="重命名当前会话"
                type="button"
              >
                <Pencil size={16} />
              </button>
              <button
                className="grid size-9 place-items-center rounded-md border border-[#D6DDD2] bg-white transition hover:border-ink/25"
                onClick={() => void deleteConversationById(activeConversation.id)}
                title="删除当前会话"
                type="button"
              >
                <Trash2 size={16} />
              </button>
            </div>
          </header>

          <MessageList
            error={error}
            isStreaming={isStreaming}
            messages={activeConversation.messages}
            sources={sources}
            steps={steps}
          />
          <Composer />
        </section>

        <aside className="hidden h-screen min-h-0 overflow-y-auto border-l border-[#DDE2DA] bg-[#F3F5F1] px-5 py-5 lg:block">
          <div className="mb-5">
            <p className="text-xs font-medium uppercase text-ink/40">Workspace inspector</p>
            <h2 className="mt-1 text-lg font-semibold tracking-tight">RAG 状态</h2>
          </div>

          <ProviderPanel onError={setError} />
          <DocumentPanel onError={setError} />

          <div className="mb-3 flex items-center gap-2 border-t border-[#DDE2DA] pt-5">
            <FileText size={18} />
            <h2 className="text-sm font-semibold uppercase text-ink/70">RAG Trace</h2>
          </div>
          <RagTimeline sources={sources} steps={steps} />
        </aside>
      </main>
    </AssistantRuntimeProvider>
  );
}
