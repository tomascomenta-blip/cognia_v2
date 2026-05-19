import type { SQLiteDatabase } from 'expo-sqlite';
import type { Conversation } from '../types';
import { generateId } from './schema';

interface ConversationRow {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
}

function rowToConversation(row: ConversationRow): Conversation {
  return {
    id: row.id,
    title: row.title,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export async function listConversations(db: SQLiteDatabase): Promise<Conversation[]> {
  const rows = await db.getAllAsync<ConversationRow>(
    'SELECT * FROM conversations ORDER BY updated_at DESC'
  );
  return rows.map(rowToConversation);
}

export async function createConversation(
  db: SQLiteDatabase,
  title: string
): Promise<Conversation> {
  const id = generateId();
  const now = Date.now();
  await db.runAsync(
    'INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)',
    [id, title, now, now]
  );
  return { id, title, createdAt: now, updatedAt: now };
}

export async function updateConversationTitle(
  db: SQLiteDatabase,
  id: string,
  title: string
): Promise<void> {
  await db.runAsync(
    'UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?',
    [title, Date.now(), id]
  );
}

export async function updateConversationTimestamp(
  db: SQLiteDatabase,
  id: string
): Promise<void> {
  await db.runAsync(
    'UPDATE conversations SET updated_at = ? WHERE id = ?',
    [Date.now(), id]
  );
}

export async function deleteConversation(db: SQLiteDatabase, id: string): Promise<void> {
  await db.runAsync('DELETE FROM conversations WHERE id = ?', [id]);
}
