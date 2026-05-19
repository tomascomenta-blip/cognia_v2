import { router } from 'expo-router';
import React, { useEffect } from 'react';
import {
  Alert,
  FlatList,
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { ConversationRow } from '../src/components/ConversationRow';
import { EmptyState } from '../src/components/EmptyState';
import { Colors, Spacing, Typography } from '../src/constants/theme';
import { useConversations } from '../src/hooks/useConversations';
import { useSettings } from '../src/hooks/useSettings';
import type { Conversation } from '../src/types';

export default function ConversationListScreen() {
  const { settings, isLoading: settingsLoading } = useSettings();
  const { conversations, newConversation, removeConversation } = useConversations();

  useEffect(() => {
    if (!settingsLoading && !settings.serverUrl) {
      router.replace('/settings');
    }
  }, [settingsLoading, settings.serverUrl]);

  const handleNew = async () => {
    const conv = await newConversation();
    router.push(`/conversation/${conv.id}`);
  };

  const handleLongPress = (conv: Conversation) => {
    Alert.alert(
      'Eliminar conversacion',
      `"${conv.title}"`,
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Eliminar',
          style: 'destructive',
          onPress: () => removeConversation(conv.id),
        },
      ]
    );
  };

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.headerActions}>
        <Pressable onPress={() => router.push('/settings')} style={styles.headerBtn}>
          <Text style={styles.headerBtnText}>config</Text>
        </Pressable>
        <Pressable onPress={handleNew} style={styles.headerBtn}>
          <Text style={styles.headerBtnText}>+ nuevo</Text>
        </Pressable>
      </View>
      <FlatList
        data={conversations}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => (
          <ConversationRow
            conversation={item}
            onPress={() => router.push(`/conversation/${item.id}`)}
            onLongPress={() => handleLongPress(item)}
          />
        )}
        ListEmptyComponent={
          <EmptyState message="Sin conversaciones.&#10;Presiona + nuevo para empezar." />
        }
        contentContainerStyle={conversations.length === 0 ? styles.emptyList : undefined}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bg,
  },
  headerActions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: Spacing.sm,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  headerBtn: {
    paddingHorizontal: Spacing.sm,
    paddingVertical: Spacing.xs,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 2,
  },
  headerBtnText: {
    fontFamily: Typography.fontFamily,
    fontSize: Typography.sm,
    color: Colors.text,
  },
  emptyList: {
    flex: 1,
  },
});
