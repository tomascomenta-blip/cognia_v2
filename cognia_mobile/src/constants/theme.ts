import { Platform } from 'react-native';

export const Colors = {
  bg:         '#0d0d0d',
  surface:    '#161616',
  border:     '#2a2a2a',
  text:       '#e8e8e8',
  muted:      '#666666',
  userBubble: '#1e1e1e',
  aiBubble:   '#0d0d0d',
  danger:     '#cc3333',
  inputBg:    '#1a1a1a',
} as const;

export const Typography = {
  fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  sm:   13,
  md:   15,
  lg:   17,
  lineHeight: 22,
} as const;

export const Spacing = {
  xs:  4,
  sm:  8,
  md: 16,
  lg: 24,
  xl: 40,
} as const;
