import type { ChatApiResponse, ReadyResponse, StreamToken } from '../types';

function baseUrl(serverUrl: string): string {
  return serverUrl.replace(/\/$/, '');
}

export async function sendMessage(
  prompt: string,
  serverUrl: string,
  signal?: AbortSignal
): Promise<ChatApiResponse> {
  const res = await fetch(`${baseUrl(serverUrl)}/infer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt }),
    signal,
  });
  if (!res.ok) throw new Error(`Server returned ${res.status}`);
  return res.json() as Promise<ChatApiResponse>;
}

// Streams tokens from GET /infer-stream?prompt=...
// React Native 0.81 supports response.body.getReader() on fetch.
// Each SSE line is: "data: {...}\n\n"
// The final event has done=true and carries the full response metadata.
export async function streamMessage(
  prompt: string,
  serverUrl: string,
  onToken: (token: string) => void,
  onDone: (final: StreamToken) => void,
  onError: (err: Error) => void,
  signal?: AbortSignal
): Promise<void> {
  const url = `${baseUrl(serverUrl)}/infer-stream?prompt=${encodeURIComponent(prompt)}`;
  let res: Response;
  try {
    res = await fetch(url, { signal });
  } catch (err) {
    onError(err instanceof Error ? err : new Error(String(err)));
    return;
  }

  if (!res.ok) {
    onError(new Error(`Server returned ${res.status}`));
    return;
  }

  if (!res.body) {
    onError(new Error('Response body is not readable'));
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      // Split on double-newline (SSE event boundary) but process line by line
      const lines = buffer.split('\n');
      // Keep the last (potentially incomplete) chunk in the buffer
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data: ')) continue;
        const jsonStr = trimmed.slice(6);
        if (!jsonStr) continue;

        let parsed: StreamToken;
        try {
          parsed = JSON.parse(jsonStr) as StreamToken;
        } catch {
          // Malformed SSE line — skip silently
          continue;
        }

        if (parsed.done) {
          onDone(parsed);
          return;
        }
        if (parsed.token != null) {
          onToken(parsed.token);
        }
      }
    }
  } catch (err) {
    // AbortError is not a failure — caller handles it
    if (err instanceof Error && err.name === 'AbortError') return;
    onError(err instanceof Error ? err : new Error(String(err)));
  } finally {
    reader.releaseLock();
  }
}

export async function checkReady(serverUrl: string): Promise<ReadyResponse | null> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    const res = await fetch(`${baseUrl(serverUrl)}/ready`, {
      signal: controller.signal,
    });
    clearTimeout(timeout);
    if (!res.ok) return null;
    return res.json() as Promise<ReadyResponse>;
  } catch {
    return null;
  }
}

// Kept for backwards compatibility — settings screen now uses checkReady
export async function testConnection(serverUrl: string): Promise<boolean> {
  const result = await checkReady(serverUrl);
  return result !== null;
}
