'use client';

import * as React from 'react';
import {
  ThemeProvider as NextThemesProvider,
  ThemeProviderProps,
  useTheme,
} from 'next-themes';
import { getThemePreset, DEFAULT_THEME } from '@/config/themes';

interface AppThemeProviderProps extends ThemeProviderProps {
  appTheme?: string;
}

/**
 * Applies CSS variables based on the active app theme
 * AND the current light/dark mode from next-themes.
 */
function AppThemeApplier({ appTheme }: { appTheme: string }) {
  const { resolvedTheme } = useTheme();

  React.useEffect(() => {
    const preset = getThemePreset(appTheme);
    const mode = resolvedTheme === 'dark' ? 'dark' : 'light';
    const variables = preset[mode];

    const root = document.documentElement;
    for (const [varName, value] of Object.entries(variables)) {
      root.style.setProperty(varName, value);
    }

    return () => {
      for (const varName of Object.keys(variables)) {
        root.style.removeProperty(varName);
      }
    };
  }, [appTheme, resolvedTheme]);

  return null;
}

/**
 * Theme Provider Component
 *
 * Wraps the application with next-themes provider for dark/light mode
 * AND applies admin-configured theme preset CSS variables.
 */
export function ThemeProvider({
  appTheme = DEFAULT_THEME,
  children,
  ...props
}: AppThemeProviderProps) {
  return (
    <NextThemesProvider {...props}>
      <AppThemeApplier appTheme={appTheme} />
      {children}
    </NextThemesProvider>
  );
}
