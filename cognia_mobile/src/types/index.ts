import type { Platform } from 'react-native';

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
  stage?: string;
  createdAt: number;
}

export interface AppSettings {
  serverUrl: string;
}

export interface ChatApiResponse {
  response: string;
  stage: string;
  error: string;
}
