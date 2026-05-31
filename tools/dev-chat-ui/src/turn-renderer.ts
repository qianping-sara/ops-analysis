import { setMarkdownContent } from "./markdown";
import type { ActivityStep, SseEvent, TurnSegment, UiMessage } from "./types";

export interface SequentialTurn {
  root: HTMLElement;
  handleEvent(ev: SseEvent): void;
  renderSegments(segments: TurnSegment[]): void;
  finish(): void;
}

function toolLabel(tool: string): string {
  if (tool === "Skill" || tool === "ToolSearch") return "读取技能";
  if (tool.includes("run_query")) return "查询数据库";
  if (tool.includes("list_tables")) return "列出数据表";
  if (tool.includes("describe_table")) return "查看表结构";
  if (tool.startsWith("mcp__")) return tool.replace(/^mcp__/, "").replace(/__/g, " · ");
  return tool;
}

function stepIcon(kind: string, tool?: string): string {
  if (kind === "thinking") return "🧠";
  if (tool === "Skill" || tool === "ToolSearch") return "📎";
  if (tool?.includes("postgres") || tool?.includes("mcp")) return "🗄";
  return "⚙";
}

function formatBody(text: string): string {
  const t = text.trim();
  if (!t) return "(empty)";
  if (t.length > 8000) return `${t.slice(0, 8000)}\n…(truncated)`;
  return t;
}

function setStepLoading(details: HTMLDetailsElement, loading: boolean): void {
  details.classList.toggle("is-running", loading);
}

function createStepElement(title: string, body: string, opts?: { error?: boolean }): HTMLDetailsElement {
  const details = document.createElement("details");
  details.className = "activity-step";
  if (opts?.error) details.classList.add("is-error");

  const summary = document.createElement("summary");
  summary.className = "activity-step-summary";
  summary.innerHTML =
    '<span class="activity-step-spinner" aria-hidden="true"></span><span class="activity-step-title"></span>';
  summary.querySelector(".activity-step-title")!.textContent = title;
  details.appendChild(summary);

  const bodyEl = document.createElement("pre");
  bodyEl.className = "activity-step-body";
  bodyEl.textContent = formatBody(body);
  details.appendChild(bodyEl);

  return details;
}

export function resolveAssistantSegments(m: UiMessage): TurnSegment[] {
  if (m.segments?.length) return m.segments;
  if (m.activity?.length) {
    return legacyActivityToSegments(m.activity, m.content || "");
  }
  if (m.content?.trim()) {
    return [{ kind: "text", content: m.content }];
  }
  return [];
}

export function legacyActivityToSegments(
  activity: ActivityStep[],
  trailingText: string,
): TurnSegment[] {
  const segments: TurnSegment[] = [];
  for (const a of activity) {
    if (a.kind === "tool_use") {
      segments.push({ ...a });
    } else if (a.kind === "thinking") {
      segments.push({ kind: "thinking", content: a.content });
    } else if (a.kind === "tool_result") {
      segments.push({ ...a });
    }
  }
  if (trailingText.trim()) {
    segments.push({ kind: "text", content: trailingText });
  }
  return segments;
}

