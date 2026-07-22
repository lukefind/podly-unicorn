import { isValidTheme, type Theme } from './theme'

export function resolveInitialTheme(
  stored: string | null,
  prefersDark: boolean,
): Theme {
  if (isValidTheme(stored)) return stored
  return prefersDark ? 'dark' : 'light'
}
