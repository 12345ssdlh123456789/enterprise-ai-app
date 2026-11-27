import { defineConfig, devices } from '@playwright/test';

/**
 * E2E 配置。
 *
 * - 工作台端口是 3002（见 package.json 的 `dev` 脚本），不是 3000。
 * - 只跑 chromium 作为默认门禁；firefox / webkit 需要时用 `--project=firefox` 单独跑。
 * - webServer 只负责起前端；登录成功的用例需要后端网关（8000），
 *   用例里会先探测 /health，后端没起就自动 skip（和 tests/test_*_smoke.py 的策略一致）。
 */
export default defineConfig({
  testDir: './tests/e2e',
  // CI 上 `next dev` 首次访问要现场编译，默认 30s 的用例超时会不够用。
  timeout: 60_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:3002',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'pnpm dev',
    url: 'http://127.0.0.1:3002',
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
});
