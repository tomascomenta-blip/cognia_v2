import { router } from 'expo-router';
import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { checkReady } from '../src/api/chatClient';
import { Colors, Spacing, Typography } from '../src/constants/theme';
import { useSettings } from '../src/hooks/useSettings';
import type { ReadyResponse } from '../src/types';

function isValidUrl(url: string): boolean {
  return /^https?:\/\/.+/.test(url.trim());
}

type TestState = 'idle' | 'testing' | 'shards' | 'ollama' | 'setup_required' | 'fail';

function readyLabel(state: TestState): string {
  switch (state) {
    case 'idle':     return 'probar conexion';
    case 'testing':  return 'probando...';
    case 'shards':   return '[ok] Cognia listo (shards)';
    case 'ollama':   return '[ok] Cognia listo (Ollama)';
    case 'setup_required': return '[--] Servidor requiere configuracion';
    case 'fail':     return '[!] Servidor no disponible';
  }
}

function resolveTestState(ready: ReadyResponse | null): TestState {
  if (!ready) return 'fail';
  if (ready.status === 'setup_required') return 'setup_required';
  if (ready.inference === 'shards') return 'shards';
  if (ready.inference === 'ollama') return 'ollama';
  return 'fail';
}

export default function SettingsScreen() {
  const { settings, saveSettings, isLoading } = useSettings();
  const [url, setUrl] = useState('');
  const [testState, setTestState] = useState<TestState>('idle');
  const [urlError, setUrlError] = useState('');

  useEffect(() => {
    if (!isLoading) setUrl(settings.serverUrl);
  }, [isLoading, settings.serverUrl]);

  const handleSave = async () => {
    const trimmed = url.trim();
    if (!isValidUrl(trimmed)) {
      setUrlError('La URL debe comenzar con http:// o https://');
      return;
    }
    setUrlError('');
    await saveSettings({ serverUrl: trimmed });
    router.replace('/');
  };

  const handleTest = async () => {
    const trimmed = url.trim();
    if (!isValidUrl(trimmed)) {
      setUrlError('La URL debe comenzar con http:// o https://');
      return;
    }
    setUrlError('');
    setTestState('testing');
    const ready = await checkReady(trimmed);
    setTestState(resolveTestState(ready));
  };

  if (isLoading) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator color={Colors.text} />
      </SafeAreaView>
    );
  }

  const testLabelStyle = [
    styles.testLabel,
    testState === 'shards' || testState === 'ollama' ? styles.testOk : null,
    testState === 'fail' ? styles.testFail : null,
  ];

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.form} keyboardShouldPersistTaps="handled">
        <Text style={styles.label}>URL del servidor Cognia</Text>
        <Text style={styles.hint}>
          Mismo Wi-Fi que tu PC: http://&lt;IP-de-tu-PC&gt;:8765{'\n'}
          Emulador Android: http://10.0.2.2:8765{'\n\n'}
          Para encontrar la IP de tu PC:{'\n'}
          Windows: ipconfig (campo "IPv4"){'\n'}
          Mac/Linux: ifconfig | grep inet{'\n\n'}
          Inicia el backend con:{'\n'}
          python cognia_desktop_api.py
        </Text>
        <TextInput
          style={[styles.input, urlError ? styles.inputError : null]}
          value={url}
          onChangeText={(v) => {
            setUrl(v);
            setUrlError('');
            setTestState('idle');
          }}
          placeholder="http://192.168.1.X:8765"
          placeholderTextColor={Colors.muted}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
        />
        {urlError ? <Text style={styles.errorText}>{urlError}</Text> : null}

        <View style={styles.actions}>
          <Pressable
            onPress={handleTest}
            style={styles.btn}
            disabled={testState === 'testing'}
          >
            <Text style={testLabelStyle}>{readyLabel(testState)}</Text>
          </Pressable>
          <Pressable onPress={handleSave} style={[styles.btn, styles.btnPrimary]}>
            <Text style={styles.btnText}>guardar</Text>
          </Pressable>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bg,
  },
  form: {
    padding: Spacing.lg,
    gap: Spacing.md,
  },
  label: {
    fontFamily: Typography.fontFamily,
    fontSize: Typography.md,
    color: Colors.text,
  },
  hint: {
    fontFamily: Typography.fontFamily,
    fontSize: Typography.sm,
    color: Colors.muted,
    lineHeight: Typography.lineHeight,
  },
  input: {
    backgroundColor: Colors.inputBg,
    color: Colors.text,
    fontFamily: Typography.fontFamily,
    fontSize: Typography.md,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 2,
  },
  inputError: {
    borderColor: Colors.danger,
  },
  errorText: {
    fontFamily: Typography.fontFamily,
    fontSize: Typography.sm,
    color: Colors.danger,
  },
  actions: {
    flexDirection: 'row',
    gap: Spacing.sm,
    marginTop: Spacing.sm,
  },
  btn: {
    flex: 1,
    paddingVertical: Spacing.sm,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 2,
    alignItems: 'center',
  },
  btnPrimary: {
    borderColor: Colors.text,
  },
  btnText: {
    fontFamily: Typography.fontFamily,
    fontSize: Typography.sm,
    color: Colors.text,
  },
  testLabel: {
    fontFamily: Typography.fontFamily,
    fontSize: Typography.sm,
    color: Colors.text,
  },
  testOk: {
    color: Colors.text,
  },
  testFail: {
    color: Colors.danger,
  },
});
