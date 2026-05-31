export type AgentType = "analysis";

export interface Chat {
  id: string;
  agent_type: AgentType;
  title: string | null;
  sdk_session_id: string | null;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  created_at: string;
  updated_at: string;
}

/** Chronological slice of one assistant turn (API order). */
export type TurnSegment =
  | { kind: "thinking"; content: string }
  | {
      kind: "tool_use";
      tool: string;
      tool_use_id?: string;
      input: Record<string, unknown>;
      result?: string;
      is_error?: boolean;
    }
  | { kind: "tool_result"; tool_use_id: string; content: string; is_error?: boolean }
  | { kind: "text"; content: string };

/** @deprecated Legacy shape — converted in UI if present */
export type ActivityStep =
  | { kind: "thinking"; content: string }
  | {
      kind: "tool_use";
      tool: string;
      tool_use_id?: string;
      input: Record<string, unknown>;
    }
  | {
      kind: "tool_result";
      tool_use_id: string;
      content: string;
      is_error?: boolean;
    };

export interface UiMessage {
  role: "user" | "assistant" | "system";
  content: string;
  segments?: TurnSegment[];
  tools?: { name: string; input: Record<string, unknown> }[];
  activity?: ActivityStep[];
  collapsed?: boolean;
}

export type SseEvent =
  | { type: "text_delta"; content: string }
  | { type: "thinking_delta"; content: string }
  | { type: "thinking"; content: string }
  | {
      type: "tool_use";
      tool: string;
      tool_use_id?: string;
      input: Record<string, unknown>;
    }
  | {
      type: "tool_result";
      tool_use_id: string;
      content: string;
      is_error?: boolean;
    }
  | { type: "tool_input_delta"; index?: number; partial_json: string }
  | {
      type: "usage";
      input_tokens: number;
      output_tokens: number;
      cache_read_input_tokens: number;
      cache_creation_input_tokens: number;
      cost_usd: number;
    }
  | { type: "done"; chat_id: string }
  | { type: "error"; message: string };
