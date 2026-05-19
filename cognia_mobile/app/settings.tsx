import { router } from 'expo-router';
import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { testConnection } from '../src/api/chatClient';
import { Colors, Spacing, Typography } from '../src/constants/theme';
import { useSettings } from '../src/hooks/useSettings';

function isValidUrl(url: string): boolean {
  return /^https?:\/\/.+/.test(url.trim());
}

export default function SettingsScreen() {
  const { settings, saveSettings, isLoading } = useSettings();
  const [url, setUrl] = useState('');
  const [testState, setTestState] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
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
    const ok = await testConnection(trimmed);
    setTestState(ok ? 'ok' : 'fail');
  };

  if (isLoading) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator color={Colors.text} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.form}>
        <Text style={styles.label}>URL del servidor Cognia</Text>
        <Text style={styles.hint}>
          Inicia Cognia en tu PC con:{'\n'}
          uvicorn app.main:app --host 0.0.0.0 --port 8000{'\n'}
          Luego ingresa http://&lt;IP-de-tu-PC&gt;:8000
        </Text>
        <TextInput
          style={[styles.input, urlError ? styles.inputError : null]}
          value={url}
          onChangeText={(v) => { setUrl(v); setUrlError(''); setTestState('idle'); }}
          placeholder="http://192.168.1.x:8000"
          placeholderTextColor={Colors.muted}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
        />
        {urlError ? <Text style={styles.errorText}>{urlError}</Text> : null}

        <View style={styles.actions}>
          <Pressable onPress={handleTest} style={styles.btn}>
            <Text style={styles.btnText}>
              {testState === 'testing' ? 'probando...' :
               testState === 'ok' ? 'conectado' :
               testState === 'fail' ? 'sin respuesta' :
               'probar'}
            </Text>
          </Pressable>
          <Pressable onPress={handleSave} style={[styles.btn, styles.btnPrimary]}>
            <Text style={styles.btnText}>guardar</Text>
          </Pressable>
        </View>
      </View>
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
});
