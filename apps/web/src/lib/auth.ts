import { apiFetch } from "./api";

export interface AuthUser {
  id: string;
  email: string | null;
  name: string;
  avatar_url: string | null;
  workspace_id: string;
}

export async function getCurrentUser(): Promise<AuthUser | null> {
  const response = await apiFetch("/api/auth/me");
  if (response.status === 401) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`登录状态查询失败：${response.status}`);
  }
  return (await response.json()) as AuthUser;
}

export async function requestEmailCode(email: string): Promise<{ message: string; dev_code?: string | null }> {
  const response = await apiFetch("/api/auth/email/request-code", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ email }),
  });
  if (!response.ok) {
    throw new Error(await readErrorDetail(response, `验证码发送失败：${response.status}`));
  }
  return (await response.json()) as { message: string; dev_code?: string | null };
}

export async function loginWithEmail(email: string, code: string): Promise<AuthUser> {
  const response = await apiFetch("/api/auth/email/login", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ email, code }),
  });
  if (!response.ok) {
    throw new Error(await readErrorDetail(response, `邮箱登录失败：${response.status}`));
  }
  return (await response.json()) as AuthUser;
}

export async function loginWithInternalTestAccount(): Promise<AuthUser> {
  const response = await apiFetch("/api/auth/dev-login", {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await readErrorDetail(response, `内部测试账号登录失败：${response.status}`));
  }
  return (await response.json()) as AuthUser;
}

export async function getOAuthUrl(provider: "github" | "google"): Promise<string> {
  const response = await apiFetch(`/api/auth/oauth/${provider}`);
  if (!response.ok) {
    throw new Error(await readErrorDetail(response, `${provider} 登录不可用：${response.status}`));
  }
  const payload = (await response.json()) as { configured: boolean; url?: string | null; message: string };
  if (!payload.configured || !payload.url) {
    throw new Error(payload.message);
  }
  return payload.url;
}

export async function logout(): Promise<void> {
  const response = await apiFetch("/api/auth/logout", {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`退出失败：${response.status}`);
  }
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    return typeof payload.detail === "string" ? payload.detail : fallback;
  } catch {
    return fallback;
  }
}
