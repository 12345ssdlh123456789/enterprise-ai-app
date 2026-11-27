// 统一配置管理 - 使用 Zod 进行环境变量验证

import * as dotenv from 'dotenv';
import { z } from 'zod';

// 加载环境变量
dotenv.config({ path: process.env.ENV_FILE ?? '.env' });

// ============ 环境变量 Schema ============

const EnvSchema = z.object({
  // 应用基础
  NODE_ENV: z.enum(['development', 'test', 'staging', 'production']).default('development'),
  APP_NAME: z.string().default('Enterprise AI App'),
  APP_VERSION: z.string().default('0.0.1'),
  APP_PORT: z.coerce.number().default(3000),
  APP_HOST: z.string().default('0.0.0.0'),
  API_PREFIX: z.string().default('/api/v1'),

  // 数据库
  DATABASE_URL: z.string().url().or(z.string().startsWith('postgresql://')),
  DATABASE_POOL_SIZE: z.coerce.number().default(20),
  DATABASE_MAX_OVERFLOW: z.coerce.number().default(10),
  DATABASE_POOL_TIMEOUT: z.coerce.number().default(30),
  DATABASE_ECHO: z.coerce.boolean().default(false),

  // Redis
  REDIS_URL: z.string().url().or(z.string().startsWith('redis://')),
  REDIS_MAX_RETRIES: z.coerce.number().default(3),
  REDIS_RETRY_DELAY: z.coerce.number().default(100),
  REDIS_CONNECT_TIMEOUT: z.coerce.number().default(10000),

  // 认证
  JWT_SECRET: z.string().min(32),
  JWT_ACCESS_TOKEN_EXPIRY: z.string().default('15m'),
  JWT_REFRESH_TOKEN_EXPIRY: z.string().default('7d'),
  JWT_ALGORITHM: z.enum(['HS256', 'RS256']).default('HS256'),
  BCRYPT_ROUNDS: z.coerce.number().default(12),

  // OAuth2 / SSO
  OAUTH2_ENABLED: z.coerce.boolean().default(false),
  OAUTH2_PROVIDER: z.enum(['google', 'github', 'microsoft', 'custom']).optional(),
  OAUTH2_CLIENT_ID: z.string().optional(),
  OAUTH2_CLIENT_SECRET: z.string().optional(),
  OAUTH2_CALLBACK_URL: z.string().url().optional(),
  OAUTH2_SCOPE: z.string().optional(),

  // LLM 提供商
  OPENAI_API_KEY: z.string().optional(),
  OPENAI_ORG_ID: z.string().optional(),
  OPENAI_BASE_URL: z.string().url().optional(),
  ANTHROPIC_API_KEY: z.string().optional(),
  ANTHROPIC_BASE_URL: z.string().url().optional(),
  AZURE_OPENAI_API_KEY: z.string().optional(),
  AZURE_OPENAI_ENDPOINT: z.string().url().optional(),
  AZURE_OPENAI_API_VERSION: z.string().optional(),
  AZURE_OPENAI_DEPLOYMENT: z.string().optional(),
  OLLAMA_BASE_URL: z.string().url().optional(),
  VLLM_BASE_URL: z.string().url().optional(),

  // 默认模型
  DEFAULT_CHAT_MODEL: z.string().default('gpt-4o-mini'),
  DEFAULT_EMBEDDING_MODEL: z.string().default('text-embedding-3-small'),
  DEFAULT_RERANK_MODEL: z.string().optional(),

  // 向量数据库
  VECTOR_DB_PROVIDER: z
    .enum(['pgvector', 'chroma', 'pinecone', 'weaviate', 'qdrant'])
    .default('pgvector'),
  VECTOR_DB_URL: z.string().optional(),
  VECTOR_DB_API_KEY: z.string().optional(),
  VECTOR_DB_INDEX_NAME: z.string().default('enterprise_ai'),

  // RAG 配置
  DEFAULT_CHUNK_SIZE: z.coerce.number().default(1000),
  DEFAULT_CHUNK_OVERLAP: z.coerce.number().default(200),
  DEFAULT_TOP_K: z.coerce.number().default(5),
  DEFAULT_SCORE_THRESHOLD: z.coerce.number().default(0.7),
  ENABLE_HYBRID_SEARCH: z.coerce.boolean().default(true),
  ENABLE_RERANK: z.coerce.boolean().default(true),

  // 文件上传
  MAX_FILE_SIZE_MB: z.coerce.number().default(50),
  ALLOWED_FILE_TYPES: z.string().default('pdf,docx,txt,md,html,csv,json,pptx,xlsx'),
  UPLOAD_DIR: z.string().default('./uploads'),
  TEMP_DIR: z.string().default('./tmp'),

  // 限流
  RATE_LIMIT_WINDOW_MS: z.coerce.number().default(60000),
  RATE_LIMIT_MAX_REQUESTS: z.coerce.number().default(100),
  RATE_LIMIT_MAX_TOKENS: z.coerce.number().default(100000),

  // 任务队列
  CELERY_BROKER_URL: z.string().url().or(z.string().startsWith('redis://')).optional(),
  CELERY_RESULT_BACKEND: z.string().url().or(z.string().startsWith('redis://')).optional(),
  CELERY_TASK_SERIALIZER: z.string().default('json'),
  CELERY_RESULT_SERIALIZER: z.string().default('json'),
  CELERY_TIMEZONE: z.string().default('UTC'),

  // 监控
  ENABLE_METRICS: z.coerce.boolean().default(true),
  METRICS_PORT: z.coerce.number().default(9090),
  ENABLE_TRACING: z.coerce.boolean().default(true),
  JAEGER_ENDPOINT: z.string().url().optional(),
  OTEL_EXPORTER_OTLP_ENDPOINT: z.string().url().optional(),
  LOG_LEVEL: z.enum(['debug', 'info', 'warn', 'error']).default('info'),
  LOG_FORMAT: z.enum(['json', 'pretty']).default('json'),

  // 存储
  STORAGE_PROVIDER: z.enum(['local', 's3', 'minio', 'azure-blob', 'gcs']).default('local'),
  S3_ENDPOINT: z.string().url().optional(),
  S3_BUCKET: z.string().optional(),
  S3_ACCESS_KEY: z.string().optional(),
  S3_SECRET_KEY: z.string().optional(),
  S3_REGION: z.string().optional(),

  // 邮件
  SMTP_HOST: z.string().optional(),
  SMTP_PORT: z.coerce.number().default(587),
  SMTP_USER: z.string().optional(),
  SMTP_PASS: z.string().optional(),
  SMTP_FROM: z.string().email().optional(),
  EMAIL_ENABLED: z.coerce.boolean().default(false),

  // Webhook
  WEBHOOK_SECRET: z.string().optional(),
  WEBHOOK_TIMEOUT_MS: z.coerce.number().default(30000),
  WEBHOOK_MAX_RETRIES: z.coerce.number().default(3),

  // 成本控制
  DEFAULT_MONTHLY_TOKEN_BUDGET: z.coerce.number().default(1000000),
  COST_ALERT_THRESHOLD: z.coerce.number().default(0.8),
  ENABLE_COST_TRACKING: z.coerce.boolean().default(true),

  // 安全
  CORS_ORIGINS: z.string().default('http://localhost:3000,http://localhost:3001'),
  CSRF_SECRET: z.string().optional(),
  HELMET_ENABLED: z.coerce.boolean().default(true),
  RATE_LIMIT_ENABLED: z.coerce.boolean().default(true),

  // 功能开关
  ENABLE_RAG: z.coerce.boolean().default(true),
  ENABLE_WORKFLOWS: z.coerce.boolean().default(true),
  ENABLE_MULTIMODAL: z.coerce.boolean().default(false),
  ENABLE_ANALYTICS: z.coerce.boolean().default(true),
  ENABLE_AUDIT_LOG: z.coerce.boolean().default(true),
});

