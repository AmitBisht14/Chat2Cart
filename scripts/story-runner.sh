#!/usr/bin/env bash
# Implements open `ready` stories one by one, lowest P-number first, each in a fresh Claude Code session.
# Usage: scripts/story-runner.sh [--dry-run]    (BUDGET_USD caps spend per story, default 5)
set -euo pipefail

BUDGET_USD="${BUDGET_USD:-5}"
ALLOWLIST_FILE="agent/src/chat2cart/swiggy/allowlist.py"
INSTRUCTIONS_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/story-runner/instructions.md"
DRY_RUN=0

main() {
  parse_args "$@"
  while true; do
    local issue
    issue="$(next_issue)"
    if [[ -z "$issue" ]]; then
      echo "No open 'ready' stories left."
      exit 0
    fi
    run_story "$issue"
    if ((DRY_RUN)); then
      echo "[dry-run] stopping after the first story."
      exit 0
    fi
  done
}

parse_args() {
  case "${1:-}" in
    "") ;;
    --dry-run) DRY_RUN=1 ;;
    *) echo "Usage: $0 [--dry-run]" >&2; exit 64 ;;
  esac
}

# Runs a mutating command, or only prints it in dry-run mode.
mutate() {
  if ((DRY_RUN)); then
    printf '[dry-run]' >&2
    printf ' %q' "$@" >&2
    printf '\n' >&2
    return 0
  fi
  "$@"
}

next_issue() {
  gh issue list --label ready --state open --limit 200 --json number,title,body,labels |
    jq -c '[.[] | select(.title | test("^P[0-9]+"))
            | . + {priority: (.title | capture("^P(?<n>[0-9]+)").n | tonumber)}]
           | sort_by(.priority) | .[0] // empty'
}

run_story() {
  local issue="$1" number title branch
  number="$(jq -r .number <<<"$issue")"
  title="$(jq -r .title <<<"$issue")"
  branch="story-${number}-$(slugify "$title")"
  echo "Next story: #${number} ${title}"
  echo "Branch: ${branch}"

  prepare_branch "$branch"
  run_claude "$issue"
  run_checks "$branch"
  open_and_merge_pr "$issue" "$number" "$branch"
}

slugify() {
  local words
  words="$(sed -E 's/^P[0-9]+ *[·-]? *//' <<<"$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-')"
  words="${words#-}"
  words="${words:0:40}"
  echo "${words%-}"
}

prepare_branch() {
  mutate git checkout main
  mutate git pull
  mutate git checkout -b "$1"
}

run_claude() {
  local issue="$1" prompt
  prompt="$(build_prompt "$issue")"
  # Never --continue or --resume: every story starts with a fresh context.
  local command=(claude -p --max-budget-usd "$BUDGET_USD" --allowedTools "Read,Edit,Write,Glob,Grep,Bash")
  if ((DRY_RUN)); then
    printf '[dry-run]'
    printf ' %q' "${command[@]}"
    echo " <<< instructions + issue text (${#prompt} chars)"
    return 0
  fi
  "${command[@]}" <<<"$prompt"
}

build_prompt() {
  jq -r '"# " + .title + "\n\n" + .body' <<<"$1" | cat "$INSTRUCTIONS_FILE" -
}

run_checks() {
  if ((DRY_RUN)); then
    echo "[dry-run] make check"
    return 0
  fi
  if ! make check; then
    echo "make check failed. Branch left for review: $1" >&2
    exit 1
  fi
}

open_and_merge_pr() {
  local issue="$1" number="$2" branch="$3" url
  mutate git push -u origin "$branch"
  url="$(mutate gh pr create --fill --body "Closes #${number}")"
  if needs_manual_review "$issue"; then
    echo "Review needed before merging: ${url:-<pull request>}"
    exit 2
  fi
  mutate gh pr merge --squash --delete-branch
  mutate git checkout main
}

needs_manual_review() {
  local changed
  if jq -e '.labels | map(.name) | index("needs-manual-check")' <<<"$1" >/dev/null; then
    return 0
  fi
  if ((DRY_RUN)); then
    return 1
  fi
  changed="$(git diff --name-only main...HEAD)"
  grep -qxF "$ALLOWLIST_FILE" <<<"$changed"
}

main "$@"
