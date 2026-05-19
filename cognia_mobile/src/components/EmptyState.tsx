import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Colors, Spacing, Typography } from '../constants/theme';

interface Props {
  message: string;
}

export function EmptyState({ message }: Props) {
  return (
    <View style={styles.container}>
      <Text style={styles.text}>{message}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: Spacing.xl,
  },
  text: {
    fontFamily: Typography.fontFamily,
    fontSize: Typography.md,
    color: Colors.muted,
    textAlign: 'center',
    lineHeight: Typography.lineHeight,
  },
});
