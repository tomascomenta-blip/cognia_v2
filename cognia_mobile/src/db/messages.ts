import type { SQLiteDatabase } from 'expo-sqlite';
import type { Message, Role } from '../types';
import { generateId } from './schema';

interface MessageRow {
  id: string;
  conversation_id: string;
  role: Role;
  content: string;
  stage: string | null;
  created_at: number;
}

function rowToMessage(row: MessageRow): Message {
  return {
    id: row.id,
    conversationId: row.conversation_id,
    role: row.role,
    content: row.content,
    stage: row.stage ?? undefined,
    createdAt: row.created_at,
  };
}

export async function listMessages(
  db: SQLiteDatabase,
  conversationId: string
): Promise<Message[]> {
  const rows = await db.getAllAsync<MessageRow>(
    'SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC',
    [conversationId]
  );
  return rows.map(rowToMessage);
}

export async function insertMessage(
  db: SQLiteDatabase,
  conversationId: string,
  role: Role,
  content: string,
  stage?: string
): Promise<Message> {
  const id = generateId();
  const now = Date.now();
  await db.runAsync(
    'INSERT INTO messages (id, conversation_id, role, content, stage, created_at) VALUES (?, ?, ?, ?, ?, ?)',
    [id, conversationId, role, content, stage ?? null, now]
  );
  return { id, conversationId, role, content, stage, createdAt: now };
}
