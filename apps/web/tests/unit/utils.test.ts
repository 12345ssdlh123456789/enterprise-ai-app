import { describe, it, expect, vi } from 'vitest';
import { cn, formatBytes, formatNumber, formatCurrency, formatRelativeTime, truncate, getInitials } from '@/lib/utils';

describe('lib/utils', () => {
  describe('cn', () => {
    it('joins class names with spaces', () => {
      expect(cn('a', 'b', 'c')).toBe('a b c');
    });

    it('filters out falsy values', () => {
      expect(cn('a', false && 'b', 'c')).toBe('a c');
      expect(cn('a', null, 'b', undefined, 'c')).toBe('a b c');
    });

    it('handles empty arguments', () => {
      expect(cn()).toBe('');
    });
  });

  describe('formatBytes', () => {
    it('formats bytes correctly', () => {
      expect(formatBytes(0)).toBe('0 Bytes');
      expect(formatBytes(1024)).toBe('1 KB');
      expect(formatBytes(1024 * 1024)).toBe('1 MB');
      expect(formatBytes(1024 * 1024 * 1024)).toBe('1 GB');
    });

    it('handles decimals', () => {
      expect(formatBytes(1536, 1)).toBe('1.5 KB');
    });
  });

  describe('formatNumber', () => {
    it('formats large numbers with K/M suffixes', () => {
      expect(formatNumber(500)).toBe('500');
      expect(formatNumber(1500)).toBe('1.5K');
      expect(formatNumber(1_500_000)).toBe('1.5M');
      expect(formatNumber(1_500_000_000)).toBe('1.5B');
    });
  });

  describe('formatCurrency', () => {
    it('formats currency with 2 decimal places', () => {
      expect(formatCurrency(100)).toBe('$100.00');
      expect(formatCurrency(100.5)).toBe('$100.50');
      expect(formatCurrency(0.99)).toBe('$0.99');
    });

    it('supports different currencies', () => {
      expect(formatCurrency(100, 'EUR')).toContain('€');
      expect(formatCurrency(100, 'CNY')).toContain('¥');
    });
  });

  describe('formatRelativeTime', () => {
    it('returns relative time strings', () => {
      const now = new Date();
      const oneMinuteAgo = new Date(now.getTime() - 60 * 1000);
      const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000);
      const oneDayAgo = new Date(now.getTime() - 24 * 60 * 60 * 1000);

      expect(formatRelativeTime(now)).toBe('刚刚');
      expect(formatRelativeTime(oneMinuteAgo)).toContain('分钟前');
      expect(formatRelativeTime(oneHourAgo)).toContain('小时前');
      expect(formatRelativeTime(oneDayAgo)).toContain('天前');
    });
  });

  describe('truncate', () => {
    it('truncates long strings', () => {
      expect(truncate('hello world', 8)).toBe('hello...');
      expect(truncate('short', 10)).toBe('short');
      expect(truncate('', 5)).toBe('');
    });
  });

  describe('getInitials', () => {
    it('extracts initials from names', () => {
      expect(getInitials('John Doe')).toBe('JD');
      expect(getInitials('Alice')).toBe('A');
      expect(getInitials('Bob Smith Johnson')).toBe('BS');
      expect(getInitials('')).toBe('');
    });
  });
});