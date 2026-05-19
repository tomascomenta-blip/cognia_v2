import { Stack } from 'expo-router';
import { SQLiteProvider } from 'expo-sqlite';
import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { initDb } from '../src/db/schema';
import { Colors, Typography } from '../src/constants/theme';

export default function RootLayout() {
  return (
    <SQLiteProvider databaseName="cognia.db" onInit={initDb}>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: Colors.surface },
          headerTintColor: Colors.text,
          headerTitleStyle: {
            fontFamily: Typography.fontFamily,
            fontSize: Typography.md,
          },
          contentStyle: { backgroundColor: Colors.bg },
          headerShadowVisible: false,
          headerBackTitle: '',
        }}
      >
        <Stack.Screen
          name="index"
          options={{ title: 'Cognia' }}
        />
        <Stack.Screen
          name="conversation/[id]"
          options={{ title: '' }}
        />
        <Stack.Screen
          name="settings"
          options={{ title: 'Servidor' }}
        />
      </Stack>
    </SQLiteProvider>
  );
}