// ============ 类型导出 ============

export type EnvConfig = z.infer<typeof EnvSchema>;

// ============ 解析与验证 ============

let cachedConfig: EnvConfig | null = null;

export function getConfig(): EnvConfig {
  if (cachedConfig) {
    return cachedConfig;
  }

  const result = EnvSchema.safeParse(process.env);

  if (!result.success) {
    const errors = result.error.flatten().fieldErrors;
    const errorMessages = Object.entries(errors)
      .map(([field, msgs]) => `${field}: ${msgs.join(', ')}`)
      .join('\n');

    throw new Error(`配置验证失败:\n${errorMessages}`);
  }

  cachedConfig = result.data;
  return cachedConfig;
}

export function resetConfig(): void {
  cachedConfig = null;
}

// ============ 便捷访问器 ============

const config = getConfig();

export const app = {
  name: config.APP_NAME,
  version: config.APP_VERSION,
  port: config.APP_PORT,
  host: config.APP_HOST,
  env: config.NODE_ENV,
  apiPrefix: config.API_PREFIX,
  isDevelopment: config.NODE_ENV === 'development',
  isProduction: config.NODE_ENV === 'production',
  isTest: config.NODE_ENV === 'test',
};

export const database = {
  url: config.DATABASE_URL,
  poolSize: config.DATABASE_POOL_SIZE,
  maxOverflow: config.DATABASE_MAX_OVERFLOW,
  poolTimeout: config.DATABASE_POOL_TIMEOUT,
  echo: config.DATABASE_ECHO,
};

