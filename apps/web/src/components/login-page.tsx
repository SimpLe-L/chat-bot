import { useState } from "react";
import { Bot, Github, KeyRound, Mail, ShieldCheck, UserRoundCheck } from "lucide-react";

import {
  getOAuthUrl,
  loginWithEmail,
  loginWithInternalTestAccount,
  requestEmailCode,
  type AuthUser,
} from "../lib/auth";

interface LoginPageProps {
  onLogin: (user: AuthUser) => void;
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [devCode, setDevCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<"github" | "google" | "code" | "email" | "internal" | null>(null);

  const handleOAuth = async (provider: "github" | "google") => {
    setError(null);
    setLoading(provider);
    try {
      const url = await getOAuthUrl(provider);
      window.location.href = url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "OAuth 登录不可用");
    } finally {
      setLoading(null);
    }
  };

  const handleRequestCode = async () => {
    if (!email.trim()) {
      setError("请输入邮箱。");
      return;
    }
    setError(null);
    setLoading("code");
    try {
      const result = await requestEmailCode(email);
      setMessage(result.message);
      setDevCode(result.dev_code ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "验证码发送失败");
    } finally {
      setLoading(null);
    }
  };

  const handleEmailLogin = async () => {
    if (!email.trim() || !code.trim()) {
      setError("请输入邮箱和验证码。");
      return;
    }
    setError(null);
    setLoading("email");
    try {
      const user = await loginWithEmail(email, code);
      onLogin(user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "邮箱登录失败");
    } finally {
      setLoading(null);
    }
  };

  const handleInternalLogin = async () => {
    setError(null);
    setLoading("internal");
    try {
      const user = await loginWithInternalTestAccount();
      onLogin(user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "内部测试账号登录失败");
    } finally {
      setLoading(null);
    }
  };

  return (
    <main className="grid min-h-screen bg-[#F5F6F1] text-ink lg:grid-cols-[minmax(420px,0.95fr)_1.05fr]">
      <section className="flex min-h-screen flex-col justify-between px-6 py-6 sm:px-10 lg:px-14">
        <div className="flex items-center gap-3">
          <div className="grid size-10 place-items-center rounded-md bg-ink text-white">
            <Bot size={20} />
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight">nebulai bot</h1>
            <p className="text-xs text-ink/55">Private RAG workspace</p>
          </div>
        </div>

        <div className="mx-auto w-full max-w-[420px] py-12">
          <div className="mb-8">
            <p className="mb-2 text-xs font-medium uppercase text-ink/45">Account access</p>
            <h2 className="text-3xl font-semibold tracking-tight">登录到知识库</h2>
            <p className="mt-3 text-sm leading-6 text-ink/58">
              每个账号使用独立 workspace，聊天、文档和检索来源按 workspace 隔离。
            </p>
          </div>

          <div className="space-y-3">
            <button
              className="flex h-11 w-full items-center justify-center gap-2 rounded-md bg-accent px-4 text-sm font-medium text-white transition hover:bg-[#256B58] disabled:cursor-wait disabled:opacity-60"
              disabled={loading !== null}
              onClick={() => void handleInternalLogin()}
              type="button"
            >
              <UserRoundCheck size={17} />
              内部测试账号登录
            </button>
            <button
              className="flex h-11 w-full items-center justify-center gap-2 rounded-md border border-[#D8DED3] bg-white text-sm font-medium transition hover:border-ink/25 disabled:cursor-wait disabled:opacity-60"
              disabled={loading !== null}
              onClick={() => void handleOAuth("github")}
              type="button"
            >
              <Github size={17} />
              GitHub 登录
            </button>
            <button
              className="flex h-11 w-full items-center justify-center gap-2 rounded-md border border-[#D8DED3] bg-white text-sm font-medium transition hover:border-ink/25 disabled:cursor-wait disabled:opacity-60"
              disabled={loading !== null}
              onClick={() => void handleOAuth("google")}
              type="button"
            >
              <KeyRound size={17} />
              Google 登录
            </button>
          </div>

          <div className="my-7 flex items-center gap-3 text-xs text-ink/35">
            <span className="h-px flex-1 bg-[#D8DED3]" />
            邮箱验证码
            <span className="h-px flex-1 bg-[#D8DED3]" />
          </div>

          <div className="space-y-3">
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-ink/55">邮箱</span>
              <input
                className="h-11 w-full rounded-md border border-[#D8DED3] bg-white px-3 text-sm outline-none transition placeholder:text-ink/30 focus:border-accent focus:ring-2 focus:ring-accent/15"
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                type="email"
                value={email}
              />
            </label>
            <div className="grid grid-cols-[1fr_auto] gap-2">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-ink/55">验证码</span>
                <input
                  className="h-11 w-full rounded-md border border-[#D8DED3] bg-white px-3 text-sm outline-none transition placeholder:text-ink/30 focus:border-accent focus:ring-2 focus:ring-accent/15"
                  inputMode="numeric"
                  maxLength={6}
                  onChange={(event) => setCode(event.target.value)}
                  placeholder="6 位数字"
                  value={code}
                />
              </label>
              <button
                className="mt-5 inline-flex h-11 items-center gap-2 rounded-md border border-[#D8DED3] bg-white px-3 text-sm font-medium transition hover:border-ink/25 disabled:cursor-wait disabled:opacity-60"
                disabled={loading !== null}
                onClick={() => void handleRequestCode()}
                type="button"
              >
                <Mail size={15} />
                获取
              </button>
            </div>
            <button
              className="flex h-11 w-full items-center justify-center rounded-md bg-accent px-4 text-sm font-medium text-white transition hover:bg-[#256B58] disabled:cursor-wait disabled:opacity-60"
              disabled={loading !== null}
              onClick={() => void handleEmailLogin()}
              type="button"
            >
              登录
            </button>
          </div>

          {message ? <p className="mt-4 text-sm text-ink/60">{message}</p> : null}
          {devCode ? (
            <p className="mt-2 rounded-md border border-[#D8DED3] bg-white px-3 py-2 text-sm text-ink/70">
              本地验证码：<span className="font-semibold tracking-widest">{devCode}</span>
            </p>
          ) : null}
          {error ? <p className="mt-4 text-sm text-red-700">{error}</p> : null}
        </div>

        <p className="text-xs text-ink/40">Auth protects sessions, documents, vectors, traces, and ingestion jobs.</p>
      </section>

      <section className="hidden min-h-screen border-l border-[#D8DED3] bg-[#E8ECE4] px-12 py-10 lg:flex lg:flex-col lg:justify-end">
        <div className="max-w-xl">
          <ShieldCheck className="mb-6 text-accent" size={38} />
          <h2 className="text-4xl font-semibold leading-tight tracking-tight">私有知识需要明确的数据边界。</h2>
          <p className="mt-5 max-w-lg text-base leading-7 text-ink/60">
            登录后，上传文档、L3 向量、会话记录和 RAG trace 都会写入当前 workspace；检索时也只命中当前 workspace 的 chunk。
          </p>
        </div>
      </section>
    </main>
  );
}
