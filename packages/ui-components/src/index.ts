/**
 * UI Components 统一导出
 */

// 基础组件
export { Button, buttonVariants } from './components/Button';
export {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from './components/Card';
export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
} from './components/Dialog';
export { Input } from './components/Input';
export { Label } from './components/Label';

// 工具函数
export {
  buildUrl,
  camelToKebab,
  capitalize,
  cn,
  debounce,
  deepClone,
  formatBytes,
  formatDate,
  formatDateTime,
  formatDuration,
  formatNumber,
  formatRelativeTime,
  generateId,
  generateUUID,
  hexToRgb,
  isEmpty,
  kebabToCamel,
  omit,
  parseQueryString,
  pick,
  retry,
  rgbToHex,
  sleep,
  slugify,
  throttle,
  timeout,
  truncate,
} from './lib/utils';

// 样式文件（需在构建后复制到 dist）
export {} from './styles.css';
