export type Role = 'user' | 'assistant';

export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
}

export interface Message {
  id: string;
  conversationId: string;
  role: Role;
  content: string;
  // sub_model is stored in the stage column (existing schema, no migration needed)
  stage?: string;
  createdAt: number;
}

export interface AppSettings {
  serverUrl: string;
}

export interface ChatApiResponse {
  text: string;
  sub_model: string;
  confidence: number;
  latency_ms: number;
  mode: string;
  route_reason: string;
}

export interface ReadyResponse {
  status: 'ready' | 'setup_required';
  inference: 'shards' | 'ollama' | 'none';
}

export interface StreamToken {
  token?: string;
  done: boolean;
  // fields present on the final done=true event
  text?: string;
  sub_model?: string;
  confidence?: number;
  latency_ms?: number;
  mode?: string;
  route_reason?: string;
}
