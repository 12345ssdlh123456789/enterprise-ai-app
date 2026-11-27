import { test, expect } from '@playwright/test';

/**
 * 登录主流程 E2E。
 *
 * 现实：项目没有独立的 /login 路由，登录表单就在首页 `/`（未登录时渲染）。
 * 演示账号来自网关种子数据：admin@example.com / admin123。
 * 依赖后端的用例会先探测网关 8000，没起就 skip，不制造假绿。
 */

const BACKEND = process.env.E2E_BACKEND_URL || 'http://127.0.0.1:8000';
const DEMO_EMAIL = process.env.E2E_EMAIL || 'admin@example.com';
const DEMO_PASSWORD = process.env.E2E_PASSWORD || 'admin123';

let backendUp = false;

test.beforeAll(async ({ request }) => {
  try {
    const res = await request.get(`${BACKEND}/health`, { timeout: 3000 });
    backendUp = res.ok();
  } catch {
    backendUp = false;
  }
});

test.describe('登录', () => {
  test('首页渲染登录表单', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByRole('heading', { name: '登录工作区' })).toBeVisible();
    await expect(page.locator('input[type="email"]')).toBeVisible();
    await expect(page.locator('input[type="password"]')).toBeVisible();
    await expect(page.getByRole('button', { name: '登录' })).toBeVisible();
  });

  test('密码错误时给出错误提示，且不进入工作台', async ({ page }) => {
    test.skip(!backendUp, '网关未启动（8000），跳过依赖后端的用例');

    await page.goto('/');
    await page.locator('input[type="email"]').fill(DEMO_EMAIL);
    await page.locator('input[type="password"]').fill('definitely-wrong');
    await page.getByRole('button', { name: '登录' }).click();

    await expect(page.getByText(/登录失败|密码|账号|error|invalid/i).first()).toBeVisible({ timeout: 15000 });
    // 仍然停在登录页
    await expect(page.getByRole('heading', { name: '登录工作区' })).toBeVisible();
  });

  test('正确账号可以登录并进入工作台', async ({ page }) => {
    test.skip(!backendUp, '网关未启动（8000），跳过依赖后端的用例');

    await page.goto('/');
    await page.locator('input[type="email"]').fill(DEMO_EMAIL);
    await page.locator('input[type="password"]').fill(DEMO_PASSWORD);
    await page.getByRole('button', { name: '登录' }).click();

    // 登录后登录表单消失，出现「知识库」标签页
    await expect(page.getByRole('tab', { name: /知识库/ })).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole('heading', { name: '登录工作区' })).toBeHidden();

    // token 落到 localStorage，刷新后仍是登录态
    const token = await page.evaluate(() => localStorage.getItem('access_token'));
    expect(token).toBeTruthy();
  });
});
