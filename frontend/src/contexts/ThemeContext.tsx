import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import {
  THEME_STORAGE_KEY,
  getNextTheme,
  isDarkSurfaceTheme,
  type Theme,
} from '../theme';
import { resolveInitialTheme } from '../themePreference';

interface ThemeContextType {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    return resolveInitialTheme(stored, prefersDark);
  });

  useEffect(() => {
    localStorage.setItem(THEME_STORAGE_KEY, theme);

    // Original mode intentionally enables `dark` utilities and then layers blue overrides.
    document.documentElement.classList.toggle('dark', isDarkSurfaceTheme(theme));
    document.documentElement.classList.toggle('theme-original', theme === 'original');
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => getNextTheme(prev));
  };

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
