#!/usr/bin/env bash
#
# MultiMind 一键安装脚本
#
# 用法:
#   ./install.sh                  # 完整安装（含 Playwright 浏览器）
#   ./install.sh --no-browser     # 跳过 Playwright 浏览器安装
#   ./install.sh --venv           # 使用虚拟环境
#   ./install.sh --dev            # 安装开发依赖
#   ./install.sh --non-interactive # 非交互式（使用默认配置，适合 CI）
#   ./install.sh --uninstall      # 卸载 MultiMind
#
# 环境变量:
#   MULTIMIND_HOME    配置目录（默认: ~/.multimind）
#   MULTIMIND_VENV    虚拟环境路径（默认: .venv，仅 --venv 时生效）
#   MULTIMIND_PYTHON  指定 Python 解释器路径
#
# Termux 支持:
#   脚本自动检测 Termux 环境，跳过 Playwright 安装（不支持 Chromium），
#   并添加 --break-system-packages 参数适配 Termux 的 pip。
#   API 通道和 CLI 通道在 Termux 下可正常使用。
#
# 参考: Oh My Zsh / rustup 安装脚本最佳实践
#
set -euo pipefail

# ── 默认配置（环境变量覆盖）──────────────────────────────────────────
MULTIMIND_HOME="${MULTIMIND_HOME:-$HOME/.multimind}"
MULTIMIND_VENV="${MULTIMIND_VENV:-.venv}"
MULTIMIND_PYTHON="${MULTIMIND_PYTHON:-}"

# ── 颜色输出 ──────────────────────────────────────────────────────────
setup_color() {
    if [ -t 1 ]; then
        RED='\033[0;31m'
        GREEN='\033[0;32m'
        YELLOW='\033[1;33m'
        CYAN='\033[0;36m'
        BOLD='\033[1m'
        DIM='\033[2m'
        NC='\033[0m'
    else
        RED=''
        GREEN=''
        YELLOW=''
        CYAN=''
        BOLD=''
        DIM=''
        NC=''
    fi
}

info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── 工具函数 ──────────────────────────────────────────────────────────
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

is_tty() {
    [ -t 0 ]
}

# ── 参数解析 ──────────────────────────────────────────────────────────
INSTALL_BROWSER=true
USE_VENV=false
INSTALL_DEV=false
SKIP_INIT=false
NON_INTERACTIVE=false
UNINSTALL=false

while [ $# -gt 0 ]; do
    case "$1" in
        --no-browser)      INSTALL_BROWSER=false ;;
        --venv)            USE_VENV=true ;;
        --dev)             INSTALL_DEV=true ;;
        --no-init)         SKIP_INIT=true ;;
        --non-interactive) NON_INTERACTIVE=true; SKIP_INIT=true ;;
        --uninstall)       UNINSTALL=true ;;
        --help|-h)
            echo "MultiMind 一键安装脚本"
            echo ""
            echo "用法: ./install.sh [选项]"
            echo ""
            echo "选项:"
            echo "  --no-browser       跳过 Playwright 浏览器安装"
            echo "  --venv             使用虚拟环境 (路径由 \$MULTIMIND_VENV 控制)"
            echo "  --dev              安装开发依赖 (pytest, ruff, mypy 等)"
            echo "  --no-init          跳过 multimind init 配置向导"
            echo "  --non-interactive  非交互式模式（使用默认配置，跳过向导）"
            echo "  --uninstall        卸载 MultiMind"
            echo "  --help             显示此帮助"
            echo ""
            echo "环境变量:"
            echo "  MULTIMIND_HOME     配置目录（默认: ~/.multimind）"
            echo "  MULTIMIND_VENV     虚拟环境路径（默认: .venv）"
            echo "  MULTIMIND_PYTHON   指定 Python 解释器路径"
            exit 0
            ;;
        *)
            warn "未知参数: $1"
            ;;
    esac
    shift
done

setup_color

# ═══════════════════════════════════════════════════════════════════════
# 卸载流程
# ═══════════════════════════════════════════════════════════════════════

