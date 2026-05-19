import React, { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Colors, Spacing, Typography } from '../constants/theme';

const FRAMES = ['.', '..', '...'];

export function LoadingDots() {
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setFrame((f) => (f + 1) % FRAMES.length);
    }, 400);
    return () => clearInterval(id);
  }, []);

  return (
    <View style={styles.container}>
      <Text style={styles.label}>cognia</Text>
      <Text style={styles.dots}>{FRAMES[frame]}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginHorizontal: Spacing.md,
    marginVertical: Spacing.xs,
    padding: Spacing.md,
    alignSelf: 'flex-start',
  },
  label: {
    fontFamily: Typography.fontFamily,
    fontSize: Typography.sm,
    color: Colors.muted,
    marginBottom: Spacing.xs,
  },
  dots: {
    fontFamily: Typography.fontFamily,
    fontSize: Typography.md,
    color: Colors.muted,
  },
});
