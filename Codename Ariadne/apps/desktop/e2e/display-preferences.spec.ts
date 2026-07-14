import { expect, test } from '@playwright/test'

test.describe('display preferences', () => {
  test('scales the complete type system and persists the accessible choice', async ({
    page,
  }) => {
    await page.goto('/settings/privacy?fixture=standard')
    await expect(page.getByTestId('route-ready')).toBeVisible()

    const navigationLabel = page.getByRole('link', { name: 'Mission Control' })
    const initialSize = await navigationLabel.evaluate((element) =>
      Number.parseFloat(getComputedStyle(element).fontSize),
    )
    await page.getByRole('button', { name: '140% interface size' }).click()
    const scaledSize = await navigationLabel.evaluate((element) =>
      Number.parseFloat(getComputedStyle(element).fontSize),
    )

    expect(scaledSize).toBeCloseTo(initialSize * 1.4, 1)
    await expect(page.locator('html')).toHaveAttribute('data-font-scale', '140')
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-font-scale', '140')
    await expect(
      page.getByRole('button', { name: '140% interface size' }),
    ).toHaveAttribute('aria-pressed', 'true')
  })

  test('offers bounded Laptop, Standard, and Ultrawide workspace widths', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 2560, height: 1080 })
    await page.goto('/settings/privacy?fixture=standard')
    await expect(page.getByTestId('route-ready')).toBeVisible()
    const pageSurface = page.locator('main .page')

    await page.getByRole('button', { name: 'Laptop', exact: true }).click()
    const laptopWidth = (await pageSurface.boundingBox())?.width ?? 0
    expect(laptopWidth).toBeGreaterThan(0)
    expect(laptopWidth).toBeLessThanOrEqual(1280)

    await page.getByRole('button', { name: 'Standard', exact: true }).click()
    const standardWidth = (await pageSurface.boundingBox())?.width ?? 0
    expect(standardWidth).toBeGreaterThan(laptopWidth)
    expect(standardWidth).toBeLessThanOrEqual(1760)

    await page.getByRole('button', { name: 'Ultrawide', exact: true }).click()
    const ultrawideWidth = (await pageSurface.boundingBox())?.width ?? 0
    expect(ultrawideWidth).toBeGreaterThan(standardWidth)
    expect(ultrawideWidth).toBeLessThanOrEqual(2560)
    await expect(page.locator('.app-shell')).toHaveAttribute(
      'data-display-preset',
      'ultrawide',
    )
  })

  test('Auto follows laptop, standard, and ultrawide window breakpoints', async ({
    page,
  }) => {
    await page.goto('/settings/privacy?fixture=standard')
    await page.getByRole('button', { name: 'Auto', exact: true }).click()

    const contentMaximum = () =>
      page.locator('html').evaluate((element) =>
        getComputedStyle(element).getPropertyValue('--display-content-max').trim(),
      )

    await page.setViewportSize({ width: 1200, height: 800 })
    await expect.poll(contentMaximum).toBe('1280px')
    await page.setViewportSize({ width: 1600, height: 900 })
    await expect.poll(contentMaximum).toBe('1760px')
    await page.setViewportSize({ width: 2560, height: 1080 })
    await expect.poll(contentMaximum).toBe('2560px')
  })
})
