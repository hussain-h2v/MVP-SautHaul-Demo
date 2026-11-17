export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const IDEMPOTENT = new Set(["POST", "PUT", "PATCH"]);

export function readCookie(name: string, cookieString?: string): string | null {
  const src = cookieString ?? (typeof document !== "undefined" ? document.cookie : "");
  for (const part of src.split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === name) return decodeURIComponent(v.join("="));
  }
  return null;
}

export function buildHeaders(
  method: string,
  hasBody: boolean,
  cookieString?: string,
  idempotencyKey?: string,
): Record<string, string> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (hasBody) headers["Content-Type"] = "application/json";
  if (idempotencyKey && IDEMPOTENT.has(method.toUpperCase())) headers["Idempotency-Key"] = idempotencyKey;
  if (UNSAFE.has(method.toUpperCase())) {
    const csrf = readCookie("csrf_token", cookieString);
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  return headers;
}

async function toError(res: Response): Promise<ApiError> {
  let code = "HTTP_" + res.status;
  let message = res.statusText || "Request failed";
  let details: Record<string, unknown> = {};
  try {
    const body = await res.json();
    if (body?.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details ?? {};
    }
  } catch {
    /* non-JSON body */
  }
  return new ApiError(res.status, code, message, details);
}

let refreshing: Promise<boolean> | null = null;

async function silentRefresh(): Promise<boolean> {
  refreshing ??= fetch("/api/v1/auth/refresh", {
    method: "POST",
    credentials: "include",
    headers: buildHeaders("POST", false),
  })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export async function api<T>(
  path: string,
  init: { method?: string; body?: unknown; formData?: FormData } = {},
): Promise<T> {
  const method = init.method ?? "GET";
  const key = crypto.randomUUID();
  const run = () =>
    fetch(`/api/v1${path}`, {
      method,
      credentials: "include",
      headers: buildHeaders(method, init.body !== undefined, undefined, key),
      body: init.formData ?? (init.body !== undefined ? JSON.stringify(init.body) : undefined),
    });
  let res = await run();
  const isAuthCall = path.startsWith("/auth/login") || path.startsWith("/auth/refresh");
  if (res.status === 401 && !isAuthCall && (await silentRefresh())) res = await run();
  if (!res.ok) throw await toError(res);
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export async function downloadCsv(path: string, filename: string): Promise<void> {
  const res = await fetch(`/api/v1${path}`, { credentials: "include", headers: { Accept: "text/csv" } });
  if (!res.ok) throw await toError(res);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
