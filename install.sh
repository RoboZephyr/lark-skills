#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Lark Skills — Installer
# 支持 Claude Code (~/.claude/commands/) 和 Codex (~/.codex/instructions/)
# ============================================================

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

# ---------- 颜色 ----------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ---------- 可安装的 Skills ----------
ALL_SKILLS=(lark-doc-personal lark-doc-deliver doc-summary weekly-report)

usage() {
    echo -e "${BOLD}Lark Skills Installer${NC}"
    echo ""
    echo "Usage: $0 [options] [skill ...]"
    echo ""
    echo "Skills:  ${ALL_SKILLS[*]}"
    echo ""
    echo "Options:"
    echo "  --claude      Install for Claude Code only"
    echo "  --codex       Install for Codex only"
    echo "  --all         Install all skills (default if no skill specified)"
    echo "  --list        List available skills"
    echo "  --check       Check dependencies only"
    echo "  -h, --help    Show this help"
    echo ""
    echo "By default, installs for all detected agents (Claude Code and/or Codex)."
    echo ""
    echo "Examples:"
    echo "  $0                        # Install all skills for detected agents"
    echo "  $0 --codex                # Install for Codex only"
    echo "  $0 lark-doc-deliver       # Install one skill"
    echo "  $0 lark-doc-deliver doc-summary  # Install multiple skills"
}

# ---------- Agent 检测 ----------
HAS_CLAUDE=0
HAS_CODEX=0

detect_agents() {
    if command -v claude &>/dev/null; then
        HAS_CLAUDE=1
        ok "claude found: $(claude --version 2>/dev/null || echo 'installed')"
    else
        info "claude not found"
    fi

    if command -v codex &>/dev/null; then
        HAS_CODEX=1
        ok "codex found"
    else
        info "codex not found"
    fi

    if [ $HAS_CLAUDE -eq 0 ] && [ $HAS_CODEX -eq 0 ]; then
        warn "No agent found (claude or codex). Install at least one:"
        echo "  Claude Code: https://docs.anthropic.com/en/docs/claude-code"
        echo "  Codex:       npm install -g @openai/codex"
    fi
}

# ---------- 依赖检查 ----------
check_deps() {
    local has_error=0

    info "Checking agents..."
    detect_agents
    echo ""

    info "Checking dependencies..."

    # lark-cli
    if command -v lark-cli &>/dev/null; then
        ok "lark-cli found"
        if lark-cli auth status &>/dev/null 2>&1; then
            ok "lark-cli auth configured"
        else
            warn "lark-cli installed but not configured"
            echo "  Run: echo \"<secret>\" | lark-cli config init --app-id \"<id>\" --app-secret-stdin --brand feishu"
        fi
    else
        warn "lark-cli not found — required for Lark integration"
        echo "  Install: npm install -g @larksuite/cli"
        echo "  Setup:   echo \"<secret>\" | lark-cli config init --app-id \"<id>\" --app-secret-stdin --brand feishu"
    fi

    return $has_error
}

