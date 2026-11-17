import { defineConfig } from '@playwright/test'

// Test e2e działa na uruchomionej aplikacji (domyślnie Docker Compose na porcie 8080).
// Uruchomienie: npx playwright test   (inny adres: E2E_BASE_URL=http://localhost:5173 npx playwright test)
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8080',
    viewport: { width: 1280, height: 800 },
    trace: 'off',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
      : undefined,
  },
})
