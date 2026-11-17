import { expect, test, type APIRequestContext } from '@playwright/test'

// Krytyczny przepływ w przeglądarce:
// logowanie → zapotrzebowanie → optymalizacja → rezerwacja → wykonanie → resztka w magazynie.
// Test sam przygotowuje nowy warsztat przez API (unikalny e-mail), więc można go powtarzać
// bez resetowania danych demo. Magazyn i zapotrzebowanie = przykład z docs/ALGORITHM.md.

const PASSWORD = 'E2eHaslo123!'

async function prepareWorkshop(request: APIRequestContext, email: string) {
  const reg = await request.post('/api/auth/register', {
    data: { email, password: PASSWORD, full_name: 'Test E2E', workshop_name: 'Warsztat E2E' },
  })
  expect(reg.status()).toBe(201)
  const { csrf_token, user } = await reg.json()
  const ws = user.memberships[0].workshop_id
  const headers = { 'X-CSRF-Token': csrf_token }
  const spec = await (
    await request.post(`/api/workshops/${ws}/materials`, { headers, data: { material: 'Sosna', section: '40x20 mm' } })
  ).json()
  const add = (length_mm: number, is_remnant: boolean, quantity = 1) =>
    request.post(`/api/workshops/${ws}/stock`, {
      headers,
      data: { material_spec_id: spec.id, length_mm, quantity, is_remnant },
    })
  for (const length of [1250, 1900, 1400, 900]) expect((await add(length, true)).status()).toBe(201)
  expect((await add(3000, false, 3)).status()).toBe(201)
  return spec.label as string
}

test('pełny przepływ planowania cięcia', async ({ page, request }) => {
  const email = `e2e-${Date.now()}@offcut.test`
  const specLabel = await prepareWorkshop(request, email)
  page.on('dialog', (dialog) => dialog.accept())

  // Logowanie
  await page.goto('/login')
  await page.getByTestId('login-email').fill(email)
  await page.getByTestId('login-password').fill(PASSWORD)
  await page.getByTestId('login-submit').click()

  // Nowy projekt i zapotrzebowanie
  await page.getByTestId('nav-projects').click()
  await page.getByPlaceholder('np. Półka do garażu').fill('Regał E2E')
  await page.getByRole('button', { name: 'Utwórz projekt' }).click()
  await expect(page.getByRole('heading', { name: 'Regał E2E' })).toBeVisible()

  for (const [length, qty] of [[950, 2], [600, 1], [560, 3]]) {
    await page.getByTestId('demand-spec').selectOption({ label: specLabel })
    await page.getByTestId('demand-length').fill(String(length))
    await page.getByTestId('demand-quantity').fill(String(qty))
    await page.getByTestId('demand-add').click()
    await expect(page.locator('[data-testid^="demand-row-"]', { hasText: `${length}` })).toBeVisible()
  }

  // Optymalizacja i porównanie metod
  await page.getByTestId('optimize').click()
  const greedy = page.getByTestId('result-GREEDY')
  const bnb = page.getByTestId('result-BRANCH_AND_BOUND')
  await expect(greedy).toContainText('5450 mm')
  await expect(bnb).toContainText('4900 mm')
  await expect(bnb).toContainText('Optymalny')
  await expect(page.getByTestId('verdict')).toContainText('550 mm')
  await expect(page.getByTestId('diagram-BRANCH_AND_BOUND')).toBeVisible()

  // Rezerwacja planu branch and bound
  await page.getByTestId('reserve-BRANCH_AND_BOUND').click()
  await expect(page.getByTestId('plan-status')).toHaveText('Zarezerwowany')

  // Wykonanie i resztki
  await page.getByTestId('execute-plan').click()
  await expect(page.getByTestId('plan-status')).toHaveText('Wykonany')
  const remnants = page.getByTestId('remnants')
  await expect(remnants).toContainText('344')
  await expect(remnants).toContainText('358')

  // Resztki są w magazynie jako dostępne odcinki z pochodzeniem z planu
  await page.getByTestId('nav-stock').click()
  for (const length of ['344', '358']) {
    await expect(page.locator('[data-testid^="stock-row-"]', { hasText: length }).first()).toContainText('z planu')
  }
})
