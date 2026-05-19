#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Office Assistant — Uninstaller
# 移除 Claude Code 和 Codex 的 skill 入口
# ============================================================

ALL_SKILLS=(lark-doc-deliver doc-summary)

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "[INFO]  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }

echo ""
echo -e "${BOLD}Office Assistant Uninstaller${NC}"
echo ""

removed=0

# Claude Code
for skill in "${ALL_SKILLS[@]}"; do
    target="$HOME/.claude/commands/$skill.md"
    if [ -f "$target" ]; then
        rm "$target"
        ok "Removed: $target"
        ((removed++))
    fi
done

# Codex
for skill in "${ALL_SKILLS[@]}"; do
    target="$HOME/.codex/instructions/$skill.md"
    if [ -f "$target" ]; then
        rm "$target"
        ok "Removed: $target"
        ((removed++))
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
