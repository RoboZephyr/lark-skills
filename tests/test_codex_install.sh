#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS=(lark-doc-personal lark-doc-deliver doc-summary weekly-report progress-report meeting-action-sync)
MANAGED_MARKER='<!-- managed-by: RoboZephyr/lark-skills -->'

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

assert_exists() {
    [ -e "$1" ] || [ -L "$1" ] || fail "expected path to exist: $1"
}

assert_not_exists() {
    if [ -e "$1" ] || [ -L "$1" ]; then
        fail "expected path to be absent: $1"
    fi
}

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/lark-skills-test.XXXXXX")"
TMP_ROOT="$(cd "$TMP_ROOT" && pwd -P)"
trap 'rm -rf "$TMP_ROOT"' EXIT

FIXTURE="$TMP_ROOT/repo"
TEST_HOME="$TMP_ROOT/home"
COLLISION_HOME="$TMP_ROOT/collision-home"
CLAUDE_HOME="$TMP_ROOT/claude-home"
mkdir -p "$FIXTURE" "$TEST_HOME" "$COLLISION_HOME" "$CLAUDE_HOME"

# Copy tracked installer inputs into an isolated checkout. This intentionally
# excludes ignored config.yaml files and their credentials.
while IFS= read -r -d '' path; do
    mkdir -p "$FIXTURE/$(dirname "$path")"
    cp -p "$REPO_DIR/$path" "$FIXTURE/$path"
done < <(git -C "$REPO_DIR" ls-files -z -- install.sh uninstall.sh skills)

run_install() {
    env -i \
        HOME="$TEST_HOME" \
        PATH="/usr/bin:/bin" \
        /bin/bash "$FIXTURE/install.sh" --codex "$@"
}

run_uninstall() {
    env -i \
        HOME="$TEST_HOME" \
        PATH="/usr/bin:/bin" \
        /bin/bash "$FIXTURE/uninstall.sh"
}

# Seed the exact legacy entries emitted by the old installer and verify that a
# new install migrates them away.
mkdir -p "$TEST_HOME/.codex/instructions"
for skill in "${SKILLS[@]}"; do
    printf 'When the user asks to run "%s", change the working directory to `%s`, then read and follow the instructions in `skills/%s/SKILL.md`.\n' \
        "$skill" "$FIXTURE" "$skill" > "$TEST_HOME/.codex/instructions/$skill.md"
done

install_output="$(run_install)"
printf '%s\n' "$install_output" | grep -Fq 'Installed 6 skill(s) for Codex' || \
    fail "full Codex install did not report six installed skills"

for skill in "${SKILLS[@]}"; do
    installed_dir="$TEST_HOME/.agents/skills/$skill"
    installed_skill="$installed_dir/SKILL.md"
    source_skill="$FIXTURE/skills/$skill/SKILL.md"

    assert_exists "$installed_skill"
    grep -Fxq -- '---' "$installed_skill" || fail "missing YAML frontmatter: $skill"
    grep -Fxq "name: $skill" "$installed_skill" || fail "wrong installed skill name: $skill"
    grep -Eq '^description: .+' "$installed_skill" || fail "missing description: $skill"
    grep -Fq "$MANAGED_MARKER" "$installed_skill" || fail "missing managed marker: $skill"
    grep -Fq "Source skill: \`$source_skill\`" "$installed_skill" || fail "wrong source route: $skill"
    grep -Fq "Runtime root: \`$FIXTURE\`" "$installed_skill" || fail "wrong runtime root: $skill"
    assert_not_exists "$TEST_HOME/.codex/instructions/$skill.md"

    if [ -d "$FIXTURE/skills/$skill/agents" ]; then
        [ -L "$installed_dir/agents" ] || fail "agents metadata is not linked: $skill"
        [ "$(readlink "$installed_dir/agents")" = "$FIXTURE/skills/$skill/agents" ] || \
            fail "agents metadata points to the wrong source: $skill"
    fi
done

installed_count="$(find "$TEST_HOME/.agents/skills" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
[ "$installed_count" = "6" ] || fail "expected six installed skill directories, got $installed_count"

# Reinstalling should update the generated launchers without creating duplicates.
run_install >/dev/null
installed_count="$(find "$TEST_HOME/.agents/skills" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
[ "$installed_count" = "6" ] || fail "reinstall created duplicate skill directories"

# If a user adds anything to a generated directory, a reinstall must fail
# before removing either the launcher or the added file.
printf '%s\n' 'keep-me' > "$TEST_HOME/.agents/skills/progress-report/user-note.txt"
if run_install progress-report >/dev/null 2>&1; then
    fail "reinstall accepted unexpected files in a managed Skill"
