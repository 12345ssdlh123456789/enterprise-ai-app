import '@testing-library/jest-dom';
import { vi, beforeAll, afterAll } from 'vitest';

// Mock next/navigation
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
  useSearchParams: () => ({
    get: vi.fn(),
    getAll: vi.fn(),
    has: vi.fn(),
    keys: vi.fn(),
    values: vi.fn(),
    entries: vi.fn(),
    forEach: vi.fn(),
    toString: vi.fn(),
  }),
  usePathname: () => '/',
  useParams: () => ({}),
}));

// Mock next-auth
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: null,
    status: 'unauthenticated',
  }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));

// Mock sonner toast
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    loading: vi.fn(),
    dismiss: vi.fn(),
    promise: vi.fn(),
  },
  Toaster: () => null,
}));

// Mock lucide-react icons
vi.mock('lucide-react', () => {
  const icons = [
    'Loader2', 'ChevronLeft', 'Save', 'Play', 'CheckCircle', 'AlertTriangle',
    'GitBranch', 'FileText', 'Plus', 'Search', 'Edit', 'Trash2', 'Copy',
    'Settings', 'X', 'Sparkles', 'Upload', 'MessageSquare', 'Users',
    'DollarSign', 'Activity', 'Shield', 'BarChart3', 'MoreHorizontal',
    'ChevronDown', 'Check', 'ThumbsUp', 'ThumbsDown', 'Flag', 'Mic',
    'Paperclip', 'Send', 'Loader', 'Pause', 'Stop', 'RotateCcw',
    'Target', 'PieChart', 'AreaChart', 'Eye', 'Download', 'Filter',
    'Calendar', 'Trash2', 'Bell', 'Zap', 'ArrowLeft', 'ArrowRight',
    'Home', 'Menu', 'Mail', 'Lock', 'Unlock', 'User', 'LogOut',
    'RefreshCw', 'Info', 'Warning', 'HelpCircle', 'ExternalLink',
    'Copy', 'Clipboard', 'Hash', 'Code', 'Database', 'Server',
    'Brain', 'Globe', 'Network', 'Cpu', 'MemoryStick', 'HardDrive',
    'Monitor', 'Smartphone', 'Tablet', 'Printer', 'Camera', 'Video',
    'Music', 'Image', 'File', 'Folder', 'Archive', 'Trash',
    'Edit', 'Delete', 'Plus', 'Minus', 'Check', 'X', 'Star',
    'Heart', 'Share', 'Link', 'Unlink', 'Lock', 'Unlock',
    'Eye', 'EyeOff', 'Search', 'Filter', 'SortAsc', 'SortDesc',
    'Grid', 'List', 'Layers', 'Box', 'Package', 'Truck',
    'Ship', 'Plane', 'Car', 'Bike', 'Walk', 'Run',
    'Sun', 'Moon', 'Cloud', 'Rain', 'Snow', 'Wind',
    'Fire', 'Water', 'Earth', 'Leaf', 'Tree', 'Flower',
    'Bird', 'Fish', 'Dog', 'Cat', 'Mouse', 'Rabbit',
    'Bear', 'Lion', 'Tiger', 'Elephant', 'Giraffe', 'Zebra',
    'Horse', 'Cow', 'Pig', 'Sheep', 'Chicken', 'Duck',
    'Frog', 'Snake', 'Turtle', 'Lizard', 'Spider', 'Ant',
    'Bee', 'Butterfly', 'Dragonfly', 'Mosquito', 'Fly', 'Wasp',
  ];
  const mockIcons: Record<string, any> = {};
  icons.forEach(name => {
    mockIcons[name] = (props: any) => <svg {...props} data-testid={name.toLowerCase()} />;
  });
  return mockIcons;
});

// Mock reactflow
vi.mock('reactflow', () => ({
  Node: vi.fn(),
  Edge: vi.fn(),
  addEdge: vi.fn(),
  Connection: vi.fn(),
  ReactFlow: vi.fn(({ children }: any) => <div data-testid="reactflow">{children}</div>),
  Controls: vi.fn(() => <div data-testid="controls" />),
  Background: vi.fn(() => <div data-testid="background" />),
  MiniMap: vi.fn(() => <div data-testid="minimap" />),
  Panel: vi.fn(({ children }: any) => <div data-testid="panel">{children}</div>),
  useNodesState: vi.fn((initial: any) => [initial, vi.fn()]),
  useEdgesState: vi.fn((initial: any) => [initial, vi.fn()]),
  OnNodesChange: vi.fn(),
  OnEdgesChange: vi.fn(),
  OnConnect: vi.fn(),
  NodeTypes: vi.fn(),
  EdgeTypes: vi.fn(),
  Handle: vi.fn(),
  Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' },
  MarkerType: { ArrowClosed: 'arrowclosed' },
}));

