import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Colors, Spacing, Typography } from '../constants/theme';
import type { Conversation } from '../types';

interface Props {
  conversation: Conversation;
  onPress: () => void;
  onLongPress: () => void;
}

export function ConversationRow({ conversation, onPress, onLongPress }: Props) {
  const date = new Date(conversation.updatedAt);
  const dateLabel = date.toLocaleDateString('es', {
    month: 'short',
    day: 'numeric',
  });

  return (
    <Pressable onPress={onPress} onLongPress={onLongPress} style={styles.row}>
      <View style={styles.content}>
        <Text style={styles.title} numberOfLines={1}>{conversation.title}</Text>
        <Text style={styles.date}>{dateLabel}</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.md,
  },
  content: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  title: {
    fontFamily: Typography.fontFamily,
    fontSize: Typography.md,
    color: Colors.text,
    flex: 1,
    marginRight: Spacing.md,
  },
  date: {
    fontFamily: Typography.fontFamily,
    fontSize: Typography.sm,
    color: Colors.muted,
  },
});
