import { describe, expect, it } from 'vitest'

import { resolveInitialTheme } from './themePreference'

describe('resolveInitialTheme', () => {
  for (const stored of ['light', 'dark', 'original'] as const) {
    it(`preserves a saved ${stored} preference when the system prefers light`, () => {
      expect(resolveInitialTheme(stored, false)).toBe(stored)
    })

    it(`preserves a saved ${stored} preference when the system prefers dark`, () => {
      expect(resolveInitialTheme(stored, true)).toBe(stored)
    })
  }

  it('uses the system light preference when no preference is saved', () => {
    expect(resolveInitialTheme(null, false)).toBe('light')
  })

  it('uses the system dark preference when no preference is saved', () => {
    expect(resolveInitialTheme(null, true)).toBe('dark')
  })

  it('uses the system light preference when the saved value is invalid', () => {
    expect(resolveInitialTheme('invalid', false)).toBe('light')
  })

  it('uses the system dark preference when the saved value is invalid', () => {
    expect(resolveInitialTheme('invalid', true)).toBe('dark')
  })
})