if [ "$UNINSTALL" = true ]; then
    echo ""
    echo -e "${BOLD}卸载 MultiMind...${NC}"
    echo ""

    # 卸载 pip 包
    if command_exists pip || command_exists pip3; then
        info "卸载 pip 包..."
        pip uninstall -y multimind 2>/dev/null || pip3 uninstall -y multimind 2>/dev/null || true
        success "pip 包已卸载"
    fi

    # 询问是否删除配置
    if [ -d "$MULTIMIND_HOME" ]; then
        if is_tty && [ "$NON_INTERACTIVE" = false ]; then
            echo -e "${YELLOW}找到配置目录: $MULTIMIND_HOME${NC}"
            printf "是否删除配置目录? [y/N] "
            read -r choice
            case "$choice" in
                y|Y|yes)
                    rm -rf "$MULTIMIND_HOME"
                    success "配置目录已删除: $MULTIMIND_HOME"
                    ;;
                *)
                    info "保留配置目录: $MULTIMIND_HOME"
                    ;;
            esac
        else
            info "非交互式模式，保留配置目录: $MULTIMIND_HOME"
        fi
    fi

    # 询问是否删除虚拟环境
    if [ "$USE_VENV" = true ] && [ -d "$MULTIMIND_VENV" ]; then
        if is_tty && [ "$NON_INTERACTIVE" = false ]; then
            printf "是否删除虚拟环境 %s? [y/N] " "$MULTIMIND_VENV"
            read -r choice
            case "$choice" in
                y|Y|yes)
                    rm -rf "$MULTIMIND_VENV"
                    success "虚拟环境已删除: $MULTIMIND_VENV"
                    ;;
                *)
                    info "保留虚拟环境: $MULTIMIND_VENV"
                    ;;
            esac
        fi
    fi

    echo ""
    success "MultiMind 卸载完成"
    exit 0
fi

# ═══════════════════════════════════════════════════════════════════════
# 安装流程
# ═══════════════════════════════════════════════════════════════════════

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   MultiMind 一键安装脚本                 ║${NC}"
echo -e "${BOLD}║   多 AI 协作 CLI Agent                    ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── 环境检测 ──────────────────────────────────────────────────────────

# 检测是否运行在 Termux 环境中
IS_TERMUX=false
if [ -n "${PREFIX:-}" ] && echo "$PREFIX" | grep -q "com.termux"; then
    IS_TERMUX=true
fi

if [ "$IS_TERMUX" = true ]; then
    info "检测到 Termux 环境"
    # Termux 无法安装 Playwright Chromium
    if [ "$INSTALL_BROWSER" = true ]; then
        warn "Termux 环境无法安装 Playwright Chromium，自动跳过"
        warn "浏览器通道功能不可用，API/CLI 通道正常"
        INSTALL_BROWSER=false
    fi
fi

# ── Step 1: 检测 Python ────────────────────────────────────────────────

info "Step 1/6: 检测 Python..."

if [ -n "$MULTIMIND_PYTHON" ]; then
    PYTHON="$MULTIMIND_PYTHON"
elif command_exists python3; then
    PYTHON=python3
elif command_exists python; then
    PYTHON=python
else
    error "未找到 Python，请安装 Python 3.10+ 后重试"
fi

if ! command_exists "$PYTHON"; then
    error "指定的 Python 解释器不存在: $PYTHON"
fi

