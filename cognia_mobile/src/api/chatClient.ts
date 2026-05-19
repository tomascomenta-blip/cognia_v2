import type { ChatApiResponse } from '../types';

export async function sendMessage(
  input: string,
  serverUrl: string,
  signal?: AbortSignal
): Promise<ChatApiResponse> {
  const url = `${serverUrl.replace(/\/$/, '')}/api/chat`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ input }),
    signal,
  });
  if (!res.ok) throw new Error(`Server returned ${res.status}`);
  return res.json() as Promise<ChatApiResponse>;
}

export async function testConnection(serverUrl: string): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    const res = await fetch(
      `${serverUrl.replace(/\/$/, '')}/api/health`,
      { signal: controller.signal }
    );
    clearTimeout(timeout);
    return res.ok;
  } catch {
    return false;
  }
}
