import { describe, expect, it } from 'vitest'

import { getNextTheme, getThemeLabel } from './theme'

describe('theme helpers', () => {
  it('rotates through every theme and labels the original theme Blue', () => {
    expect(getNextTheme('light')).toBe('dark')
    expect(getNextTheme('dark')).toBe('original')
    expect(getNextTheme('original')).toBe('light')
    expect(getThemeLabel('original')).toBe('Blue')
  })
})
