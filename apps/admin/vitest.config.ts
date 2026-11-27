import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

/**
 * 管理后台单测配置。
 *
 * - 测试只跑 `tests/unit/**`，不需要后端或 Next dev server。
 * - `tests/unit/setup.ts` 里 mock 掉 next/link、next/navigation 和 @/lib/auth，
 *   请求层用例再单独 `vi.unmock` 测真实实现（参考 apps/web 的做法）。
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    // jest-dom 的匹配器注册依赖全局 expect（与 apps/web 的配置保持一致）
    globals: true,
    setupFiles: ['./tests/unit/setup.tsx'],
    include: ['tests/unit/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      // lcov 供 CI 上传 codecov（默认 reporter 不含 lcov）
      reporter: ['text', 'json', 'html', 'lcov'],
      exclude: ['node_modules/', 'tests/', '**/*.d.ts', '**/*.config.*'],
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
      '@/components': path.resolve(__dirname, 'components'),
      '@/lib': path.resolve(__dirname, 'lib'),
      '@/hooks': path.resolve(__dirname, 'hooks'),
      '@/types': path.resolve(__dirname, 'types'),
    },
  },
});
