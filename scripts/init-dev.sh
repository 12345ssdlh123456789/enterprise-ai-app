#!/usr/bin/env bash
# ============================================
# Enterprise AI App - 开发环境初始化脚本
# ============================================

set -euo pipefail

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 检查命令是否存在
check_command() {
    if ! command -v "$1" &> /dev/null; then
        log_error "$1 未安装，请先安装 $1"
        return 1
    fi
    log_success "$1 已安装: $(command -v $1)"
}

# 检查版本
check_version() {
    local cmd=$1
    local min_version=$2
    local current_version=$($cmd --version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1)

    if [ -z "$current_version" ]; then
        log_warn "无法获取 $cmd 版本"
        return 0
    fi

    log_info "$cmd 版本: $current_version (最低要求: $min_version)"
}

main() {
    echo "============================================"
    echo "  Enterprise AI App - 开发环境初始化"
    echo "============================================"
    echo ""

    # 1. 检查前置依赖
    log_info "检查前置依赖..."

    check_command "node" || exit 1
    check_command "pnpm" || exit 1
    check_command "docker" || exit 1
    check_command "docker-compose" || exit 1

    check_version "node" "20.0.0"
    check_version "pnpm" "9.0.0"

    # Python 可选 (用于 RAG/LLM/Document 服务)
    if command -v python3 &> /dev/null; then
        check_version "python3" "3.11"
    else
        log_warn "Python3 未安装，RAG/LLM/Document 服务将无法在本地直接运行 (可通过 Docker 运行)"
    fi

    echo ""

    # 2. 安装依赖
    log_info "安装 Node.js 依赖..."
    pnpm install --frozen-lockfile
    log_success "依赖安装完成"

    echo ""

    # 3. 检查环境变量
    log_info "检查环境变量配置..."
    if [ ! -f ".env" ]; then
        log_warn ".env 文件不存在，从 .env.example 复制"
        cp .env.example .env
        log_warn "请编辑 .env 文件填入必要的 API Key (OPENAI_API_KEY 等)"
    else
        log_success ".env 文件已存在"
    fi

    # 检查关键配置
    if grep -q "OPENAI_API_KEY=$" .env || grep -q "OPENAI_API_KEY=your" .env; then
        log_warn "OPENAI_API_KEY 未配置，AI 功能将无法工作"
    fi

    echo ""

    # 4. 启动基础设施
    log_info "启动基础设施服务 (PostgreSQL, Redis, MinIO)..."
    pnpm docker:up

    # 等待服务就绪
    log_info "等待服务就绪..."
    sleep 5

    # 检查 PostgreSQL
    for i in {1..30}; do
        if docker-compose exec -T postgres pg_isready -U enterprise_ai -d enterprise_ai &> /dev/null; then
            log_success "PostgreSQL 已就绪"
            break
        fi
        if [ $i -eq 30 ]; then
            log_error "PostgreSQL 启动超时"
            exit 1
        fi
        sleep 1
    done

    # 检查 Redis
    for i in {1..15}; do
        if docker-compose exec -T redis redis-cli ping &> /dev/null; then
            log_success "Redis 已就绪"
            break
        fi
        if [ $i -eq 15 ]; then
            log_error "Redis 启动超时"
            exit 1
        fi
        sleep 1
    done

    echo ""

    # 5. 构建共享包
    log_info "构建共享包..."
    pnpm build --filter=@enterprise-ai-app/shared-types
    pnpm build --filter=@enterprise-ai-app/config
    pnpm build --filter=@enterprise-ai-app/ui-components
    log_success "共享包构建完成"

    echo ""

    # 6. 显示后续步骤
    echo "============================================"
    log_success "开发环境初始化完成！"
    echo "============================================"
    echo ""
    echo "后续步骤:"
    echo "  1. 编辑 .env 文件，配置 OPENAI_API_KEY 等密钥"
    echo "  2. 启动开发服务器:"
    echo "     ${GREEN}pnpm dev${NC}                    # 启动所有服务"
    echo "     ${GREEN}pnpm dev --filter=web${NC}         # 仅启动前端 (端口 3000)"
    echo "     ${GREEN}pnpm dev --filter=api-gateway${NC} # 仅启动 API 网关 (端口 8000)"
    echo ""
    echo "  3. 访问应用:"
    echo "     ${BLUE}Web 前端:${NC}      http://localhost:3000"
    echo "     ${BLUE}Admin 后台:${NC}    http://localhost:3001"
    echo "     ${BLUE}API 文档:${NC}      http://localhost:8000/docs"
    echo "     ${BLUE}MinIO 控制台:${NC}  http://localhost:9001 (minioadmin/minioadmin123)"
    echo ""
    echo "  4. 启用监控 (可选):"
    echo "     ${GREEN}docker-compose --profile monitoring up -d${NC}"
    echo "     ${BLUE}Grafana:${NC} http://localhost:3002 (admin/admin123)"
    echo "     ${BLUE}Jaeger:${NC}  http://localhost:16686"
    echo ""
    echo "  5. 常用命令:"
    echo "     ${GREEN}pnpm lint${NC}           # 代码检查"
    echo "     ${GREEN}pnpm typecheck${NC}      # 类型检查"
    echo "     ${GREEN}pnpm test${NC}           # 运行测试"
    echo "     ${GREEN}pnpm docker:logs${NC}    # 查看基础设施日志"
    echo "     ${GREEN}pnpm docker:down${NC}    # 停止基础设施"
    echo ""
}

main "$@"