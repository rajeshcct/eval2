/**
 * src/lib/auth.ts
 *
 * Auth client: login, register, logout, persist token in localStorage,
 * and send it on every API/WS call.
 */

export const BACKEND_HTTP_URL = import.meta.env.VITE_BACKEND_HTTP_URL as string;

export interface AuthUser {
  user_id: string;
  username: string;
  display_name: string;
}

const TOKEN_KEY = "evalmind_token";
const USER_KEY = "evalmind_user";

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

function storeSession(token: string, user: AuthUser) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

function authHeaders(): Record<string, string> {
  const token = getStoredToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BACKEND_HTTP_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function checkSetupStatus(): Promise<{ needs_setup: boolean }> {
  return apiFetch<{ needs_setup: boolean }>("/api/auth/setup-status");
}

export async function register(
  username: string,
  password: string,
  display_name?: string,
): Promise<AuthUser> {
  const data = await apiFetch<{ token: string; user: { id: string; username: string; display_name: string } }>(
    "/api/auth/register",
    {
      method: "POST",
      body: JSON.stringify({ username, password, display_name }),
    },
  );
  const user: AuthUser = {
    user_id: data.user.id,
    username: data.user.username,
    display_name: data.user.display_name,
  };
  storeSession(data.token, user);
  return user;
}

export async function login(username: string, password: string): Promise<AuthUser> {
  const data = await apiFetch<{ token: string; user: { id: string; username: string; display_name: string } }>(
    "/api/auth/login",
    {
      method: "POST",
      body: JSON.stringify({ username, password }),
    },
  );
  const user: AuthUser = {
    user_id: data.user.id,
    username: data.user.username,
    display_name: data.user.display_name,
  };
  storeSession(data.token, user);
  return user;
}

export async function logout(): Promise<void> {
  await apiFetch("/api/auth/logout", { method: "POST" }).catch(() => {});
  clearSession();
}

export async function fetchMe(): Promise<AuthUser | null> {
  try {
    const data = await apiFetch<{ user: { user_id: string; username: string; display_name: string } }>("/api/auth/me");
    return data.user;
  } catch {
    return null;
  }
}
