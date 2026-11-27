import { expect, test } from '@playwright/test';

import { backendIsUp, loginAsAdmin } from './support';

/**
 * 五个管理页面 + 审计明细对话框的 E2E。
 * 全部依赖网关（登录 + 列表接口），后端没起就整组 skip。
 *
 * 注意：`test.skip()` 必须写在用例体内。写在 describe/file 作用域会在「收集阶段」
 * 求值，那时 beforeAll 还没跑，backendUp 永远是 false —— 会静默跳过整组用例。
 */

const PAGES = [
  { nav: '用户', heading: '用户管理' },
  { nav: '租户', heading: '租户管理' },
  { nav: '模型', heading: '模型配置' },
  { nav: '审计', heading: '审计日志' },
  { nav: '成本', heading: '成本与用量' },
] as const;

let backendUp = false;

test.beforeAll(async ({ request }) => {
  backendUp = await backendIsUp(request);
});

test.describe('后台导航', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('每个导航项都能打开对应页面并标记当前页', async ({ page }) => {
    test.skip(!backendUp, '网关未启动（8000），跳过依赖后端的用例');

    for (const item of PAGES) {
      await page.getByRole('link', { name: item.nav, exact: true }).click();
      await expect(page.getByRole('heading', { name: item.heading })).toBeVisible({
        timeout: 15000,
      });
      await expect(page.getByRole('link', { name: item.nav, exact: true })).toHaveAttribute(
        'aria-current',
        'page'
      );
    }
  });

  test('提供「跳到主内容」跳转链接和 main 地标', async ({ page }) => {
    test.skip(!backendUp, '网关未启动（8000），跳过依赖后端的用例');

    await expect(page.getByRole('link', { name: '跳到主内容' })).toHaveCount(1);
    await expect(page.locator('main#main')).toBeVisible();
  });
});

test.describe('用户列表', () => {
  test('搜索无结果时给出空态，清空后恢复列表', async ({ page }) => {
    test.skip(!backendUp, '网关未启动（8000），跳过依赖后端的用例');

    await loginAsAdmin(page);
    await page.getByRole('link', { name: '用户', exact: true }).click();

    const search = page.getByLabel('搜索用户');
    await expect(search).toBeVisible({ timeout: 15000 });

    await search.fill('no-such-user-xyz');
    await expect(page.getByText('没有匹配的用户')).toBeVisible();

    await search.fill('');
    await expect(page.getByText('没有匹配的用户')).toBeHidden();
    await expect(page.getByRole('button', { name: /^编辑 / }).first()).toBeVisible();
  });
});

test.describe('审计明细', () => {
  test('「查看」按钮打开明细对话框并可关闭', async ({ page }) => {
    test.skip(!backendUp, '网关未启动（8000），跳过依赖后端的用例');

    await loginAsAdmin(page);
    await page.getByRole('link', { name: '审计', exact: true }).click();
    await expect(page.getByRole('heading', { name: '审计日志' })).toBeVisible({ timeout: 15000 });

    const detailButtons = page.getByRole('button', { name: /^查看 .* 的事件明细$/ });
    const count = await detailButtons.count();
    test.skip(count === 0, '审计表里还没有事件（登录会写入，可先登录一次再跑）');

    await detailButtons.first().click();
    const dialog = page.getByRole('dialog', { name: '审计事件明细' });
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: '关闭' }).click();
    await expect(dialog).toBeHidden();
  });
});
