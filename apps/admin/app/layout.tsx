import type { Metadata } from 'next';
import './globals.css';
import { Providers } from '@/components/providers';
import { AuthGate } from '@/components/auth-gate';

export const metadata: Metadata = {
  title: '智汇 AI 工作台 - 管理后台',
  description: '企业级 AI 应用管理后台 - 租户、用户、成本、审计',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="font-sans antialiased">
        <Providers>
          <AuthGate>{children}</AuthGate>
        </Providers>
      </body>
    </html>
  );
}