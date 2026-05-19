import { useSQLiteContext } from 'expo-sqlite';
import { useCallback, useEffect, useRef, useState } from 'react';
import { updateConversationTimestamp, updateConversationTitle } from '../db/conversations';
import { insertMessage, listMessages, updateMessageContent } from '../db/messages';
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

  // Creates an empty assistant placeholder, returns its id.
  // Use appendToken to stream content into it, then finalizeMessage to persist
  // the final content and metadata.
  const addStreamingPlaceholder = useCallback(async (): Promise<Message> => {
    const msg = await insertMessage(db, conversationId, 'assistant', '', undefined);
    await updateConversationTimestamp(db, conversationId);
    setMessages((prev) => [...prev, msg]);
    return msg;
  }, [db, conversationId]);

  // Appends a token to an in-flight streaming message (UI only, no DB write).
  // The DB is updated once in finalizeMessage to avoid per-token writes.
  const appendToken = useCallback((messageId: string, token: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId ? { ...m, content: m.content + token } : m
      )
    );
  }, []);

  // Commits the final streamed content and metadata to SQLite.
  const finalizeMessage = useCallback(
    async (messageId: string, finalContent: string, stage?: string) => {
      await updateMessageContent(db, messageId, finalContent, stage);
      await updateConversationTimestamp(db, conversationId);
      // Sync UI state with persisted values
      setMessages((prev) =>
        prev.map((m) =>
          m.id === messageId ? { ...m, content: finalContent, stage } : m
        )
      );
    },
    [db, conversationId]
  );

  const setTitle = useCallback(
    async (title: string) => {
      await updateConversationTitle(db, conversationId, title);
    },
    [db, conversationId]
  );

  return {
    messages,
    isSending,
    setIsSending,
    addMessage,
    addStreamingPlaceholder,
    appendToken,
    finalizeMessage,
    setTitle,
    abortRef,
  };
}
