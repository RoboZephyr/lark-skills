#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Lark Skills — Uninstaller
# 移除 Claude Code 和 Codex 的 skill 入口
# ============================================================

ALL_SKILLS=(lark-doc-personal lark-doc-deliver doc-summary weekly-report progress-report meeting-action-sync)

MANAGED_MARKER='<!-- managed-by: RoboZephyr/lark-skills -->'

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "[INFO]  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }

echo ""
echo -e "${BOLD}Lark Skills Uninstaller${NC}"
echo ""

removed=0

# Claude Code
for skill in "${ALL_SKILLS[@]}"; do
    target="$HOME/.claude/commands/$skill.md"
    if [ -L "$target" ]; then
        warn "Kept unmanaged Claude Code command symlink: $target"
    elif [ -f "$target" ]; then
        if grep -Fq "$MANAGED_MARKER" "$target" || \
           { grep -Fq 'First, change the working directory to' "$target" && \
             grep -Fq "skills/$skill/SKILL.md" "$target"; }; then
            rm "$target"
            ok "Removed: $target"
            removed=$((removed + 1))
        else
            warn "Kept unmanaged Claude Code command: $target"
        fi
    fi
done

# Codex: remove only launcher Skills created by this installer.
for skill in "${ALL_SKILLS[@]}"; do
    target="$HOME/.agents/skills/$skill"
    skill_file="$target/SKILL.md"
    if [ -L "$target" ]; then
        warn "Kept unmanaged Codex Skill symlink: $target"
    elif [ -e "$target" ]; then
        if [ -f "$skill_file" ] && grep -Fq "$MANAGED_MARKER" "$skill_file"; then
            if [ -L "$target/agents" ]; then
                rm "$target/agents"
            fi
            rm "$skill_file"
            if rmdir "$target" 2>/dev/null; then
                ok "Removed: $target"
                removed=$((removed + 1))
            else
                warn "Kept non-generated files in: $target"
            fi
        else
            warn "Kept unmanaged Codex Skill: $target"
        fi
    fi

    # Backward-compatible cleanup for entries produced by the old installer.
    legacy="$HOME/.codex/instructions/$skill.md"
    if [ -f "$legacy" ]; then
        if grep -Fq "When the user asks to run \"$skill\"" "$legacy" && \
           grep -Fq "skills/$skill/SKILL.md" "$legacy"; then
            rm "$legacy"
            ok "Removed legacy: $legacy"
            removed=$((removed + 1))
        else
            warn "Kept unrelated legacy file: $legacy"
        fi
    fi
done

echo ""
if [ $removed -gt 0 ]; then
    echo -e "${GREEN}Removed $removed file(s).${NC}"
else
    echo "Nothing to remove."
fi

echo ""
echo "Note: config.yaml files in this repo are preserved."
echo "      To fully clean up, delete this repo directory."
echo ""
