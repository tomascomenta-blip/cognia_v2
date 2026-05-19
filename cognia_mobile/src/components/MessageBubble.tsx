import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Colors, Spacing, Typography } from '../constants/theme';
import type { Message } from '../types';

interface Props {
  message: Message;
}

// stage is stored as "SUB_MODEL·latency_ms" e.g. "LOGOS·420"
// We display it as "LOGOS · 420ms"
function parseStageLabel(stage: string | undefined): string | null {
  if (!stage) return null;
  const parts = stage.split('·');
  if (parts.length === 2) {
    const [model, ms] = parts;
    return `${model.trim()} · ${ms.trim()}ms`;
  }
  return stage;
}

export function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user';
  const stageLabel = isUser ? null : parseStageLabel(message.stage);

  return (
    <View style={[styles.bubble, isUser ? styles.userBubble : styles.aiBubble]}>
      {!isUser && (
        <Text style={styles.roleLabel}>cognia</Text>
      )}
      <Text style={styles.content}>{message.content}</Text>
      {stageLabel && (
        <Text style={styles.stageLabel}>{stageLabel}</Text>
      )}
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
  stageLabel: {
    fontFamily: Typography.fontFamily,
    fontSize: 11,
    color: Colors.muted,
    marginTop: Spacing.xs,
  },
});
