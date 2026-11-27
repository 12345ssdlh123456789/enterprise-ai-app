import { describe, it, expect } from 'vitest';
import {
  cn,
  formatBytes,
  formatNumber,
  truncate,
  getInitials,
  parseError,
  isValidUrl,
  formatRelativeTime,
} from '@/lib/utils';

describe('admin lib/utils', () => {
  it('cn 合并冲突的 Tailwind 类', () => {
    expect(cn('p-2', 'p-4')).toBe('p-4');
    expect(cn('text-sm', undefined, false, 'font-bold')).toBe('text-sm font-bold');
  });

  it('formatBytes 处理 0 与各单位', () => {
    expect(formatBytes(0)).toBe('0 Bytes');
    expect(formatBytes(1024)).toBe('1 KB');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(1024 * 1024)).toBe('1 MB');
  });

  it('formatNumber 在千 / 百万处缩写', () => {
    expect(formatNumber(999)).toBe('999');
    expect(formatNumber(1500)).toBe('1.5K');
    expect(formatNumber(2_400_000)).toBe('2.4M');
  });

  it('truncate 超长才加省略号', () => {
    expect(truncate('abc', 5)).toBe('abc');
    expect(truncate('abcdef', 3)).toBe('abc...');
  });

  it('getInitials 取前两个首字母并大写', () => {
    expect(getInitials('ada lovelace')).toBe('AL');
    expect(getInitials('buffy')).toBe('B');
  });

  it('parseError 覆盖 Error / 字符串 / detail / 未知', () => {
    expect(parseError(new Error('boom'))).toBe('boom');
    expect(parseError('文本错误')).toBe('文本错误');
    expect(parseError({ detail: '后端详情' })).toBe('后端详情');
    expect(parseError(42)).toBe('发生未知错误');
  });

  it('isValidUrl 只接受可解析的绝对地址', () => {
    expect(isValidUrl('https://example.com/a')).toBe(true);
    expect(isValidUrl('not a url')).toBe(false);
  });

  it('formatRelativeTime 覆盖刚刚 / 分钟 / 小时 / 天', () => {
    const now = Date.now();
    expect(formatRelativeTime(new Date(now - 5_000))).toBe('刚刚');
    expect(formatRelativeTime(new Date(now - 5 * 60_000))).toBe('5 分钟前');
    expect(formatRelativeTime(new Date(now - 3 * 3600_000))).toBe('3 小时前');
    expect(formatRelativeTime(new Date(now - 2 * 86400_000))).toBe('2 天前');
  });
});
