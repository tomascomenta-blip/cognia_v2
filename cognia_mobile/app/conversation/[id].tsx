import { useLocalSearchParams, useNavigation } from 'expo-router';
import React, { useEffect, useRef } from 'react';
import {
  FlatList,
  SafeAreaView,
  StyleSheet,
  View,
} from 'react-native';
import { sendMessage } from '../../src/api/chatClient';
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
  const { messages, isSending, setIsSending, addMessage, setTitle, abortRef } =
    useMessages(id);
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

    try {
      const result = await sendMessage(text, settings.serverUrl, abortRef.current.signal);
      const content = result.error
        ? `[error] ${result.error}`
        : result.response;
      await addMessage('assistant', content, result.stage);
    } catch (err) {
      const isAbort = err instanceof Error && err.name === 'AbortError';
      if (!isAbort) {
        await addMessage('assistant', 'No se pudo conectar al servidor.');
      }
    } finally {
      setIsSending(false);
    }
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
