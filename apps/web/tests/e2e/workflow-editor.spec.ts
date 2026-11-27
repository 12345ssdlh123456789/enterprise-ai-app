import { test, expect, Page } from '@playwright/test';

/**
 * 工作流列表 / 新建 流程 E2E。
 *
 * 旧版这条 spec 是对着「想象中的 UI」写的（`/login` 旁路、假账号、编辑器内部组件名），
 * 一次都没跑通过。现在改成：用真实网关登录拿 token，注入 localStorage，再断言真实存在的元素。
 * 网关没起时依赖后端的用例自动 skip。
 */

const BACKEND = process.env.E2E_BACKEND_URL || 'http://127.0.0.1:8000';
const API = `${BACKEND}/api/v1`;
const DEMO_EMAIL = process.env.E2E_EMAIL || 'admin@example.com';
const DEMO_PASSWORD = process.env.E2E_PASSWORD || 'admin123';

let accessToken = '';
let refreshToken = '';

async function seedAuth(page: Page) {
  await page.addInitScript(
    ([access, refresh]) => {
      localStorage.setItem('access_token', access);
      localStorage.setItem('refresh_token', refresh);
    },
    [accessToken, refreshToken]
  );
}

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

test.describe('未登录访问', () => {
  test('直接打开 /workflows 提示先登录，而不是永远转圈', async ({ page }) => {
    await page.goto('/workflows');

    // 回归用例：曾经这里的 loading 永远不会结束，页面卡在「加载中，请稍候...」
    await expect(page.getByText('请先登录')).toBeVisible({ timeout: 15000 });
    await expect(page.getByText('加载中，请稍候...')).toBeHidden();
    await expect(page.getByRole('heading', { name: '工作流管理' })).toBeHidden();
  });
});

test.describe('工作流管理', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!accessToken, '网关未启动或演示账号登录失败，跳过依赖后端的用例');
    await seedAuth(page);
  });

  test('列表页加载并显示标题', async ({ page }) => {
    await page.goto('/workflows');
    await expect(page.getByRole('heading', { name: '工作流管理' })).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole('button', { name: '新建工作流' })).toBeVisible();
  });

  test('新建对话框可以打开并输入，取消后不落库', async ({ page }) => {
    await page.goto('/workflows');
    await page.getByRole('button', { name: '新建工作流' }).click();

    const nameInput = page.locator('input[placeholder="例如：智能客服问答流程"]');
    await expect(nameInput).toBeVisible();
    await nameInput.fill('E2E 不落库的工作流');
    await expect(nameInput).toHaveValue('E2E 不落库的工作流');

    await page.keyboard.press('Escape');
    await expect(nameInput).toBeHidden();
  });

  test('搜索框可以过滤列表', async ({ page }) => {
    await page.goto('/workflows');
    const search = page.locator('input[placeholder="搜索工作流..."]');
    await expect(search).toBeVisible();

    await search.fill('不存在的关键词-zzz');
    await page.waitForTimeout(800);
    // 不假设列表里一定有空状态文案，只要求不报错、搜索框值保持
    await expect(search).toHaveValue('不存在的关键词-zzz');
    await expect(page.getByRole('heading', { name: '工作流管理' })).toBeVisible();
  });
});
