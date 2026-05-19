import React, { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { Colors, Spacing, Typography } from '../constants/theme';

interface Props {
  onSend: (text: string) => void;
  disabled: boolean;
}

export function InputBar({ onSend, disabled }: Props) {
  const [text, setText] = useState('');

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText('');
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={80}
    >
      <View style={styles.container}>
        <TextInput
          style={styles.input}
          value={text}
          onChangeText={setText}
          onSubmitEditing={handleSend}
          placeholder="Escribe un mensaje"
          placeholderTextColor={Colors.muted}
          multiline
          returnKeyType="send"
          blurOnSubmit={false}
          editable={!disabled}
        />
        <Pressable
          onPress={handleSend}
          disabled={disabled || !text.trim()}
          style={[styles.sendBtn, (disabled || !text.trim()) && styles.sendBtnDisabled]}
        >
          <Text style={styles.sendLabel}>&gt;</Text>
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    backgroundColor: Colors.surface,
    borderTopWidth: 1,
    borderTopColor: Colors.border,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    gap: Spacing.sm,
  },
  input: {
    flex: 1,
    backgroundColor: Colors.inputBg,
    color: Colors.text,
    fontFamily: Typography.fontFamily,
    fontSize: Typography.md,
    lineHeight: Typography.lineHeight,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 2,
    maxHeight: 120,
  },
  sendBtn: {
    width: 40,
    height: 40,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 2,
  },
  sendBtnDisabled: {
    opacity: 0.3,
  },
  sendLabel: {
    fontFamily: Typography.fontFamily,
    fontSize: Typography.lg,
    color: Colors.text,
  },
});