export const redis = {
  url: config.REDIS_URL,
  maxRetries: config.REDIS_MAX_RETRIES,
  retryDelay: config.REDIS_RETRY_DELAY,
  connectTimeout: config.REDIS_CONNECT_TIMEOUT,
};

export const auth = {
  jwtSecret: config.JWT_SECRET,
  accessTokenExpiry: config.JWT_ACCESS_TOKEN_EXPIRY,
  refreshTokenExpiry: config.JWT_REFRESH_TOKEN_EXPIRY,
  algorithm: config.JWT_ALGORITHM,
  bcryptRounds: config.BCRYPT_ROUNDS,
  oauth2: {
    enabled: config.OAUTH2_ENABLED,
    provider: config.OAUTH2_PROVIDER,
    clientId: config.OAUTH2_CLIENT_ID,
    clientSecret: config.OAUTH2_CLIENT_SECRET,
    callbackUrl: config.OAUTH2_CALLBACK_URL,
    scope: config.OAUTH2_SCOPE,
  },
};

export const llm = {
  openai: {
    apiKey: config.OPENAI_API_KEY,
    orgId: config.OPENAI_ORG_ID,
    baseUrl: config.OPENAI_BASE_URL,
  },
  anthropic: {
    apiKey: config.ANTHROPIC_API_KEY,
    baseUrl: config.ANTHROPIC_BASE_URL,
  },
  azureOpenai: {
    apiKey: config.AZURE_OPENAI_API_KEY,
    endpoint: config.AZURE_OPENAI_ENDPOINT,
    apiVersion: config.AZURE_OPENAI_API_VERSION,
    deployment: config.AZURE_OPENAI_DEPLOYMENT,
  },
  ollama: {
    baseUrl: config.OLLAMA_BASE_URL,
  },
  vllm: {
    baseUrl: config.VLLM_BASE_URL,
  },
  defaults: {
    chatModel: config.DEFAULT_CHAT_MODEL,
    embeddingModel: config.DEFAULT_EMBEDDING_MODEL,
    rerankModel: config.DEFAULT_RERANK_MODEL,
  },
};

export const vectorDb = {
  provider: config.VECTOR_DB_PROVIDER,
  url: config.VECTOR_DB_URL,
  apiKey: config.VECTOR_DB_API_KEY,
  indexName: config.VECTOR_DB_INDEX_NAME,
};

export const rag = {
  chunkSize: config.DEFAULT_CHUNK_SIZE,
  chunkOverlap: config.DEFAULT_CHUNK_OVERLAP,
  topK: config.DEFAULT_TOP_K,
  scoreThreshold: config.DEFAULT_SCORE_THRESHOLD,
  enableHybridSearch: config.ENABLE_HYBRID_SEARCH,
  enableRerank: config.ENABLE_RERANK,
};

export const upload = {
  maxFileSizeMB: config.MAX_FILE_SIZE_MB,
  allowedFileTypes: config.ALLOWED_FILE_TYPES.split(',').map((t) => t.trim()),
  uploadDir: config.UPLOAD_DIR,
  tempDir: config.TEMP_DIR,
};

