const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

export async function apiFetch(path: string, options: RequestInit = {}) {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      "ngrok-skip-browser-warning": "1",
      ...options.headers,
    },
    ...options,
  });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json();
}
