import {
  checkHealth,
  createChat,
  getMessages,
  listChats,
  streamMessage,
} from "./api";
import {
  createSequentialTurn,
  resolveAssistantSegments,
  type SequentialTurn,
} from "./turn-renderer";
import type { Chat, SseEvent, UiMessage } from "./types";

const appEl = document.getElementById("app")!;
const chatListWrapEl = document.getElementById("chat-list-wrap")!;
const chatListEl = document.getElementById("chat-list")!;
const messagesEl = document.getElementById("messages")!;
const mainLoadingEl = document.getElementById("main-loading")!;
const sidebarLoadingEl = document.getElementById("sidebar-loading")!;
const composer = document.getElementById("composer") as HTMLFormElement;
const inputEl = document.getElementById("input") as HTMLTextAreaElement;
const btnSend = document.getElementById("btn-send") as HTMLButtonElement;
const btnNewChat = document.getElementById("btn-new-chat")!;
const backendStatus = document.getElementById("backend-status")!;

let chats: Chat[] = [];
let activeChatId: string | null = null;
let streaming = false;
let conversationLoading = false;
/** Prevents double-submit before async createChat / setComposerEnabled. */
let submitLock = false;
/** False until chat list (history) is loaded and rendered. */
let appReady = false;
/** Bumps when user switches chats quickly — ignore stale loadMessages. */
let conversationLoadSeq = 0;

function chatLabel(c: Chat): string {
  return c.title?.trim() || "New Chat";
}

function setChatListInteractive(interactive: boolean): void {
  for (const btn of chatListEl.querySelectorAll("button")) {
    (btn as HTMLButtonElement).disabled = !interactive;
  }
}

function renderChatList(): void {
  chatListEl.innerHTML = "";
  for (const c of chats) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = chatLabel(c);
    btn.title = chatLabel(c);
    if (c.id === activeChatId) btn.classList.add("active");
    btn.disabled = conversationLoading;
    btn.addEventListener("click", () => void selectChat(c.id));
    li.appendChild(btn);
    chatListEl.appendChild(li);
  }
}

function createConversationLoading(text: string): HTMLElement {
  const el = document.createElement("div");
  el.id = "conversation-loading";
  el.className = "panel-loading main-loading conversation-loading";
  el.setAttribute("aria-busy", "true");
  el.innerHTML = `
    <span class="spinner" aria-hidden="true"></span>
    <span class="panel-loading-text"></span>
  `;
  el.querySelector(".panel-loading-text")!.textContent = text;
  return el;
}

function showConversationLoading(text = "Loading conversation…"): void {
  conversationLoading = true;
  clearMessages();
  messagesEl.appendChild(createConversationLoading(text));
  setChatListInteractive(false);
  setComposerEnabled(false);
}

function hideConversationLoading(): void {
  conversationLoading = false;
  document.getElementById("conversation-loading")?.remove();
  setChatListInteractive(true);
  if (appReady && !streaming && !submitLock) {
    setComposerEnabled(true);
  }
}

function renderAssistantTurn(m: UiMessage): HTMLElement {
  const sequential = createSequentialTurn();
  const segments = resolveAssistantSegments(m);
  if (segments.length) {
    sequential.renderSegments(segments);
  }
  return sequential.root;
}

function renderMessage(m: UiMessage): HTMLElement {
  if (m.role === "assistant" && resolveAssistantSegments(m).length > 0) {
    return renderAssistantTurn(m);
  }

  const div = document.createElement("div");
  div.className = `msg ${m.role}`;
  if (m.collapsed) div.classList.add("collapsed");
  div.textContent = m.content;
  return div;
}

function beginAssistantTurn(): SequentialTurn {
  const hint = messagesEl.querySelector(".empty-hint");
  if (hint) hint.remove();
  document.getElementById("conversation-loading")?.remove();

  const sequential = createSequentialTurn(scrollMessagesToBottom);
  messagesEl.appendChild(sequential.root);
  scrollMessagesToBottom();
  return sequential;
}

function clearMessages(): void {
  messagesEl.innerHTML = "";
}

type SidebarState = "loading" | "ready" | "error";

function setSidebarHistoryState(state: SidebarState): void {
  chatListWrapEl.dataset.state = state;
}

function revealSidebarHistory(): void {
  setSidebarHistoryState("ready");
  sidebarLoadingEl.remove();
}

function setMainAreaLoading(loading: boolean, text?: string): void {
  if (text) {
    const label = mainLoadingEl.querySelector(".panel-loading-text");
    if (label) label.textContent = text;
  }
  mainLoadingEl.style.display = loading ? "" : "none";
}

function setMainLoadingText(text: string): void {
  const label = mainLoadingEl.querySelector(".panel-loading-text");
  if (label) label.textContent = text;
}

function setAppReady(ready: boolean): void {
  appReady = ready;
  appEl.classList.toggle("is-booting", !ready);
  composer.classList.toggle("is-locked", !ready);
  if (ready) {
    mainLoadingEl.remove();
  }
}

function showHint(text: string): void {
  clearMessages();
  const p = document.createElement("p");
  p.className = "empty-hint";
  p.textContent = text;
  messagesEl.appendChild(p);
}

function appendUserBubble(text: string): void {
  const hint = messagesEl.querySelector(".empty-hint");
  if (hint) hint.remove();
  document.getElementById("conversation-loading")?.remove();
  messagesEl.appendChild(renderMessage({ role: "user", content: text }));
}

