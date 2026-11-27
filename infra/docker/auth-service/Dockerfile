# ============================================
# Auth Service - Dockerfile
# ============================================

FROM node:20-alpine AS base

FROM base AS deps
RUN apk add --no-cache libc6-compat python3 make g++
WORKDIR /app

COPY package.json pnpm-lock.yaml* ./
COPY packages/shared-types/package.json ./packages/shared-types/
COPY packages/config/package.json ./packages/config/
COPY services/auth-service/package.json ./services/auth-service/

RUN npm install -g pnpm@9 && pnpm install --frozen-lockfile

FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build --filter=auth-service...

FROM base AS prod-deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

COPY package.json pnpm-lock.yaml* ./
COPY packages/shared-types/package.json ./packages/shared-types/
COPY packages/config/package.json ./packages/config/
COPY services/auth-service/package.json ./services/auth-service/

RUN npm install -g pnpm@9 && pnpm install --prod --frozen-lockfile

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

COPY --from=builder /app/services/auth-service/dist ./services/auth-service/dist
COPY --from=builder /app/packages/shared-types/dist ./packages/shared-types/dist
COPY --from=builder /app/packages/config/dist ./packages/config/dist
COPY --from=prod-deps /app/node_modules ./node_modules
COPY --from=builder /app/services/auth-service/package.json ./services/auth-service/package.json

RUN chown -R nextjs:nodejs /app
USER nextjs

EXPOSE 8000

CMD ["node", "services/auth-service/dist/main.js"]

FROM base AS development
WORKDIR /app

COPY package.json pnpm-lock.yaml* ./
COPY packages/shared-types/package.json ./packages/shared-types/
COPY packages/config/package.json ./packages/config/
COPY services/auth-service/package.json ./services/auth-service/

RUN npm install -g pnpm@9 && pnpm install --frozen-lockfile

COPY . .

EXPOSE 8000

CMD ["pnpm", "dev", "--filter=auth-service"]