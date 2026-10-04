/* Thin API client. The auth token is held in memory and persisted to
 * localStorage; it is never placed in a URL or logged. */

const BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const TOKEN_KEY = "koverly.token";

export class ApiError extends Error {
  code: string;
  status: number;
  details?: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details?: Record<string, unknown>) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts: { formData?: FormData } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let payload: BodyInit | undefined;
  if (opts.formData) {
    payload = opts.formData;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const resp = await fetch(`${BASE}/api/v1${path}`, { method, headers, body: payload });

  if (resp.status === 204) return undefined as T;

  const text = await resp.text();
  const data = text ? JSON.parse(text) : null;

  if (!resp.ok) {
    const err = data?.error ?? {};
    if (resp.status === 401 && token) {
      setToken(null);
    }
    throw new ApiError(
      resp.status,
      err.code || "ERROR",
      err.message || "Something went wrong.",
      err.details,
    );
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
  upload: <T>(path: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<T>("POST", path, undefined, { formData: fd });
  },
  /** Fetch a binary endpoint with auth and return it as a Blob. */
  blob: (path: string) => requestBlob(path),
};

async function requestBlob(path: string): Promise<Blob> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const resp = await fetch(`${BASE}/api/v1${path}`, { headers });
  if (!resp.ok) {
    let code = "ERROR";
    let message = "Something went wrong.";
    let details: Record<string, unknown> | undefined;
    try {
      const data = JSON.parse(await resp.text());
      code = data?.error?.code || code;
      message = data?.error?.message || message;
      details = data?.error?.details;
    } catch {
      /* non-JSON error body */
    }
    if (resp.status === 401 && token) setToken(null);
    throw new ApiError(resp.status, code, message, details);
  }
  return resp.blob();
}

/** Human-readable message for any thrown error, preferring API detail. */
export function errorMessage(err: unknown, fallback = "Something went wrong."): string {
  if (err instanceof ApiError) {
    const fields = (err.details as { fields?: Array<{ msg?: string }> } | undefined)?.fields;
    const firstField = Array.isArray(fields) ? fields.find((f) => f?.msg)?.msg : undefined;
    return firstField || err.message || fallback;
  }
  if (err instanceof Error) return err.message || fallback;
  return fallback;
}

/** Trigger a browser download for a Blob without leaking the object URL. */
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