function scrollMessagesToBottom(): void {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function showError(message: string): void {
  const el = document.createElement("div");
  el.className = "error-banner";
  el.textContent = message;
  messagesEl.appendChild(el);
}

async function loadMessages(chatId: string): Promise<void> {
  const msgs = await getMessages(chatId);
  clearMessages();
  if (msgs.length === 0) {
    showHint("Send a message to start.");
    return;
  }
  for (const m of msgs) {
    if (m.role === "system" && m.collapsed) continue;
    messagesEl.appendChild(renderMessage(m));
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function selectChat(chatId: string): Promise<void> {
  if (!appReady || streaming || submitLock || conversationLoading) return;
  if (chatId === activeChatId && !document.getElementById("conversation-loading")) {
    return;
  }

  activeChatId = chatId;
  renderChatList();

  const seq = ++conversationLoadSeq;
  showConversationLoading("Loading conversation…");

  try {
    await loadMessages(chatId);
    if (seq !== conversationLoadSeq) return;
  } catch (e) {
    if (seq !== conversationLoadSeq) return;
    clearMessages();
    showHint("Failed to load messages.");
    showError(e instanceof Error ? e.message : String(e));
  } finally {
    if (seq === conversationLoadSeq) {
      hideConversationLoading();
    }
  }
}

async function refreshChats(selectId?: string): Promise<void> {
  chats = await listChats();
  if (selectId) activeChatId = selectId;
  else if (activeChatId && !chats.some((c) => c.id === activeChatId)) {
    activeChatId = chats[0]?.id ?? null;
  }
  renderChatList();
}

async function onNewChat(): Promise<void> {
  if (!appReady || streaming || submitLock || conversationLoading) return;
  submitLock = true;
  setComposerEnabled(false);
  try {
    const chat = await createChat(null);
    activeChatId = chat.id;
    await refreshChats(chat.id);
    clearMessages();
    showHint("Send a message to start.");
    inputEl.focus();
  } finally {
    submitLock = false;
    setComposerEnabled(true);
  }
}

function setComposerEnabled(enabled: boolean): void {
  const on = appReady && enabled && !conversationLoading;
  streaming = appReady && !enabled && !conversationLoading;
  inputEl.disabled = !on;
  btnSend.disabled = !on;
  btnNewChat.disabled = !on || conversationLoading;
  composer.classList.toggle("is-locked", !on);
}

async function handleSend(): Promise<void> {
  const text = inputEl.value.trim();
  if (!appReady || !text || streaming || submitLock || conversationLoading) return;

  submitLock = true;
  setComposerEnabled(false);

  let chatId = activeChatId;
  try {
    if (!chatId) {
      const chat = await createChat(text.slice(0, 80));
      chatId = chat.id;
      activeChatId = chatId;
      await refreshChats(chatId);
      clearMessages();
    }

    appendUserBubble(text);
    inputEl.value = "";

    const turn = beginAssistantTurn();

    const onEvent = (ev: SseEvent) => {
      if (
        ev.type === "tool_use" ||
        ev.type === "tool_result" ||
        ev.type === "thinking" ||
        ev.type === "thinking_delta" ||
        ev.type === "tool_input_delta" ||
        ev.type === "text_delta"
      ) {
        turn.handleEvent(ev);
      } else if (ev.type === "usage") {
        turn.root.dataset.cost = `$${ev.cost_usd.toFixed(4)}`;
      } else if (ev.type === "error") {
        showError(ev.message);
      }
    };

    await streamMessage(chatId, text, onEvent);
    turn.finish();
    await refreshChats(chatId);
  } catch (err) {
    messagesEl
      .querySelector(".msg.assistant.streaming")
      ?.classList.remove("streaming");
    showError(err instanceof Error ? err.message : String(err));
  } finally {
    submitLock = false;
    setComposerEnabled(true);
    inputEl.focus();
  }
}

composer.onsubmit = (e) => {
  e.preventDefault();
  void handleSend();
};

btnNewChat.onclick = () => {
  void onNewChat().catch((err) =>
    showError(err instanceof Error ? err.message : String(err)),
  );
};

inputEl.onkeydown = (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    void handleSend();
  }
};

let initStarted = false;

async function init(): Promise<void> {
  if (initStarted) return;
  initStarted = true;

  appReady = false;
  setComposerEnabled(false);
  setSidebarHistoryState("loading");
  setMainAreaLoading(true, "Connecting to backend…");

  try {
    const health = await checkHealth();
    backendStatus.textContent =
      health.status === "ok"
        ? `Backend OK · ${health.platform_db ?? "—"}`
        : `Backend degraded`;
    backendStatus.className = `backend-status ${health.status === "ok" ? "ok" : "err"}`;
  } catch {
    backendStatus.textContent = "Backend unreachable (start uvicorn :8000)";
    backendStatus.className = "backend-status err";
  }

  setMainLoadingText("Loading chat history…");

  try {
    await refreshChats();
    revealSidebarHistory();

    setAppReady(true);
    setMainAreaLoading(false);

    if (activeChatId) {
      await selectChat(activeChatId);
    } else {
      setComposerEnabled(true);
      showHint("New Chat or pick a session from History.");
    }
  } catch (e) {
    setSidebarHistoryState("error");
    sidebarLoadingEl.remove();
    renderChatList();
    mainLoadingEl.remove();
    clearMessages();
    showHint("Could not load chat history.");
    backendStatus.className = "backend-status err";
    showError(e instanceof Error ? e.message : String(e));
  }
}

void init();
