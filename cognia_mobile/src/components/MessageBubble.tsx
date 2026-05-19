import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Colors, Spacing, Typography } from '../constants/theme';
import type { Message } from '../types';

interface Props {
  message: Message;
}

export function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user';

  return (
    <View style={[styles.bubble, isUser ? styles.userBubble : styles.aiBubble]}>
      {!isUser && (
        <Text style={styles.roleLabel}>cognia</Text>
      )}
      <Text style={styles.content}>{message.content}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  bubble: {
    marginHorizontal: Spacing.md,
    marginVertical: Spacing.xs,
    padding: Spacing.md,
    borderRadius: 2,
    maxWidth: '85%',
  },
  userBubble: {
    alignSelf: 'flex-end',
    backgroundColor: Colors.userBubble,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  aiBubble: {
    alignSelf: 'flex-start',
    backgroundColor: Colors.aiBubble,
  },
  roleLabel: {
    fontFamily: Typography.fontFamily,
    fontSize: Typography.sm,
    color: Colors.muted,
    marginBottom: Spacing.xs,
  },
  content: {
    fontFamily: Typography.fontFamily,
    fontSize: Typography.md,
    color: Colors.text,
    lineHeight: Typography.lineHeight,
  },
});
