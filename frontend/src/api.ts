
const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export async function apiRequest(
  path: string,
  options: RequestInit = {},
  token?: string
) {
  const headers = new Headers(options.headers);

  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(
      data.detail || data.message || `Request failed (${response.status})`
    );
  }

  return data;
}

export async function login(username: string, password: string) {
  // FastAPI OAuth2PasswordRequestForm expects form-encoded data.
  const body = new URLSearchParams();
  body.set("username", username);
  body.set("password", password);

  const response = await fetch(`${API_URL}/token`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body,
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.detail || "Login failed");
  }

  return data;
}

export async function sendChatMessage(
  query: string,
  sessionId: string,
  token?: string
) {
  return apiRequest(
    "/chat",
    {
      method: "POST",
      body: JSON.stringify({
        query,
        session_id: sessionId,
      }),
    },
    token
  );
}
