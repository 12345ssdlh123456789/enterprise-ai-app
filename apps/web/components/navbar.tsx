'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { useState } from 'react';
import {
  User as UserIcon,
  Settings,
  LogOut,
  MessageSquare,
  FileText,
  GitBranch,
  ChevronDown,
  Menu,
  X,
  Sparkles,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import { NotificationBell } from '@/components/notifications/notification-bell';

const navItems = [
  { href: '/', label: '知识库', icon: FileText },
  { href: '/chat', label: '对话', icon: MessageSquare },
  { href: '/workflows', label: '工作流', icon: GitBranch },
];

function BrandMark() {
  return (
    <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-brand-gradient shadow-glow">
      <svg
        className="h-5 w-5 text-white"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M12 2 2 7l10 5 10-5-10-5z" />
        <path d="M2 17l10 5 10-5" />
        <path d="M2 12l10 5 10-5" />
      </svg>
    </div>
  );
}

export function Navbar() {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const isActive = (href: string) =>
    href === '/' ? pathname === '/' || pathname.startsWith('/knowledge-bases') : pathname.startsWith(href);

  return (
    <nav className="page-header">
      <div className="mx-auto flex h-16 w-full max-w-[1360px] items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-8">
          <Link href="/" className="group flex items-center gap-2.5">
            <div className="transition-transform duration-200 group-hover:scale-105">
              <BrandMark />
            </div>
            <div className="leading-tight">
              <div className="text-[15px] font-semibold tracking-tight text-foreground">智汇 AI 工作台</div>
              <div className="hidden text-[11px] font-medium text-muted-foreground sm:block">知识中台</div>
            </div>
          </Link>

          <div className="hidden items-center gap-1 rounded-xl border border-border/70 bg-muted/50 p-1 md:flex">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cn('nav-pill', isActive(item.href) && 'nav-pill-active')}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </Link>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Link
            href="/chat"
            className="hidden items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-primary sm:flex"
          >
            <Sparkles className="h-4 w-4" />
            智能助手
          </Link>

          {user && <NotificationBell />}

          {user ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className="flex h-10 items-center gap-2 rounded-xl px-2">
                  <div className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-full bg-primary/10 text-sm font-semibold text-primary ring-1 ring-primary/15">
                    {user.full_name ? user.full_name.charAt(0).toUpperCase() : user.email.charAt(0).toUpperCase()}
                  </div>
                  <div className="hidden text-left lg:block">
                    <div className="text-[13px] font-medium leading-tight text-foreground">
                      {user.full_name || user.email}
                    </div>
                    <div className="text-[11px] leading-tight text-muted-foreground">{user.role}</div>
                  </div>
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel className="px-3 py-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  {user.email}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem>
                  <UserIcon className="mr-2 h-4 w-4" /> 个人资料
                </DropdownMenuItem>
                <DropdownMenuItem>
                  <Settings className="mr-2 h-4 w-4" /> 系统设置
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onClick={async () => {
                    await logout();
                    setMobileMenuOpen(false);
                  }}
                >
                  <LogOut className="mr-2 h-4 w-4" /> 退出登录
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <Link
              href="/"
              className="inline-flex h-10 items-center rounded-xl bg-brand-gradient px-4 text-sm font-semibold text-white shadow-sm transition-all hover:shadow-glow"
            >
              登录
            </Link>
          )}

          <Button
            variant="ghost"
            size="icon"
            className="rounded-xl md:hidden"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="菜单"
          >
            {mobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </Button>
        </div>
      </div>

      {mobileMenuOpen && (
        <div className="border-t border-border/70 bg-background/95 px-4 py-3 md:hidden">
          <div className="space-y-1">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMobileMenuOpen(false)}
                className={cn('flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium', isActive(item.href) ? 'bg-primary/10 text-primary' : 'text-muted-foreground')}
              >
                <item.icon className="h-5 w-5" />
                {item.label}
              </Link>
            ))}
          </div>
        </div>
      )}
    </nav>
  );
}

export function NavbarAuth() {
  return (
    <nav className="page-header">
      <div className="mx-auto flex h-16 w-full max-w-[1360px] items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link href="/" className="flex items-center gap-2.5">
          <BrandMark />
          <span className="text-base font-semibold tracking-tight text-foreground">智汇 AI 工作台</span>
        </Link>
        <Link
          href="/"
          className="inline-flex h-10 items-center rounded-xl bg-brand-gradient px-5 text-sm font-semibold text-white shadow-sm transition-all hover:shadow-glow"
        >
          开始使用
        </Link>
      </div>
    </nav>
  );
}