PY_VERSION=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$($PYTHON -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$($PYTHON -c 'import sys; print(sys.version_info.minor)')

info "  Python: ${PY_VERSION} ($($PYTHON --version 2>&1))"

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    error "需要 Python 3.10+，当前为 ${PY_VERSION}"
fi
success "  Python 版本满足要求"

# ── Step 2: 检测 pip ──────────────────────────────────────────────────

info "Step 2/6: 检测 pip..."
if ! $PYTHON -m pip --version >/dev/null 2>&1; then
    if [ "$IS_TERMUX" = true ]; then
        error "未找到 pip，请运行: pkg install python-pip"
    fi
    error "未找到 pip，请安装 pip 后重试（https://pip.pypa.io/en/stable/installation/）"
fi
success "  pip 可用"

# ── Step 3: 虚拟环境 ──────────────────────────────────────────────────

info "Step 3/6: 配置 Python 环境..."

if [ "$USE_VENV" = true ]; then
    if [ -d "$MULTIMIND_VENV" ]; then
        info "  虚拟环境已存在: $MULTIMIND_VENV"
    else
        info "  创建虚拟环境: $MULTIMIND_VENV..."
        $PYTHON -m venv "$MULTIMIND_VENV"
    fi

    # 激活虚拟环境
    if [ -f "$MULTIMIND_VENV/bin/activate" ]; then
        # shellcheck disable=SC1091
        source "$MULTIMIND_VENV/bin/activate"
    elif [ -f "$MULTIMIND_VENV/Scripts/activate" ]; then
        # shellcheck disable=SC1091
        source "$MULTIMIND_VENV/Scripts/activate"
    else
        error "虚拟环境激活失败: $MULTIMIND_VENV"
    fi
    PYTHON=python
    success "  虚拟环境已激活: $(which python)"
else
    success "  使用系统 Python"
fi

# ── Step 4: 安装依赖 ──────────────────────────────────────────────────

info "Step 4/6: 安装依赖..."

# 确定安装方式（避免破坏系统包管理器的 pip）
PIP_INSTALL_ARGS="-e"
if [ "$IS_TERMUX" = true ]; then
    # Termux 需要此参数
    PIP_INSTALL_ARGS="$PIP_INSTALL_ARGS --break-system-packages"
fi

if [ "$USE_VENV" = true ]; then
    # 虚拟环境中可以安全升级 pip
    info "  升级 pip（虚拟环境）..."
    $PYTHON -m pip install --upgrade pip --quiet 2>/dev/null || warn "  pip 升级跳过（不影响安装）"
fi

if [ "$INSTALL_DEV" = true ]; then
    info "  安装核心依赖 + 开发依赖..."
    $PYTHON -m pip install $PIP_INSTALL_ARGS ".[browser,dev]" --quiet
    success "  已安装: core + browser + dev"
else
    info "  安装核心依赖..."
    $PYTHON -m pip install $PIP_INSTALL_ARGS "." --quiet
    success "  已安装: core (API/CLI 通道可用)"
    if [ "$INSTALL_BROWSER" = true ]; then
        info "  安装浏览器依赖..."
        $PYTHON -m pip install $PIP_INSTALL_ARGS ".[browser]" --quiet 2>/dev/null || \
            warn "  浏览器依赖安装失败，可稍后运行: pip install playwright"
    fi
fi

# ── Step 5: Playwright 浏览器 ─────────────────────────────────────────

if [ "$INSTALL_BROWSER" = true ]; then
    info "Step 5/6: 安装 Playwright Chromium..."
    $PYTHON -m playwright install chromium
    success "  Playwright Chromium 已安装"
else
    warn "Step 5/6: 跳过 Playwright 浏览器安装（--no-browser）"
    echo -e "  ${DIM}稍后可手动运行: python -m playwright install chromium${NC}"
fi

# ── Step 6: 验证安装 ──────────────────────────────────────────────────

info "Step 6/6: 验证安装..."

if $PYTHON -c "import multimind; print(f'  MultiMind v{multimind.__version__}')" 2>/dev/null; then
    success "  MultiMind 导入成功"
elif $PYTHON -c "from multimind.cli.main import app; print('  CLI 可用')" 2>/dev/null; then
    success "  MultiMind CLI 可用"
else
    error "  MultiMind 安装验证失败"
fi

# ── 初始化配置 ────────────────────────────────────────────────────────

if [ "$SKIP_INIT" = false ]; then
    echo ""
    info "启动配置向导..."

    # 检测是否为 TTY（非 TTY 时使用非交互式模式）
    if ! is_tty; then
        warn "非交互式终端，使用默认配置"
        NON_INTERACTIVE=true
    fi

    if [ "$NON_INTERACTIVE" = true ]; then
        # 非交互式：使用默认配置
        if $PYTHON -m multimind init --non-interactive --force 2>/dev/null; then
            success "配置完成（非交互式）"
        elif multimind init --non-interactive --force 2>/dev/null; then
            success "配置完成（非交互式）"
        else
            warn "配置向导未完成，稍后可运行: multimind init --non-interactive"
        fi
    else
        echo -e "${CYAN}提示: 可选择快速开始（2 个问题）或专家模式（逐项配置）${NC}"
        echo ""

        if $PYTHON -m multimind init 2>/dev/null; then
            success "配置完成"
        elif multimind init 2>/dev/null; then
            success "配置完成"
        else
            warn "配置向导未完成，稍后可运行: multimind init"
        fi
    fi
fi

# ── 完成 ──────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║   MultiMind 安装完成！                    ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}${BOLD}下一步配置（重要）:${NC}"
echo -e "  ${DIM}API 通道需要密钥才能使用，以下任选:${NC}"
echo -e "  ${CYAN}export GROQ_API_KEY=your_key${NC}       # Groq 免费 API (https://console.groq.com)"
echo -e "  ${DIM}CLI 通道和公共端点通道无需密钥，可直接使用${NC}"
echo ""
echo -e "${BOLD}快速开始:${NC}"
echo -e "  ${CYAN}multimind${NC}                    # 直接进入交互式群聊"
echo -e "  ${CYAN}multimind init${NC}               # 重新配置（简单/专家模式）"
echo -e "  ${CYAN}multimind providers${NC}          # 查看可用 Provider"
echo ""

if [ "$INSTALL_BROWSER" = false ]; then
    echo -e "${YELLOW}注意: 浏览器通道未安装（无 Playwright Chromium）${NC}"
    echo -e "  API 通道和 CLI 通道可正常使用"
    if [ "$IS_TERMUX" = true ]; then
        echo -e "  ${DIM}Termux 环境不支持 Playwright，浏览器通道不可用${NC}"
    else
        echo -e "  ${DIM}如需浏览器通道: python -m playwright install chromium${NC}"
    fi
    echo ""
fi

echo -e "其他:"
echo -e "  ${DIM}./install.sh --uninstall${NC}     # 卸载"
echo -e "  ${DIM}./install.sh --help${NC}          # 查看所有选项"
echo ""

if [ "$USE_VENV" = true ]; then
    echo -e "${YELLOW}提示: 使用前请激活虚拟环境:${NC}"
    echo -e "  ${CYAN}source ${MULTIMIND_VENV}/bin/activate${NC}"
    echo ""
fi
