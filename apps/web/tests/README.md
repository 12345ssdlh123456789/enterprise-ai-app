# 测试指南

## 测试架构

```
apps/web/tests/
├── unit/                    # 单元测试 (Vitest)
│   ├── setup.ts            # 测试环境配置、Mock 设置
│   ├── utils.test.ts       # 工具函数测试
│   └── workflow-validation.test.ts  # 工作流验证逻辑测试
├── e2e/                    # 端到端测试
│   ├── workflow-editor.spec.ts     # 工作流编辑器 E2E 测试
│   └── auth.spec.ts              # 认证流程 E2E 测试
├── fixtures/               # 测试数据
│   └── workflow.ts         # Mock 工作流数据
├── vitest.config.ts        # Vitest 配置
└── playwright.config.ts    # Playwright 配置
```

## 运行测试

### 单元测试

```bash
# 运行所有单元测试
cd apps/web && npm run test

# 监视模式 (开发时使用)
cd apps/web && npm run test:watch

# 打开 UI 界面
cd apps/web && npm run test:ui

# 生成覆盖率报告
cd apps/web && npm run test:coverage
```

### E2E 测试

```bash
# 先启动开发服务器
cd apps/web && npm run dev

# 在另一个终端运行 E2E 测试
cd apps/web && npm run e2e

# 打开 Playwright UI
cd apps/web && npm run e2e:ui

# 带界面运行 (headed 模式)
cd apps/web && npm run e2e:headed
```

## 测试覆盖范围

### 单元测试
- ✅ 工具函数 (`cn`, `formatBytes`, `formatNumber`, `formatCurrency`, `formatRelativeTime`, `truncate`, `getInitials`)
- ✅ 工作流验证逻辑 (基础验证、孤立节点检测、循环检测、边缘情况)

### E2E 测试
- ✅ 认证流程 (登录、登出、受保护路由)
- ✅ 工作流编辑器 (画布加载、节点添加、连接、配置面板、验证、保存、执行)
- ✅ 工作流列表 (搜索、筛选、CRUD 操作)

## Mock 策略

### 单元测试 Mock
- `next/navigation` - 路由相关 hooks
- `next-auth/react` - 认证状态
- `sonner` - Toast 通知
- `lucide-react` - 图标组件
- `reactflow` - 画布组件
- `@radix-ui/*` - UI 组件库
- `@/lib/api` - API 客户端
- `@/lib/auth` - 认证上下文
- `@/lib/utils` - 工具函数

### E2E 测试
- 使用 Playwright 的真实浏览器环境
- 开发服务器通过 `webServer` 配置自动启动
- 支持 Chromium、Firefox、WebKit 多浏览器

## 添加新测试

### 单元测试
1. 在 `tests/unit/` 创建 `xxx.test.ts`
2. 导入被测试函数
3. 使用 `describe`/`it` 编写测试用例
4. 运行 `npm run test` 验证

### E2E 测试
1. 在 `tests/e2e/` 创建 `xxx.spec.ts`
2. 使用 `test.describe`/`test` 编写测试
3. 使用 `page` 对象进行交互
4. 运行 `npm run e2e` 验证

## CI/CD 集成

在 GitHub Actions 中添加：

```yaml
- name: Run unit tests
  run: cd apps/web && npm run test

- name: Run E2E tests
  run: |
    cd apps/web
    npm run build
    npm run start &
    sleep 10
    npm run e2e
```

## 常见问题

### 1. 测试超时
增加 `testTimeout` 配置：
```typescript
// vitest.config.ts
test: {
  testTimeout: 10000,
}
```

### 2. Mock 不生效
确保 mock 在 `setup.ts` 中定义，且测试文件正确导入了 setup

### 3. E2E 测试不稳定
- 使用 `waitFor` 等待元素出现
- 避免硬编码等待时间
- 使用 `data-testid` 选择器而非 CSS 类名

### 4. 覆盖率低
- 为核心业务逻辑添加单元测试
- 使用 `--coverage` 生成报告查看未覆盖代码