import type { Metadata } from 'next';
import './globals.css';
import { Providers } from '@/components/providers';
import { ToasterProvider } from '@/components/ui/toast';
import { Navbar } from '@/components/navbar';

export const metadata: Metadata = {
  title: '智汇 AI 工作台 - 智能客服助手',
  description: '企业级 AI 应用平台 - 知识库、对话、工作流管理',
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
          <Navbar />
          {children}
          <ToasterProvider />
        </Providers>
      </body>
    </html>
  );
}
