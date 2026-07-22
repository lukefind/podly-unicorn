import { expect, test } from '@playwright/test'

const themes = ['light', 'dark', 'original'] as const

for (const theme of themes) {
  test(`${theme} theme preserves Unicorn product presentation`, async ({ page }, testInfo) => {
    await page.addInitScript((savedTheme) => {
      window.localStorage.setItem('podly-theme', savedTheme)
      window.localStorage.setItem('podly_onboarding_completed', 'true')
    }, theme)

    await page.goto('/')
    await expect(page).toHaveTitle('Podly Unicorn')

    const expectedLogo = theme === 'original'
      ? '/images/logos/original-logo.png'
      : '/images/logos/unicorn-logo.png'
    const expectedBrand = theme === 'original' ? 'Podly' : 'Podly Unicorn'
    await expect(page.locator(`img[src="${expectedLogo}"]:visible`).first()).toHaveAttribute('alt', expectedBrand)

    if (testInfo.project.name === 'mobile') {
      const mobileHeader = page.locator('div.lg\\:hidden.fixed').first()
      await mobileHeader.getByRole('button').click()
      await expect(page.getByRole('link', { name: 'Dashboard' })).toBeVisible()
      await mobileHeader.getByRole('button').click()
    } else {
      await expect(page.getByRole('link', { name: 'Dashboard' })).toBeVisible()
      await expect(page.getByRole('link', { name: 'Podcasts', exact: true })).toBeVisible()
    }

    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true)
    await expect(page).toHaveScreenshot(`${theme}-${testInfo.project.name}.png`, {
      fullPage: true,
      animations: 'disabled',
    })
  })
}
