# ============================================
# API Gateway - Dockerfile (Multi-stage)
# ============================================

# Base image
FROM node:20-alpine AS base

# Install dependencies only when needed
FROM base AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

# Copy package files
COPY package.json pnpm-lock.yaml* ./
COPY packages/shared-types/package.json ./packages/shared-types/
COPY packages/config/package.json ./packages/config/
COPY packages/ui-components/package.json ./packages/ui-components/
COPY services/api-gateway/package.json ./services/api-gateway/

# Install dependencies
RUN npm install -g pnpm@9 && pnpm install --frozen-lockfile

# Builder stage
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Generate Prisma client if needed
# RUN pnpm db:generate

# Build the application
RUN pnpm build --filter=api-gateway...

# Production dependencies only
FROM base AS prod-deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

COPY package.json pnpm-lock.yaml* ./
COPY packages/shared-types/package.json ./packages/shared-types/
COPY packages/config/package.json ./packages/config/
COPY packages/ui-components/package.json ./packages/ui-components/
COPY services/api-gateway/package.json ./services/api-gateway/

RUN npm install -g pnpm@9 && pnpm install --prod --frozen-lockfile

# Production runner
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production

# Create non-root user
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# Copy built application
COPY --from=builder /app/services/api-gateway/dist ./services/api-gateway/dist
COPY --from=builder /app/packages/shared-types/dist ./packages/shared-types/dist
COPY --from=builder /app/packages/config/dist ./packages/config/dist
COPY --from=prod-deps /app/node_modules ./node_modules
COPY --from=builder /app/services/api-gateway/package.json ./services/api-gateway/package.json

# Set ownership
RUN chown -R nextjs:nodejs /app
USER nextjs

EXPOSE 8000

CMD ["node", "services/api-gateway/dist/main.js"]

# ============================================
# Development stage (used by docker-compose)
# ============================================

FROM base AS development
WORKDIR /app

# Install all dependencies including dev
COPY package.json pnpm-lock.yaml* ./
COPY packages/shared-types/package.json ./packages/shared-types/
COPY packages/config/package.json ./packages/config/
COPY packages/ui-components/package.json ./packages/ui-components/
COPY services/api-gateway/package.json ./services/api-gateway/

RUN npm install -g pnpm@9 && pnpm install --frozen-lockfile

# Copy source code
COPY . .

EXPOSE 8000

# Use tsx for TypeScript execution in dev
CMD ["pnpm", "dev", "--filter=api-gateway"]