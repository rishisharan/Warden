// Thin fetch wrappers around warden-api. Every call goes through
// warden-api (never straight to the Python retrieval service or Chroma) -
// warden-api is the single place that knows how to turn a userId into an
// access-level filter, and the single place the UI needs to know about.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8082";

async function parseError(res, fallback) {
  try {
    const body = await res.json();
    return body.error || fallback;
  } catch {
    return fallback;
  }
}

export async function fetchUsers() {
  const res = await fetch(`${API_BASE_URL}/api/users`);
  if (!res.ok) {
    throw new Error(await parseError(res, `Failed to load users (${res.status})`));
  }
  return res.json();
}

// Returns the QueryResponse shape from warden-api, plus the traceId read
// off the X-Trace-Id response header (see TraceIdFilter) so the UI can
// show which server-side log lines a given answer corresponds to.
export async function sendQuery(userId, question) {
  const res = await fetch(`${API_BASE_URL}/api/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ userId, question }),
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
    body: formData,
  });

  if (!res.ok) {
    throw new Error(await parseError(res, `Upload failed (${res.status})`));
  }

  return res.json();
}