export const rateLimit = {
  windowMs: config.RATE_LIMIT_WINDOW_MS,
  maxRequests: config.RATE_LIMIT_MAX_REQUESTS,
  maxTokens: config.RATE_LIMIT_MAX_TOKENS,
  enabled: config.RATE_LIMIT_ENABLED,
};

export const celery = {
  brokerUrl: config.CELERY_BROKER_URL ?? config.REDIS_URL,
  resultBackend: config.CELERY_RESULT_BACKEND ?? config.REDIS_URL,
  taskSerializer: config.CELERY_TASK_SERIALIZER,
  resultSerializer: config.CELERY_RESULT_SERIALIZER,
  timezone: config.CELERY_TIMEZONE,
};

export const monitoring = {
  enableMetrics: config.ENABLE_METRICS,
  metricsPort: config.METRICS_PORT,
  enableTracing: config.ENABLE_TRACING,
  jaegerEndpoint: config.JAEGER_ENDPOINT,
  otelEndpoint: config.OTEL_EXPORTER_OTLP_ENDPOINT,
  logLevel: config.LOG_LEVEL,
  logFormat: config.LOG_FORMAT,
};

export const storage = {
  provider: config.STORAGE_PROVIDER,
  s3: {
    endpoint: config.S3_ENDPOINT,
    bucket: config.S3_BUCKET,
    accessKey: config.S3_ACCESS_KEY,
    secretKey: config.S3_SECRET_KEY,
    region: config.S3_REGION,
  },
};

export const email = {
  enabled: config.EMAIL_ENABLED,
  smtp: {
    host: config.SMTP_HOST,
    port: config.SMTP_PORT,
    user: config.SMTP_USER,
    pass: config.SMTP_PASS,
    from: config.SMTP_FROM,
  },
};

export const webhook = {
  secret: config.WEBHOOK_SECRET,
  timeoutMs: config.WEBHOOK_TIMEOUT_MS,
  maxRetries: config.WEBHOOK_MAX_RETRIES,
};

export const cost = {
  defaultMonthlyTokenBudget: config.DEFAULT_MONTHLY_TOKEN_BUDGET,
  alertThreshold: config.COST_ALERT_THRESHOLD,
  enableTracking: config.ENABLE_COST_TRACKING,
};

export const security = {
  corsOrigins: config.CORS_ORIGINS.split(',').map((o) => o.trim()),
  csrfSecret: config.CSRF_SECRET,
  helmetEnabled: config.HELMET_ENABLED,
  rateLimitEnabled: config.RATE_LIMIT_ENABLED,
};

export const features = {
  enableRag: config.ENABLE_RAG,
  EnableWorkflows: config.ENABLE_WORKFLOWS,
  enableMultimodal: config.ENABLE_MULTIMODAL,
  enableAnalytics: config.ENABLE_ANALYTICS,
  enableAuditLog: config.ENABLE_AUDIT_LOG,
};

// ============ 配置验证工具 ============

export function validateRequiredKeys(keys: (keyof EnvConfig)[]): void {
  const config = getConfig();
  const missing = keys.filter((key) => !config[key]);
  if (missing.length > 0) {
    throw new Error(`缺少必需配置: ${missing.join(', ')}`);
  }
}

export function assertProductionReady(): void {
  const config = getConfig();

  if (config.NODE_ENV === 'production') {
    const checks = [
      { key: 'JWT_SECRET', value: config.JWT_SECRET, minLength: 64 },
      { key: 'DATABASE_URL', value: config.DATABASE_URL },
      { key: 'REDIS_URL', value: config.REDIS_URL },
    ];

    const failures = checks.filter(
      (c) => !c.value || (c.minLength && c.value.length < c.minLength)
    );

    if (failures.length > 0) {
      throw new Error(`生产环境配置不完整: ${failures.map((f) => f.key).join(', ')}`);
    }

    if (config.JWT_ALGORITHM === 'HS256' && config.JWT_SECRET.length < 64) {
      console.warn('⚠️  生产环境建议使用 RS256 算法或至少 64 字符的 HS256 密钥');
    }
  }
}

// 导出原始配置对象（用于高级用法）
export { config as rawConfig };
