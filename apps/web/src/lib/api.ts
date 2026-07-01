export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${API_BASE_URL}${input}`, {
    ...init,
    credentials: "include",
    headers: init.headers,
  });
}
