import { describe, expect, it } from 'vitest'

import {
  getNextTheme,
  getThemeBrandName,
  getThemeLabel,
  getThemeLogoPath,
  THEME_STORAGE_KEY,
} from './theme'

describe('theme helpers', () => {
  it('keeps the existing local-storage key', () => {
    expect(THEME_STORAGE_KEY).toBe('podly-theme')
  })

  it('rotates through every theme and labels the original theme Blue', () => {
    expect(getNextTheme('light')).toBe('dark')
    expect(getNextTheme('dark')).toBe('original')
    expect(getNextTheme('original')).toBe('light')
    expect(getThemeLabel('original')).toBe('Blue')
  })

  it.each(['light', 'dark'] as const)(
    'uses the Unicorn identity for the %s theme',
    (theme) => {
      expect(getThemeLogoPath(theme)).toBe('/images/logos/unicorn-logo.png')
      expect(getThemeBrandName(theme)).toBe('Podly Unicorn')
    },
  )

  it('keeps the Blue identity available under the original storage value', () => {
    expect(getThemeLabel('original')).toBe('Blue')
    expect(getThemeLogoPath('original')).toBe('/images/logos/original-logo.png')
    expect(getThemeBrandName('original')).toBe('Podly')
  })
})
