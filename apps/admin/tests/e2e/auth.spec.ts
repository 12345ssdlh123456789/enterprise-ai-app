import { expect, test } from '@playwright/test';

import { DEMO_EMAIL, DEMO_PASSWORD, backendIsUp, loginAsAdmin } from './support';

/**
 * 登录主流程 E2E（管理后台）。
 *
 * 后台没有独立 /login 路由：未登录时 AuthGate 直接在 `/` 渲染登录表单。
 * 依赖后端的用例先探测网关 8000，没起就 skip。
 */

let backendUp = false;

test.beforeAll(async ({ request }) => {
  backendUp = await backendIsUp(request);
});

test.describe('登录与退出', () => {
  test('未登录时渲染登录表单，不暴露后台内容', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByText('智汇 AI 工作台 · 管理后台')).toBeVisible();
    await expect(page.locator('#email')).toHaveValue(DEMO_EMAIL);
    await expect(page.locator('#password')).toBeVisible();
    await expect(page.getByRole('button', { name: '登录' })).toBeVisible();
    // 未登录不应出现导航或「总览」标题
    await expect(page.getByRole('navigation', { name: '主导航' })).toBeHidden();
    await expect(page.getByRole('heading', { name: '总览' })).toBeHidden();
  });

  test('密码错误时给出可读错误且停在登录页', async ({ page }) => {
    test.skip(!backendUp, '网关未启动（8000），跳过依赖后端的用例');

    await page.goto('/');
    await page.locator('#password').fill('definitely-wrong');
    await page.getByRole('button', { name: '登录' }).click();

    // 页面里还有一个 Next 的 `__next-route-announcer__`（同样 role="alert"、内容为空），
    // 所以这里限定登录表单里的 <p role="alert">，并要求错误文案真的出现。
    await expect(page.locator('p[role="alert"]')).toContainText(
      /invalid|密码|账号|登录失败/i,
      { timeout: 15000 }
    );
    await expect(page.getByRole('button', { name: '登录' })).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem('access_token'))).toBeFalsy();
  });

  test('正确账号登录后进入后台，刷新仍是登录态', async ({ page }) => {
    test.skip(!backendUp, '网关未启动（8000），跳过依赖后端的用例');

    await loginAsAdmin(page);

    await expect(page.getByRole('navigation', { name: '主导航' })).toBeVisible();
    await expect(page.getByRole('link', { name: '总览' })).toHaveAttribute('aria-current', 'page');
    expect(await page.evaluate(() => localStorage.getItem('access_token'))).toBeTruthy();

    await page.reload();
    await expect(page.getByRole('heading', { name: '总览' })).toBeVisible({ timeout: 20000 });
  });

  test('退出后清掉会话并回到登录表单', async ({ page }) => {
    test.skip(!backendUp, '网关未启动（8000），跳过依赖后端的用例');

    await loginAsAdmin(page);
    await page.getByRole('button', { name: '退出' }).click();

    await expect(page.getByRole('button', { name: '登录' })).toBeVisible({ timeout: 15000 });
    expect(await page.evaluate(() => localStorage.getItem('access_token'))).toBeFalsy();
  });
});
