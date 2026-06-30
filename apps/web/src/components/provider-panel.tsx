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
        <div className="space-y-2">
          {Object.values(status.providers).map((provider) => (
            <div className="rounded-md border border-line bg-white p-3" key={provider.name}>
              <div className="mb-1 flex items-start gap-2">
                <ProviderIcon status={provider.status} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-xs font-semibold uppercase text-ink/65">{provider.name}</h3>
                    <span className="truncate text-[11px] text-ink/45">{provider.provider}</span>
                  </div>
                  <p className="mt-1 text-[11px] leading-4 text-ink/55">{provider.message}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function ProviderIcon({ status }: { status: string }) {
  if (["completed", "configured"].includes(status)) {
    return <CheckCircle2 className="mt-0.5 shrink-0 text-accent" size={15} />;
  }
  return <TriangleAlert className="mt-0.5 shrink-0 text-warn" size={15} />;
}