export function createSequentialTurn(onScroll?: () => void): SequentialTurn {
  const root = document.createElement("div");
  root.className = "assistant-turn";

  const toolSteps = new Map<string, HTMLDetailsElement>();
  let thinkingEl: HTMLDetailsElement | null = null;
  let thinkingText = "";
  let currentTextEl: HTMLElement | null = null;
  let currentMarkdown = "";
  let mdScheduled = false;

  function scroll(): void {
    onScroll?.();
  }

  function scheduleMarkdown(): void {
    if (!currentTextEl) return;
    if (mdScheduled) return;
    mdScheduled = true;
    requestAnimationFrame(() => {
      mdScheduled = false;
      if (currentTextEl) {
        setMarkdownContent(currentTextEl, currentMarkdown);
        scroll();
      }
    });
  }

  function closeThinkingLoading(): void {
    if (thinkingEl) setStepLoading(thinkingEl, false);
  }

  function closeTextStreaming(): void {
    currentTextEl?.classList.remove("streaming");
  }

  function startNewTextSegment(): HTMLElement {
    closeTextStreaming();
    closeThinkingLoading();
    currentMarkdown = "";
    const el = document.createElement("div");
    el.className = "msg assistant markdown-body streaming";
    root.appendChild(el);
    currentTextEl = el;
    scroll();
    return el;
  }

  function appendThinkingChunk(chunk: string): void {
    thinkingText += chunk;
    if (!thinkingEl) {
      thinkingEl = createStepElement("🧠 推理过程", "");
      root.appendChild(thinkingEl);
      setStepLoading(thinkingEl, true);
      scroll();
    }
    const body = thinkingEl.querySelector(".activity-step-body");
    if (body) body.textContent = formatBody(thinkingText);
  }

  function appendToolUse(tool: string, toolUseId: string | undefined, input: unknown): void {
    closeTextStreaming();
    currentTextEl = null;
    closeThinkingLoading();

    const id = toolUseId || `${tool}-${toolSteps.size}`;
    let body = "";
    try {
      body = JSON.stringify(input, null, 2);
    } catch {
      body = String(input);
    }
    const title = `${stepIcon("tool", tool)} ${toolLabel(tool)}`;
    const el = createStepElement(title, body || "(no input)");
    el.dataset.toolUseId = id;
    setStepLoading(el, true);
    root.appendChild(el);
    toolSteps.set(id, el);
    scroll();
  }

  function applyToolResult(toolUseId: string, content: string, isError: boolean): void {
    const existing = toolSteps.get(toolUseId);
    if (existing) {
      const body = existing.querySelector(".activity-step-body");
      if (body) {
        const prev = body.textContent?.trim() || "";
        const prefix =
          prev && prev !== "(empty)" ? `${prev}\n\n--- result ---\n` : "--- result ---\n";
        body.textContent = formatBody(`${prefix}${content}`);
      }
      if (isError) existing.classList.add("is-error");
      setStepLoading(existing, false);
      scroll();
      return;
    }
    const el = createStepElement(`${stepIcon("tool")} 工具结果`, content, { error: isError });
    el.dataset.toolUseId = toolUseId;
    root.appendChild(el);
    toolSteps.set(toolUseId, el);
    scroll();
  }

  function renderToolSegment(seg: Extract<TurnSegment, { kind: "tool_use" }>): void {
    appendToolUse(seg.tool, seg.tool_use_id, seg.input);
    const id = seg.tool_use_id || "";
    if (seg.result !== undefined && id) {
      applyToolResult(id, seg.result, Boolean(seg.is_error));
    }
  }

  return {
    root,
    handleEvent(ev: SseEvent) {
      if (ev.type === "thinking_delta" || ev.type === "thinking") {
        appendThinkingChunk(ev.content);
      } else if (ev.type === "tool_use") {
        appendToolUse(ev.tool, ev.tool_use_id, ev.input);
      } else if (ev.type === "tool_result") {
        applyToolResult(ev.tool_use_id, ev.content, Boolean(ev.is_error));
      } else if (ev.type === "tool_input_delta") {
        const last = [...toolSteps.values()].pop();
        if (last?.classList.contains("is-running")) {
          const body = last.querySelector(".activity-step-body");
          if (body) {
            const prev = body.textContent === "(empty)" ? "" : body.textContent || "";
            body.textContent = formatBody(`${prev}${ev.partial_json}`);
          }
        }
      } else if (ev.type === "text_delta") {
        if (!currentTextEl) startNewTextSegment();
        currentMarkdown += ev.content;
        scheduleMarkdown();
      }
    },
    renderSegments(segments: TurnSegment[]) {
      root.innerHTML = "";
      toolSteps.clear();
      thinkingEl = null;
      thinkingText = "";
      currentTextEl = null;
      currentMarkdown = "";

      for (const seg of segments) {
        if (seg.kind === "thinking") {
          thinkingText = seg.content;
          thinkingEl = createStepElement("🧠 推理过程", seg.content);
          root.appendChild(thinkingEl);
        } else if (seg.kind === "tool_use") {
          renderToolSegment(seg);
        } else if (seg.kind === "tool_result") {
          applyToolResult(seg.tool_use_id, seg.content, Boolean(seg.is_error));
        } else if (seg.kind === "text") {
          closeTextStreaming();
          currentTextEl = null;
          const el = document.createElement("div");
          el.className = "msg assistant markdown-body";
          root.appendChild(el);
          setMarkdownContent(el, seg.content);
        }
      }
    },
    finish() {
      closeThinkingLoading();
      for (const el of toolSteps.values()) {
        setStepLoading(el, false);
      }
      if (currentTextEl && currentMarkdown) {
        setMarkdownContent(currentTextEl, currentMarkdown);
      }
      closeTextStreaming();
    },
  };
}
