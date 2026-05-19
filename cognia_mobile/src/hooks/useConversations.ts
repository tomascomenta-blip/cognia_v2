import { useSQLiteContext } from 'expo-sqlite';
import { useCallback, useEffect, useState } from 'react';
import {
  createConversation,
  deleteConversation,
  listConversations,
} from '../db/conversations';
import type { Conversation } from '../types';

export function useConversations() {
  const db = useSQLiteContext();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    const result = await listConversations(db);
    setConversations(result);
    setIsLoading(false);
  }, [db]);

  useEffect(() => { load(); }, [load]);

  const newConversation = useCallback(async (title = 'Nueva conversacion') => {
    const conv = await createConversation(db, title);
    setConversations((prev) => [conv, ...prev]);
    return conv;
  }, [db]);

  const removeConversation = useCallback(async (id: string) => {
    await deleteConversation(db, id);
    setConversations((prev) => prev.filter((c) => c.id !== id));
  }, [db]);

  return { conversations, isLoading, newConversation, removeConversation, reload: load };
}
