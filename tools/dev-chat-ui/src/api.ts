import type { Chat, SseEvent, UiMessage } from "./types";

/** Empty = same origin (Vite proxy). Set VITE_API_BASE_URL for direct backend URL. */
const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";
const AGENT = (import.meta.env.VITE_AGENT_TYPE as string | undefined) ?? "analysis";

function agentPath(suffix: string): string {
  return `${API_BASE}/api/v1/agents/${AGENT}${suffix}`;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function checkHealth(): Promise<{ status: string; platform_db?: string }> {
  const res = await fetch(`${API_BASE}/health`);
  return json(res);
}

export async function listChats(): Promise<Chat[]> {
  const data = await json<{ chats: Chat[] }>(
    await fetch(agentPath("/chats")),
  );
  return data.chats;
}

export async function createChat(title: string | null = null): Promise<Chat> {
  return json<Chat>(
    await fetch(agentPath("/chats"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  );
}

export async function getMessages(chatId: string): Promise<UiMessage[]> {
  const data = await json<{ messages: UiMessage[] }>(
    await fetch(agentPath(`/chats/${chatId}/messages`)),
  );
  return data.messages;
}

function parseSseChunk(chunk: string, onEvent: (event: SseEvent) => void): void {
  if (!chunk.trim()) return;
  let data = "";
  for (const line of chunk.split(/\r?\n/)) {
    if (line.startsWith("data:")) {
      const piece = line.slice(5);
      data += (data ? "\n" : "") + piece.replace(/^\s/, "");
    }
  }
  if (!data) return;
  onEvent(JSON.parse(data) as SseEvent);
}

function drainSseBuffer(buffer: string, onEvent: (event: SseEvent) => void): string {
  const parts = buffer.split(/\r?\n\r?\n/);
  const rest = parts.pop() ?? "";
  for (const part of parts) parseSseChunk(part, onEvent);
  return rest;
}

export async function streamMessage(
  chatId: string,
  content: string,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(agentPath(`/chats/${chatId}/messages`), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ content }),
    signal,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`);
  }
  if (!res.body) throw new Error("No stream body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = drainSseBuffer(buffer, onEvent);
  }

  buffer += decoder.decode();
  drainSseBuffer(buffer, onEvent);
}
