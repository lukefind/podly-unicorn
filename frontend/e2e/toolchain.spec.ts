import { expect, test } from '@playwright/test'

test('runs specs from the isolated end-to-end test directory', () => {
  expect(test.info().file).toMatch(/[\\/]e2e[\\/]/)
})
