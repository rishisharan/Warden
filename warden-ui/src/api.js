// Thin fetch wrappers around warden-api. Every call goes through
// warden-api (never straight to the Python retrieval service or Chroma) -
// Java resolves access permissions from the authenticated session.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8082";

async function csrfHeaders() {
  const response = await fetch(API_BASE_URL + "/api/csrf", { credentials: "include" });
  if (!response.ok) throw new Error("Could not start a secure request.");
  const { headerName, token } = await response.json();
  return { [headerName]: token };
}

export async function login(username, password) {
  const response = await fetch(API_BASE_URL + "/api/login", {
    method: "POST",
    credentials: "include",
    headers: await csrfHeaders(),
    body: new URLSearchParams({ username, password }),
  });
  if (!response.ok) throw new Error("Sign-in failed.");
}

export async function logout() {
  const response = await fetch(API_BASE_URL + "/api/logout", {
    method: "POST", credentials: "include", headers: await csrfHeaders(),
  });
  if (!response.ok) throw new Error("Sign-out failed.");
}

async function parseError(res, fallback) {
  try {
    const body = await res.json();
    return body.error || fallback;
  } catch {
    return fallback;
  }
}

export async function fetchUsers() {
  const res = await fetch(`${API_BASE_URL}/api/users`, { credentials: "include" });
  if (res.status === 401) return [];
  if (!res.ok) {
    throw new Error(await parseError(res, `Failed to load users (${res.status})`));
  }
  return res.json();
}

// Returns the QueryResponse shape from warden-api, plus the traceId read
// off the X-Trace-Id response header (see TraceIdFilter) so the UI can
// show which server-side log lines a given answer corresponds to.
export async function sendQuery(question) {
  const res = await fetch(`${API_BASE_URL}/api/query`, {
    method: "POST",
    credentials: "include",
    headers: { ...(await csrfHeaders()), "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  const traceId = res.headers.get("X-Trace-Id");

  if (!res.ok) {
    throw new Error(await parseError(res, `Query failed (${res.status})`));
  }

  const data = await res.json();
  return { ...data, traceId };
}

export async function uploadDocument(file, accessLevel) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("accessLevel", accessLevel);

  const res = await fetch(`${API_BASE_URL}/api/documents`, {
    method: "POST",
    credentials: "include",
    headers: await csrfHeaders(),
    body: formData,
  });

  if (!res.ok) {
    throw new Error(await parseError(res, `Upload failed (${res.status})`));
  }

  return res.json();
}
