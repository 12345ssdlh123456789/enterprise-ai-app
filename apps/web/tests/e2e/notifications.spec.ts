import { expect, test } from '@playwright/test';

/**
 * 通知中心 E2E。
 *
 * 依赖网关（登录 + `/notifications`）；网关没起时依赖后端的用例自动 skip。
 * 通知数据通过 API 造：演示管理员登录拿 token → POST /notifications。
 * 注意默认单体模式下由网关自己的表提供，开 `GATEWAY_PROXY_NOTIFICATIONS` 时由
 * notification-service 提供，前端与用例都不感知。
 */

const BACKEND = process.env.E2E_BACKEND_URL || 'http://127.0.0.1:8000';
const API = `${BACKEND}/api/v1`;
const DEMO_EMAIL = process.env.E2E_EMAIL || 'admin@example.com';
const DEMO_PASSWORD = process.env.E2E_PASSWORD || 'admin123';

let accessToken = '';
let refreshToken = '';

test.beforeAll(async ({ request }) => {
  try {
    const res = await request.post(`${API}/auth/login`, {
      data: { email: DEMO_EMAIL, password: DEMO_PASSWORD },
      timeout: 5000,
    });
    if (!res.ok()) return;
    const body = await res.json();
    const data = body?.data ?? body;
    accessToken = data?.access_token || '';
    refreshToken = data?.refresh_token || '';
  } catch {
    accessToken = '';
  }
});

async function seedAuth(page: import('@playwright/test').Page) {
  await page.addInitScript(
    ([access, refresh]) => {
      localStorage.setItem('access_token', access);
      localStorage.setItem('refresh_token', refresh);
    },
    [accessToken, refreshToken]
  );
}

test.describe('通知中心', () => {
  test('未登录访问时提示先登录', async ({ page }) => {
    await page.goto('/notifications');

    await expect(page.getByText('请先登录')).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole('heading', { name: '通知中心' })).toBeHidden();
  });

  test('能看到新通知，标记已读后未读态消失，删除后从列表移除', async ({ page, request }) => {
    test.skip(!accessToken, '网关未启动或演示账号登录失败，跳过依赖后端的用例');

    const title = `E2E 通知 ${Date.now()}`;
    const created = await request.post(`${API}/notifications`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: { title, content: '由 Playwright 创建的通知', type: 'INFO', channel: 'IN_APP' },
    });
    expect(created.ok(), await created.text()).toBeTruthy();

    await seedAuth(page);
    await page.goto('/notifications');

    await expect(page.getByRole('heading', { name: '通知中心' })).toBeVisible({ timeout: 20000 });
    const row = page.getByRole('listitem').filter({ hasText: title });
    await expect(row).toBeVisible();

    await row.getByRole('button', { name: '标记已读' }).click();
    await expect(row.getByRole('button', { name: '标记已读' })).toBeHidden();

    await row.getByRole('button', { name: `删除通知 ${title}` }).click();
    await expect(page.getByText(title)).toBeHidden();
  });
});
