import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, PlugZap, RefreshCw, TriangleAlert } from "lucide-react";

import { getProviderStatus, type ProviderStatus } from "../lib/providers";

interface ProviderPanelProps {
  onError: (message: string) => void;
}

export function ProviderPanel({ onError }: ProviderPanelProps) {
  const [status, setStatus] = useState<ProviderStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isVerifying, setIsVerifying] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getProviderStatus(false)
      .then((payload) => {
        if (!cancelled) {
          setStatus(payload);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          onError(err instanceof Error ? err.message : "Provider 状态查询失败");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [onError]);

  const verifyLive = async () => {
    setIsVerifying(true);
    try {
      setStatus(await getProviderStatus(true));
    } catch (err) {
      onError(err instanceof Error ? err.message : "Provider live verify 失败");
    } finally {
      setIsVerifying(false);
    }
  };

  return (
    <section className="mb-6 border-b border-line pb-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <PlugZap size={17} />
          <h2 className="text-sm font-semibold uppercase text-ink/70">Providers</h2>
        </div>
        <button
          className="grid size-8 place-items-center rounded-md border border-line bg-white text-ink transition hover:border-ink/25 disabled:cursor-not-allowed disabled:text-ink/35"
          disabled={isLoading || isVerifying}
          onClick={() => void verifyLive()}
          title="执行 live provider 验证"
          type="button"
        >
          {isVerifying ? <Loader2 className="animate-spin" size={15} /> : <RefreshCw size={15} />}
        </button>
      </div>

      {isLoading || status === null ? (
        <div className="flex items-center gap-2 rounded-md border border-line bg-white px-3 py-4 text-xs text-ink/55">
          <Loader2 className="animate-spin" size={14} />
          正在读取 provider 状态
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-2">
          {Object.values(status.providers).map((provider) => (
            <div
              className="flex min-w-0 items-center gap-1.5 rounded-md border border-line bg-white px-2 py-2"
              key={provider.name}
              title={`${provider.name}: ${provider.provider} · ${provider.status} · ${provider.message}`}
            >
              <ProviderIcon status={provider.status} />
              <span className="min-w-0 truncate text-[11px] font-semibold uppercase text-ink/65">
                {provider.name}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function ProviderIcon({ status }: { status: string }) {
  if (["completed", "configured"].includes(status)) {
    return <CheckCircle2 className="shrink-0 text-accent" size={14} />;
  }
  return <TriangleAlert className="shrink-0 text-warn" size={14} />;
}