# ---------- 安装单个 Skill ----------
install_skill() {
    local skill="$1"
    local skill_dir="$REPO_DIR/skills/$skill"

    # 检查 skill 是否存在
    if [ ! -f "$skill_dir/SKILL.md" ]; then
        error "Skill not found: $skill_dir/SKILL.md"
        return 1
    fi

    # 1. Claude Code: 写入 ~/.claude/commands/
    if [ $INSTALL_CLAUDE -eq 1 ]; then
        local claude_commands="$HOME/.claude/commands"
        mkdir -p "$claude_commands"
        cat > "$claude_commands/$skill.md" << EOF
First, change the working directory to \`$REPO_DIR\`, then read and follow the instructions in \`skills/$skill/SKILL.md\`.

\$ARGUMENTS
EOF
        ok "Claude Code: ~/.claude/commands/$skill.md"
    fi

    # 2. Codex: 写入 ~/.codex/instructions/
    if [ $INSTALL_CODEX -eq 1 ]; then
        local codex_instructions="$HOME/.codex/instructions"
        mkdir -p "$codex_instructions"
        cat > "$codex_instructions/$skill.md" << EOF
When the user asks to run "$skill", change the working directory to \`$REPO_DIR\`, then read and follow the instructions in \`skills/$skill/SKILL.md\`.
EOF
        ok "Codex:       ~/.codex/instructions/$skill.md"
    fi

    # 3. 初始化配置文件
    if [ -f "$skill_dir/config.example.yaml" ] && [ ! -f "$skill_dir/config.yaml" ]; then
        cp "$skill_dir/config.example.yaml" "$skill_dir/config.yaml"
        warn "Created $skill_dir/config.yaml — please edit with your real values"
    elif [ -f "$skill_dir/config.yaml" ]; then
        ok "Config already exists: $skill_dir/config.yaml"
    fi

    # 4. 场景目录（doc-summary 特有）
    if [ "$skill" = "doc-summary" ] && [ -d "$skill_dir/scenarios" ]; then
        if [ -f "$skill_dir/scenarios/example.yaml" ] && [ ! -f "$skill_dir/scenarios/tech-design.yaml" ]; then
            info "Scenario template available at: $skill_dir/scenarios/example.yaml"
            info "Copy and customize it for your use case"
        fi
    fi
}

# ---------- 主流程 ----------
INSTALL_CLAUDE=0
INSTALL_CODEX=0

main() {
    local skills_to_install=()
    local check_only=0
    local agent_explicit=0

    # 解析参数
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help)  usage; exit 0 ;;
            --list)
                echo "Available skills:"
                for s in "${ALL_SKILLS[@]}"; do
                    local desc=""
                    if [ -f "$REPO_DIR/skills/$s/SKILL.md" ]; then
                        desc=$(sed -n 's/^description: *//p' "$REPO_DIR/skills/$s/SKILL.md" | head -1)
                    fi
                    echo "  $s  —  $desc"
                done
                exit 0
                ;;
            --check)    check_only=1 ;;
            --claude)   INSTALL_CLAUDE=1; agent_explicit=1 ;;
            --codex)    INSTALL_CODEX=1; agent_explicit=1 ;;
            --all)      skills_to_install=("${ALL_SKILLS[@]}") ;;
            *)
                local valid=0
                for s in "${ALL_SKILLS[@]}"; do
                    if [ "$1" = "$s" ]; then valid=1; break; fi
                done
                if [ $valid -eq 1 ]; then
                    skills_to_install+=("$1")
                else
                    error "Unknown skill: $1"
                    echo "Available: ${ALL_SKILLS[*]}"
                    exit 1
                fi
                ;;
        esac
        shift
    done

    echo ""
    echo -e "${BOLD}Lark Skills Installer${NC}"
    echo -e "Repo: ${CYAN}$REPO_DIR${NC}"
    echo ""

    # 依赖检查
    check_deps || true
    echo ""

    if [ $check_only -eq 1 ]; then
        exit 0
    fi

    # 未指定 agent 时，自动检测安装
    if [ $agent_explicit -eq 0 ]; then
        INSTALL_CLAUDE=$HAS_CLAUDE
        INSTALL_CODEX=$HAS_CODEX
    fi

    if [ $INSTALL_CLAUDE -eq 0 ] && [ $INSTALL_CODEX -eq 0 ]; then
        error "No target agent. Use --claude or --codex, or install an agent first."
        exit 1
    fi

    local targets=""
    [ $INSTALL_CLAUDE -eq 1 ] && targets="Claude Code"
    [ $INSTALL_CODEX -eq 1 ] && targets="${targets:+$targets + }Codex"
    info "Target: $targets"
    echo ""

    # 默认安装全部 skills
    if [ ${#skills_to_install[@]} -eq 0 ]; then
        skills_to_install=("${ALL_SKILLS[@]}")
    fi

    # 安装
    info "Installing ${#skills_to_install[@]} skill(s)..."
    echo ""

    local installed=0
    for skill in "${skills_to_install[@]}"; do
        info "--- $skill ---"
        if install_skill "$skill"; then
            ((installed++))
        fi
        echo ""
    done

    # 完成
    echo -e "${BOLD}${GREEN}Done!${NC} Installed $installed skill(s) for $targets."
    echo ""
    echo -e "${BOLD}Next steps:${NC}"
    echo "  1. Edit config.yaml files with your real values (open_id, targets, etc.)"
    echo "     $(find "$REPO_DIR/skills" -name 'config.yaml' -maxdepth 2 2>/dev/null | head -5 | sed 's/^/     /')"
    echo ""
    echo "  2. Make sure lark-cli is configured:"
    echo "     lark-cli auth status"
    echo ""
    local step=3
    if [ $INSTALL_CLAUDE -eq 1 ]; then
        echo "  $step. Claude Code — open in any directory and use:"
        for skill in "${skills_to_install[@]}"; do
            echo "     /$skill"
        done
        ((step++))
    fi
    if [ $INSTALL_CODEX -eq 1 ]; then
        echo "  $step. Codex — cd to this repo and run:"
        echo "     codex"
        echo "     Then ask it to run a skill, e.g. \"run lark-doc-deliver\""
    fi
    echo ""
}

main "$@"