// Mock Radix UI components
vi.mock('@radix-ui/react-dialog', () => ({
  Dialog: ({ children, open, onOpenChange }: any) => open ? <div data-testid="dialog">{children}</div> : null,
  DialogTrigger: ({ children }: any) => <span data-testid="dialog-trigger">{children}</span>,
  DialogContent: ({ children }: any) => <div data-testid="dialog-content">{children}</div>,
  DialogHeader: ({ children }: any) => <div data-testid="dialog-header">{children}</div>,
  DialogTitle: ({ children }: any) => <h2 data-testid="dialog-title">{children}</h2>,
  DialogDescription: ({ children }: any) => <p data-testid="dialog-description">{children}</p>,
  DialogFooter: ({ children }: any) => <div data-testid="dialog-footer">{children}</div>,
  DialogClose: ({ children }: any) => <button data-testid="dialog-close">{children}</button>,
}));

vi.mock('@radix-ui/react-select', () => ({
  Select: ({ children }: any) => <div data-testid="select">{children}</div>,
  SelectTrigger: ({ children }: any) => <button data-testid="select-trigger">{children}</button>,
  SelectValue: ({ placeholder }: any) => <span data-testid="select-value">{placeholder}</span>,
  SelectContent: ({ children }: any) => <div data-testid="select-content">{children}</div>,
  SelectItem: ({ children, value }: any) => <div data-testid="select-item" data-value={value}>{children}</div>,
  SelectSeparator: () => <hr data-testid="select-separator" />,
  SelectScrollUpButton: () => <button data-testid="select-scroll-up" />,
  SelectScrollDownButton: () => <button data-testid="select-scroll-down" />,
  SelectGroup: ({ children }: any) => <div data-testid="select-group">{children}</div>,
  SelectLabel: ({ children }: any) => <div data-testid="select-label">{children}</div>,
}));

vi.mock('@radix-ui/react-tabs', () => ({
  Tabs: ({ children, value, onValueChange }: any) => <div data-testid="tabs">{children}</div>,
  TabsList: ({ children }: any) => <div data-testid="tabs-list" role="tablist">{children}</div>,
  TabsTrigger: ({ children, value }: any) => <button data-testid="tabs-trigger" data-value={value} role="tab">{children}</button>,
  TabsContent: ({ children, value }: any) => <div data-testid="tabs-content" data-value={value}>{children}</div>,
}));

vi.mock('@radix-ui/react-toast', () => ({
  ToastProvider: ({ children }: any) => <div data-testid="toast-provider">{children}</div>,
  ToastViewport: ({ children }: any) => <div data-testid="toast-viewport">{children}</div>,
  Toast: ({ children }: any) => <div data-testid="toast">{children}</div>,
  ToastTitle: ({ children }: any) => <div data-testid="toast-title">{children}</div>,
  ToastDescription: ({ children }: any) => <div data-testid="toast-description">{children}</div>,
  ToastClose: () => <button data-testid="toast-close" />,
  ToastAction: ({ children }: any) => <button data-testid="toast-action">{children}</button>,
}));

vi.mock('@radix-ui/react-dropdown-menu', () => ({
  DropdownMenu: ({ children }: any) => <div data-testid="dropdown-menu">{children}</div>,
  DropdownMenuTrigger: ({ children }: any) => <button data-testid="dropdown-trigger">{children}</button>,
  DropdownMenuContent: ({ children }: any) => <div data-testid="dropdown-content">{children}</div>,
  DropdownMenuItem: ({ children, onSelect }: any) => <button data-testid="dropdown-item" onClick={onSelect}>{children}</button>,
  DropdownMenuSeparator: () => <hr data-testid="dropdown-separator" />,
  DropdownMenuLabel: ({ children }: any) => <div data-testid="dropdown-label">{children}</div>,
  DropdownMenuShortcut: ({ children }: any) => <span data-testid="dropdown-shortcut">{children}</span>,
}));

vi.mock('@radix-ui/react-tooltip', () => ({
  TooltipProvider: ({ children }: any) => <div data-testid="tooltip-provider">{children}</div>,
  Tooltip: ({ children }: any) => <div data-testid="tooltip">{children}</div>,
  TooltipTrigger: ({ children }: any) => <span data-testid="tooltip-trigger">{children}</span>,
  TooltipContent: ({ children }: any) => <div data-testid="tooltip-content">{children}</div>,
  TooltipArrow: () => <div data-testid="tooltip-arrow" />,
}));

