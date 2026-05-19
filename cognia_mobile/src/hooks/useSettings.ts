import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useEffect, useState } from 'react';
import type { AppSettings } from '../types';

const SETTINGS_KEY = 'cognia_settings_v1';
// 10.0.2.2 is the Android emulator's alias for the host machine's localhost.
// On a real device, the user must change this to their machine's LAN IP.
const DEFAULT_SETTINGS: AppSettings = { serverUrl: 'http://10.0.2.2:8765' };

export function useSettings() {
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    AsyncStorage.getItem(SETTINGS_KEY)
      .then((raw) => {
        if (raw) setSettings(JSON.parse(raw) as AppSettings);
      })
      .finally(() => setIsLoading(false));
  }, []);

  const saveSettings = useCallback(async (next: AppSettings) => {
    await AsyncStorage.setItem(SETTINGS_KEY, JSON.stringify(next));
    setSettings(next);
  }, []);

  return { settings, saveSettings, isLoading };
}
