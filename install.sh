#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Lark Skills — Installer
# 支持 Claude Code (~/.claude/commands/) 和 Codex (~/.agents/skills/)
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

MANAGED_MARKER='<!-- managed-by: RoboZephyr/lark-skills -->'

# ---------- 可安装的 Skills ----------
ALL_SKILLS=(lark-doc-personal lark-doc-deliver doc-summary weekly-report progress-report meeting-action-sync)

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

    # 0. Project-level Claude Code commands for using this repo directly.
    if [ $INSTALL_CLAUDE -eq 1 ]; then
        local project_commands="$REPO_DIR/.claude/commands"
        local project_command="$project_commands/$skill.md"
        if ! mkdir -p "$project_commands"; then
            error "Could not create project commands directory: $project_commands"
            return 1
        fi
        if [ -f "$project_command" ]; then
            ok "Project:     .claude/commands/$skill.md (kept existing)"
        else
            if ! cat > "$project_command" << EOF
Read and follow the instructions in \`skills/$skill/SKILL.md\`.

\$ARGUMENTS
EOF
            then
                error "Could not write project command: $project_command"
                return 1
            fi
            ok "Project:     .claude/commands/$skill.md"
        fi
    fi

    # 1. Claude Code: 写入 ~/.claude/commands/
    if [ $INSTALL_CLAUDE -eq 1 ]; then
        local claude_commands="$HOME/.claude/commands"
        local claude_command="$claude_commands/$skill.md"
        if [ -L "$claude_command" ]; then
            error "Claude Code command path is a symlink not managed by this installer: $claude_command"
            return 1
        elif [ -f "$claude_command" ] && \
           ! grep -Fq "$MANAGED_MARKER" "$claude_command" && \
           ! { grep -Fq 'First, change the working directory to' "$claude_command" && \
               grep -Fq "skills/$skill/SKILL.md" "$claude_command"; }; then
            error "Claude Code command already exists and is not managed by this installer: $claude_command"
            return 1
        fi
        if ! mkdir -p "$claude_commands"; then
            error "Could not create Claude Code commands directory: $claude_commands"
            return 1
        fi
        if ! {
            printf '%s\n\n' "$MANAGED_MARKER"
            printf 'First, change the working directory to `%s`, then read and follow the instructions in `skills/%s/SKILL.md`.\n\n' \
                "$REPO_DIR" "$skill"
            printf '%s\n' '$ARGUMENTS'
        } > "$claude_command"; then
            error "Could not write Claude Code command: $claude_command"
            return 1
        fi
        ok "Claude Code: ~/.claude/commands/$skill.md"
    fi

    # 2. Codex: 写入全局 Skill launcher。
    #
    # Codex 从 ~/.agents/skills/<name>/SKILL.md 发现用户级 Skills。这里不直接
    # 链接源目录，因为源 SKILL.md 中的命令以本仓库根目录为相对路径；launcher
    # 会保留用户调用时的项目上下文，同时明确这些运行时路径应从 REPO_DIR 解析。
    if [ $INSTALL_CODEX -eq 1 ]; then
        local codex_skills="$HOME/.agents/skills"
        local codex_skill_dir="$codex_skills/$skill"
        local codex_skill_file="$codex_skill_dir/SKILL.md"
        local description_line=""

        description_line=$(sed -n '/^---$/,/^---$/ { /^description:/p; }' "$skill_dir/SKILL.md" | head -1)
        if [ -z "$description_line" ]; then
            error "Missing description in $skill_dir/SKILL.md"
            return 1
        fi

        if [ -L "$codex_skill_dir" ]; then
            error "Codex Skill path is a symlink not managed by this installer: $codex_skill_dir"
            return 1
        elif [ -e "$codex_skill_dir" ]; then
            if [ -f "$codex_skill_file" ] && grep -Fq "$MANAGED_MARKER" "$codex_skill_file"; then
                local unexpected_entry=""
                unexpected_entry=$(find "$codex_skill_dir" -mindepth 1 -maxdepth 1 \
                    ! -name 'SKILL.md' ! -name 'agents' -print -quit)
                if [ -n "$unexpected_entry" ] || \
                   { { [ -e "$codex_skill_dir/agents" ] || [ -L "$codex_skill_dir/agents" ]; } && \
                     [ ! -L "$codex_skill_dir/agents" ]; }; then
                    error "Managed Codex Skill contains unexpected files: $codex_skill_dir"
                    return 1
                fi
                if [ -L "$codex_skill_dir/agents" ]; then
                    rm "$codex_skill_dir/agents" || return 1
                fi
                rm "$codex_skill_file" || return 1
                if ! rmdir "$codex_skill_dir" 2>/dev/null; then
                    error "Managed Codex Skill contains unexpected files: $codex_skill_dir"
                    return 1
                fi
            else
                error "Codex Skill already exists and is not managed by this installer: $codex_skill_dir"
                return 1
            fi
        fi

        if ! mkdir -p "$codex_skill_dir"; then
            error "Could not create Codex Skill directory: $codex_skill_dir"
            return 1
        fi
        if ! {
            printf '%s\n' '---'
            printf 'name: %s\n' "$skill"
            printf '%s\n' "$description_line"
            printf '%s\n\n' '---'
            printf '%s\n\n' "$MANAGED_MARKER"
            printf '%s\n\n' '# Lark Skills launcher'
            printf 'Source skill: `%s`\n\n' "$skill_dir/SKILL.md"
            printf 'Runtime root: `%s`\n\n' "$REPO_DIR"
            printf '%s\n' '1. Preserve the working directory where the user invoked Codex as the task project context.'
            printf '%s\n' '2. Read the source `SKILL.md` above completely before taking task actions, then follow it.'
            printf '%s\n' '3. Resolve paths beginning with `skills/` and run Lark Skills helper commands from the runtime root above.'
            printf '%s\n' '4. Keep repository-specific inspection and edits scoped to the task project unless the user names a different project.'
        } > "$codex_skill_file"; then
            error "Could not write Codex Skill launcher: $codex_skill_file"
            return 1
        fi

        if [ -d "$skill_dir/agents" ]; then
            if ! ln -s "$skill_dir/agents" "$codex_skill_dir/agents"; then
                error "Could not link Codex Skill metadata: $skill_dir/agents"
                return 1
            fi
        fi

        # Clean up the legacy entry created by older versions of this installer.
        local legacy_instruction="$HOME/.codex/instructions/$skill.md"
        if [ -f "$legacy_instruction" ]; then
            if grep -Fq "When the user asks to run \"$skill\"" "$legacy_instruction" && \
               grep -Fq "skills/$skill/SKILL.md" "$legacy_instruction"; then
                if rm "$legacy_instruction"; then
                    ok "Migrated:    ~/.codex/instructions/$skill.md"
                else
                    warn "Could not remove legacy file: $legacy_instruction"
                fi
            else
                warn "Kept unrelated legacy file: $legacy_instruction"
            fi
        fi

        ok "Codex:       ~/.agents/skills/$skill/SKILL.md"
    fi

    # 3. 初始化配置文件
    if [ -f "$skill_dir/config.example.yaml" ] && [ ! -f "$skill_dir/config.yaml" ]; then
        if ! cp "$skill_dir/config.example.yaml" "$skill_dir/config.yaml"; then
            error "Could not create $skill_dir/config.yaml"
            return 1
        fi
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
    local failed=0
    for skill in "${skills_to_install[@]}"; do
        info "--- $skill ---"
        if install_skill "$skill"; then
            installed=$((installed + 1))
        else
            failed=$((failed + 1))
        fi
        echo ""
    done

    if [ $failed -gt 0 ]; then
        error "Installed $installed skill(s), but failed to install $failed skill(s)."
        exit 1
    fi

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
        step=$((step + 1))
    fi
    if [ $INSTALL_CODEX -eq 1 ]; then
        echo "  $step. Codex — open any project and mention a Skill:"
        for skill in "${skills_to_install[@]}"; do
            echo "     \$$skill"
        done
        echo "     If a new Skill does not appear, restart Codex."
    fi
    echo ""

}

main "$@"
