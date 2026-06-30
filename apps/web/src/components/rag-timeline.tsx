import { AlertTriangle, CheckCircle2, Circle, Database, FileText } from "lucide-react";

import type { Source, Step } from "../lib/types";

interface RagTimelineProps {
  steps: Step[];
  sources: Source[];
}

export function RagTimeline({ steps, sources }: RagTimelineProps) {
  if (steps.length === 0 && sources.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-line px-4 py-5 text-sm leading-6 text-ink/50">
        提问后会实时显示问题分析、检索、精排、降级和来源。
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        {steps.map((step) => (
          <div className="rounded-md border border-line bg-white p-3" key={step.id}>
            <div className="mb-2 flex items-center gap-2">
              <StatusIcon status={step.status} />
              <span className="text-sm font-semibold">{step.title}</span>
              {typeof step.score === "number" ? (
                <span className="ml-auto rounded bg-[#EDF5F1] px-2 py-0.5 text-xs text-accent">
                  {step.score.toFixed(2)}
                </span>
              ) : null}
            </div>
            <p className="text-xs leading-5 text-ink/60">{step.detail}</p>
            <p className="mt-2 text-[11px] uppercase text-ink/35">{step.kind}</p>
          </div>
        ))}
      </div>

      <div>
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <Database size={16} />
          Sources
        </div>
        <div className="space-y-3">
          {sources.map((source) => (
            <div className="rounded-md border border-line bg-white p-3" key={source.id}>
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
                <FileText size={15} />
                <span className="truncate">{source.documentTitle}</span>
              </div>
              <p className="text-xs leading-5 text-ink/60">{source.excerpt}</p>
              <div className="mt-3 flex items-center justify-between text-[11px] text-ink/45">
                <span>{source.chunkId}</span>
                <span>
                  score {source.score?.toFixed(2) ?? "-"} / rerank {source.rerankScore?.toFixed(2) ?? "-"}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StatusIcon({ status }: { status: Step["status"] }) {
  if (status === "completed") {
    return <CheckCircle2 className="text-accent" size={16} />;
  }
  if (status === "warning") {
    return <AlertTriangle className="text-warn" size={16} />;
  }
  return <Circle className="text-ink/35" size={16} />;
}
