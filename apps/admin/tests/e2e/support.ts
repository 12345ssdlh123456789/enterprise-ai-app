import { expect } from '@playwright/test';

import type { APIRequestContext, Page } from '@playwright/test';

/** 网关地址；E2E 只探测健康检查，不直接调业务接口。 */
export const BACKEND = process.env.E2E_BACKEND_URL || 'http://127.0.0.1:8000';
export const DEMO_EMAIL = process.env.E2E_EMAIL || 'admin@example.com';
export const DEMO_PASSWORD = process.env.E2E_PASSWORD || 'admin123';

/**
 * 网关没起时依赖真实接口的用例统一 skip，不制造假绿。
 * （与 apps/web 的 e2e、tests/test_*_smoke.py 的策略一致。）
 */
export async function backendIsUp(request: APIRequestContext): Promise<boolean> {
  try {
    const res = await request.get(`${BACKEND}/health`, { timeout: 3000 });
    return res.ok();
  } catch {
    return false;
  }
}

/** 用演示管理员登录，停在「总览」页。 */
export async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto('/');
  await page.locator('#email').fill(DEMO_EMAIL);
  await page.locator('#password').fill(DEMO_PASSWORD);
  await page.getByRole('button', { name: '登录' }).click();
  await expect(page.getByRole('heading', { name: '总览' })).toBeVisible({ timeout: 20000 });
}
