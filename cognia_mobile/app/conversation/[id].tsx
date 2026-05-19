import { useLocalSearchParams, useNavigation } from 'expo-router';
import React, { useEffect, useRef } from 'react';
import {
  FlatList,
  SafeAreaView,
  StyleSheet,
  View,
} from 'react-native';
import { streamMessage } from '../../src/api/chatClient';
import { InputBar } from '../../src/components/InputBar';
import { LoadingDots } from '../../src/components/LoadingDots';
import { MessageBubble } from '../../src/components/MessageBubble';
import { Colors } from '../../src/constants/theme';
import { useMessages } from '../../src/hooks/useMessages';
import { useSettings } from '../../src/hooks/useSettings';

export default function ChatScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const navigation = useNavigation();
  const { settings } = useSettings();
  const {
    messages,
    isSending,
    setIsSending,
    addMessage,
    addStreamingPlaceholder,
    appendToken,
    finalizeMessage,
    setTitle,
    abortRef,
  } = useMessages(id);
  const listRef = useRef<FlatList>(null);
  const isFirstMessage = messages.length === 0;

  useEffect(() => {
    if (messages.length > 0) {
      navigation.setOptions({ title: messages[0].content.slice(0, 40) });
    }
  }, [messages, navigation]);

  const handleSend = async (text: string) => {
    if (isSending) return;

    await addMessage('user', text);

    if (isFirstMessage) {
      const title = text.slice(0, 40);
      navigation.setOptions({ title });
      await setTitle(title);
    }

    setIsSending(true);
    abortRef.current = new AbortController();

    // Insert a placeholder immediately so the user sees the streaming response appear
    const placeholder = await addStreamingPlaceholder();
    let accumulatedContent = '';

    await streamMessage(
      text,
      settings.serverUrl,
      (token) => {
        accumulatedContent += token;
        appendToken(placeholder.id, token);
      },
      (final) => {
        // On done, build the stage string encoding sub_model + latency
        // Format: "SUB_MODEL·latency_ms" — parsed by MessageBubble for display
        const stage = final.sub_model && final.latency_ms != null
          ? `${final.sub_model}·${final.latency_ms}`
          : final.sub_model;

        // Use the authoritative text from the server if it sent one,
        // otherwise keep what we accumulated via tokens
        const finalContent = final.text ?? accumulatedContent;

        finalizeMessage(placeholder.id, finalContent, stage).catch(() => undefined);
        setIsSending(false);
      },
      (err) => {
        const isAbort = err.name === 'AbortError';
        if (!isAbort) {
          finalizeMessage(
            placeholder.id,
            '[!] No se pudo conectar al servidor.',
            undefined
          ).catch(() => undefined);
        }
        setIsSending(false);
      },
      abortRef.current.signal
    );
  };

  useEffect(() => {
    if (messages.length > 0) {
      listRef.current?.scrollToEnd({ animated: true });
    }
  }, [messages.length]);

  return (
    <SafeAreaView style={styles.container}>
      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => <MessageBubble message={item} />}
        contentContainerStyle={styles.list}
        onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: false })}
      />
      {isSending && (
        <View>
          <LoadingDots />
        </View>
      )}
      <InputBar onSend={handleSend} disabled={isSending} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bg,
  },
  list: {
    paddingVertical: 8,
    flexGrow: 1,
  },
});