fi
assert_exists "$TEST_HOME/.agents/skills/progress-report/SKILL.md"
grep -Fxq 'keep-me' "$TEST_HOME/.agents/skills/progress-report/user-note.txt" || \
    fail "reinstall removed a user file from a managed Skill"
rm "$TEST_HOME/.agents/skills/progress-report/user-note.txt"
run_install progress-report >/dev/null

# An unrelated user Skill with the same name must never be overwritten.
mkdir -p "$COLLISION_HOME/.agents/skills/progress-report"
printf '%s\n' 'user-owned' > "$COLLISION_HOME/.agents/skills/progress-report/SKILL.md"
if env -i HOME="$COLLISION_HOME" PATH="/usr/bin:/bin" \
    /bin/bash "$FIXTURE/install.sh" --codex progress-report >/dev/null 2>&1; then
    fail "installer accepted an unmanaged skill collision"
fi
grep -Fxq 'user-owned' "$COLLISION_HOME/.agents/skills/progress-report/SKILL.md" || \
    fail "installer modified an unmanaged skill collision"

# The shared uninstaller must not broaden the Codex fix into overwriting or
# deleting unrelated Claude Code commands. It should still migrate commands
# emitted by the previous installer format.
mkdir -p "$CLAUDE_HOME/.claude/commands"
printf '%s\n' 'user-owned' > "$CLAUDE_HOME/.claude/commands/progress-report.md"
if env -i HOME="$CLAUDE_HOME" PATH="/usr/bin:/bin" \
    /bin/bash "$FIXTURE/install.sh" --claude progress-report >/dev/null 2>&1; then
    fail "installer accepted an unmanaged Claude Code command collision"
fi
grep -Fxq 'user-owned' "$CLAUDE_HOME/.claude/commands/progress-report.md" || \
    fail "installer modified an unmanaged Claude Code command"

printf 'First, change the working directory to `%s`, then read and follow the instructions in `skills/progress-report/SKILL.md`.\n\n$ARGUMENTS\n' \
    "$FIXTURE" > "$CLAUDE_HOME/.claude/commands/progress-report.md"
env -i HOME="$CLAUDE_HOME" PATH="/usr/bin:/bin" \
    /bin/bash "$FIXTURE/install.sh" --claude progress-report >/dev/null
grep -Fq "$MANAGED_MARKER" "$CLAUDE_HOME/.claude/commands/progress-report.md" || \
    fail "installer did not migrate a legacy Claude Code command"

printf '%s\n' 'user-owned' > "$CLAUDE_HOME/.claude/commands/weekly-report.md"
env -i HOME="$CLAUDE_HOME" PATH="/usr/bin:/bin" /bin/bash "$FIXTURE/uninstall.sh" >/dev/null
assert_not_exists "$CLAUDE_HOME/.claude/commands/progress-report.md"
grep -Fxq 'user-owned' "$CLAUDE_HOME/.claude/commands/weekly-report.md" || \
    fail "uninstaller removed an unmanaged Claude Code command"

# Uninstall removes generated launchers and legacy entries, but preserves an
# unrelated Skill and every source Skill in the checkout.
mkdir -p "$TEST_HOME/.agents/skills/unrelated"
printf '%s\n' 'sentinel' > "$TEST_HOME/.agents/skills/unrelated/SKILL.md"
mkdir -p "$TEST_HOME/.codex/instructions"
for skill in "${SKILLS[@]}"; do
    printf 'When the user asks to run "%s", change the working directory to `%s`, then read and follow the instructions in `skills/%s/SKILL.md`.\n' \
        "$skill" "$FIXTURE" "$skill" > "$TEST_HOME/.codex/instructions/$skill.md"
done

run_uninstall >/dev/null
for skill in "${SKILLS[@]}"; do
    assert_not_exists "$TEST_HOME/.agents/skills/$skill"
    assert_not_exists "$TEST_HOME/.codex/instructions/$skill.md"
    assert_exists "$FIXTURE/skills/$skill/SKILL.md"
done
grep -Fxq 'sentinel' "$TEST_HOME/.agents/skills/unrelated/SKILL.md" || \
    fail "uninstaller modified an unrelated Skill"

second_uninstall_output="$(run_uninstall)"
printf '%s\n' "$second_uninstall_output" | grep -Fq 'Nothing to remove.' || \
    fail "second uninstall was not idempotent"

echo "PASS: Codex install and uninstall are isolated, discoverable, safe, and idempotent."
