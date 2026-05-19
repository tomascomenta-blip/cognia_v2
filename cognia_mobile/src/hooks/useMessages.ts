import { useSQLiteContext } from 'expo-sqlite';
import { useCallback, useEffect, useRef, useState } from 'react';
import { updateConversationTimestamp, updateConversationTitle } from '../db/conversations';
import { insertMessage, listMessages } from '../db/messages';
import type { Message } from '../types';

export function useMessages(conversationId: string) {
  const db = useSQLiteContext();
  const [messages, setMessages] = useState<Message[]>([]);
  const [isSending, setIsSending] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    listMessages(db, conversationId).then(setMessages);
    return () => { abortRef.current?.abort(); };
  }, [db, conversationId]);

  const addMessage = useCallback(
    async (role: 'user' | 'assistant', content: string, stage?: string) => {
      const msg = await insertMessage(db, conversationId, role, content, stage);
      await updateConversationTimestamp(db, conversationId);
      setMessages((prev) => [...prev, msg]);
      return msg;
    },
    [db, conversationId]
  );

  const setTitle = useCallback(
    async (title: string) => {
      await updateConversationTitle(db, conversationId, title);
    },
    [db, conversationId]
  );

  return { messages, isSending, setIsSending, addMessage, setTitle, abortRef };
}