vi.mock('@radix-ui/react-avatar', () => ({
  Avatar: ({ children }: any) => <div data-testid="avatar">{children}</div>,
  AvatarImage: ({ src }: any) => <img src={src} data-testid="avatar-image" />,
  AvatarFallback: ({ children }: any) => <div data-testid="avatar-fallback">{children}</div>,
}));

vi.mock('@radix-ui/react-separator', () => ({
  Separator: ({ orientation = 'horizontal' }: any) => <hr data-testid="separator" data-orientation={orientation} />,
}));

vi.mock('@radix-ui/react-scroll-area', () => ({
  ScrollArea: ({ children }: any) => <div data-testid="scroll-area">{children}</div>,
  ScrollBar: () => <div data-testid="scroll-bar" />,
}));

vi.mock('@radix-ui/react-slider', () => ({
  Slider: ({ children }: any) => <div data-testid="slider">{children}</div>,
  SliderTrack: () => <div data-testid="slider-track" />,
  SliderRange: () => <div data-testid="slider-range" />,
  SliderThumb: () => <div data-testid="slider-thumb" />,
}));

vi.mock('@radix-ui/react-switch', () => ({
  Switch: ({ checked, onCheckedChange, ...props }: any) => (
    <button
      data-testid="switch"
      data-checked={checked}
      onClick={() => onCheckedChange(!checked)}
      {...props}
    />
  ),
}));

// Mock sonner
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    loading: vi.fn(),
    dismiss: vi.fn(),
    promise: vi.fn(),
  },
  Toaster: () => <div data-testid="toaster" />,
}));

// Mock API client
vi.mock('@/lib/api', () => ({
  api: {
    getWorkflows: vi.fn().mockResolvedValue([]),
    getWorkflow: vi.fn().mockResolvedValue({ id: '1', name: 'Test Workflow', definition: { nodes: [], edges: [] } }),
    createWorkflow: vi.fn().mockResolvedValue({ id: '1' }),
    updateWorkflow: vi.fn().mockResolvedValue({}),
    deleteWorkflow: vi.fn().mockResolvedValue({}),
    validateWorkflowDefinition: vi.fn().mockResolvedValue({ valid: true, errors: [], warnings: [] }),
    executeWorkflow: vi.fn().mockResolvedValue({ status: 'completed' }),
    getKnowledgeBases: vi.fn().mockResolvedValue([]),
    getModels: vi.fn().mockResolvedValue({ data: [{ id: 'gpt-4o-mini' }] }),
    getConversations: vi.fn().mockResolvedValue([]),
    getConversation: vi.fn().mockResolvedValue({ messages: [] }),
    createConversation: vi.fn().mockResolvedValue({ id: '1' }),
    sendMessage: vi.fn().mockResolvedValue({}),
    getUsageRecords: vi.fn().mockResolvedValue([]),
    getCostSummary: vi.fn().mockResolvedValue({ total_cost_usd: 0 }),
    healthCheck: vi.fn().mockResolvedValue({ status: 'healthy' }),
    getAuth: vi.fn().mockResolvedValue({ user: null }),
    login: vi.fn().mockResolvedValue({}),
    logout: vi.fn().mockResolvedValue({}),
    register: vi.fn().mockResolvedValue({}),
    getMe: vi.fn().mockResolvedValue({ user: { id: '1', email: 'test@test.com', full_name: 'Test User', role: 'ADMIN', is_active: true, created_at: new Date().toISOString() }, tenant: { id: '1', name: 'Test Tenant', slug: 'test', settings: {} } }),
  },
}));

// Mock auth context
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    user: { id: '1', email: 'test@test.com', full_name: 'Test User', role: 'ADMIN', is_active: true },
    tenant: { id: '1', name: 'Test Tenant', slug: 'test', settings: {} },
    isLoading: false,
    isAuthenticated: true,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    refreshTokens: vi.fn(),
  }),
  AuthProvider: ({ children }: any) => <div data-testid="auth-provider">{children}</div>,
}));

// Mock react-hot-toast or similar
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: any) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Mock ResizeObserver
global.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));

// Mock IntersectionObserver
global.IntersectionObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));

// Suppress console.error in tests (optional)
const originalError = console.error;
beforeAll(() => {
  console.error = (...args) => {
    if (args[0]?.includes?.('Warning: ReactDOM.render is no longer supported')) return;
    originalError.call(console, ...args);
  };
});

afterAll(() => {
  console.error = originalError;
});