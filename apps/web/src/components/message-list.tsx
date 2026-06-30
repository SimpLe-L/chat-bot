import { useMemo, useState } from "react";
import { AlertCircle, Bot, CheckCircle2, ChevronDown, FileText, Loader2, Search, User } from "lucide-react";

import type { Message, Source, Step } from "../lib/types";

interface MessageListProps {
  messages: Message[];
  isStreaming: boolean;
  error: string | null;
  sources: Source[];
  steps: Step[];
}

export function MessageList({ messages, isStreaming, error, sources, steps }: MessageListProps) {
  const latestAssistantMessageId = useMemo(
    () => [...messages].reverse().find((message) => message.role === "assistant")?.id,
    [messages],
  );

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
      <div className="mx-auto flex max-w-4xl flex-col gap-6">
        {messages.map((message) => {
          const isUser = message.role === "user";
          const showEvidence = !isUser && message.id === latestAssistantMessageId && (sources.length > 0 || steps.length > 0);
          return (
            <article className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`} key={message.id}>
              {!isUser ? <MessageAvatar role={message.role} /> : null}
              <div
                className={`flex min-w-0 max-w-[86%] flex-col sm:max-w-[74%] ${isUser ? "items-end" : "items-start"
                  }`}
              >
                <div className={`mb-1 flex items-center gap-2 text-xs text-ink/45 ${isUser ? "justify-end" : ""}`}>
                  <span className="font-medium text-ink/60">{isUser ? "你" : "nebulai bot"}</span>
                  <span>{new Date(message.createdAt).toLocaleTimeString("zh-CN")}</span>
                </div>
                <div
                  className={`max-w-full whitespace-pre-wrap break-words rounded-md border px-4 py-3.5 text-sm leading-7 shadow-sm ${isUser
                      ? "border-[#CFE1D9] bg-[#E8F5EF] text-ink"
                      : "border-[#DEE4DC] bg-white text-ink"
                    }`}
                >
                  {message.content && !isUser ? (
                    <AnswerContent content={message.content} disabled={sources.length === 0} sources={sources} />
                  ) : message.content ? (
                    message.content
                  ) : !isUser && isStreaming ? (
                    <StreamingPlaceholder />
                  ) : null}
                </div>
                {showEvidence ? <InlineEvidencePanel sources={sources} steps={steps} /> : null}
              </div>
              {isUser ? <MessageAvatar role={message.role} /> : null}
            </article>
          );
        })}

        {error ? (
          <div className="flex items-center gap-2 rounded-md border border-[#E7B68C] bg-[#FFF3E7] px-4 py-3 text-sm text-[#7A3C12] shadow-sm">
            <AlertCircle size={16} />
            {error}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function AnswerContent({ content, sources, disabled }: { content: string; sources: Source[]; disabled: boolean }) {
  const parts = content.split(/(\[\d+\])/g);

  return (
    <>
      {parts.map((part, index) => {
        const match = part.match(/^\[(\d+)\]$/);
        if (!match) {
          return <span key={`${part}-${index}`}>{part}</span>;
        }

        const sourceIndex = Number(match[1]) - 1;
        const source = sources[sourceIndex];
        if (!source || disabled) {
          return <span key={`${part}-${index}`}>{part}</span>;
        }

        return (
          <a
            className="mx-0.5 inline-flex h-5 translate-y-[-1px] items-center rounded border border-accent/20 bg-accent/10 px-1.5 text-[11px] font-semibold leading-none text-accent transition hover:border-accent/45 hover:bg-accent/15"
            href={`#source-${source.id}`}
            key={`${part}-${index}`}
            title={`${source.documentTitle} · ${source.contextLevel ?? "L3"}`}
          >
            {part}
          </a>
        );
      })}
    </>
  );
}

function InlineEvidencePanel({ sources, steps }: { sources: Source[]; steps: Step[] }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="mt-2 w-full max-w-full overflow-hidden rounded-md border border-[#DDE5DC] bg-[#F3F7F6] text-sm shadow-sm">
      <button
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition hover:bg-white/45"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span className="inline-flex min-w-0 items-center gap-2 font-semibold text-ink/75">
          <Search size={15} />
          <span className="truncate">检索过程与引用来源</span>
        </span>
        <span className="inline-flex shrink-0 items-center gap-2 text-xs text-ink/45">
          {sources.length} 个来源
          <ChevronDown className={`transition ${open ? "rotate-180" : ""}`} size={15} />
        </span>
      </button>

      {open ? (
        <div className="border-t border-[#DDE5DC] px-4 py-3">
          {steps.length > 0 ? (
            <div className="mb-4 space-y-2">
              {steps.slice(0, 5).map((step) => (
                <div className="grid grid-cols-[18px_minmax(0,1fr)] gap-2 text-xs leading-5 text-ink/65" key={step.id}>
                  <CheckCircle2 className={step.status === "warning" ? "text-warn" : "text-accent"} size={14} />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-ink/75">{step.title}</span>
                      {typeof step.score === "number" ? (
                        <span className="rounded bg-white px-1.5 py-0.5 text-[11px] text-ink/45">
                          {step.score.toFixed(2)}
                        </span>
                      ) : null}
                    </div>
                    <p className="max-h-10 overflow-hidden text-ink/50">{step.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : null}

          <div className="space-y-2">
            {sources.map((source, index) => (
              <section className="rounded-md border border-[#DDE5DC] bg-white p-3" id={`source-${source.id}`} key={source.id}>
                <div className="mb-2 flex min-w-0 items-center gap-2">
                  <span className="rounded bg-accent/10 px-1.5 py-0.5 text-xs font-semibold text-accent">
                    [{index + 1}]
                  </span>
                  <FileText className="shrink-0 text-ink/45" size={14} />
                  <span className="truncate text-xs font-semibold text-ink/75">{source.documentTitle}</span>
                </div>
                <p className="text-xs leading-5 text-ink/60">{source.excerpt}</p>
                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink/40">
                  <span>chunk {source.chunkId}</span>
                  {source.contextLevel ? <span>context {source.contextLevel}</span> : null}
                  <span>score {source.score?.toFixed(2) ?? "-"}</span>
                  <span>rerank {source.rerankScore?.toFixed(2) ?? "-"}</span>
                </div>
              </section>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MessageAvatar({ role }: { role: Message["role"] }) {
  const isUser = role === "user";
  return (
    <div
      className={`grid size-10 shrink-0 place-items-center rounded-md shadow-sm ${isUser ? "bg-accent text-white" : "bg-ink text-white"
        }`}
    >
      {isUser ? <User size={17} /> : <Bot size={17} />}
    </div>
  );
}

function StreamingPlaceholder() {
  return (
    <span className="inline-flex items-center gap-2 text-ink/50">
      <Loader2 className="animate-spin" size={15} />
      正在生成
    </span>
  );
}
