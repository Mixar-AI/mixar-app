#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Mixar AI
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/open_source/phase1_secret_audit.sh [--output-dir DIR]

Scans Git-visible files and Git history path names for likely secrets and
sensitive publication risks. Optional gitleaks/trufflehog runs are used only
when those tools are already installed.
USAGE
}

OUTPUT_DIR="docs/open-source/audit/secret-audit"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      OUTPUT_DIR="${2:?--output-dir requires a value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p "$OUTPUT_DIR"

HIGH_CONFIDENCE_SECRET_REGEX='(BEGIN[[:space:]]+(RSA|DSA|EC|OPENSSH|PRIVATE)[[:space:]]+PRIVATE[[:space:]]+KEY|AKIA[0-9A-Z]{16}|aws_access_key_id[[:space:]]*[:=]|aws_secret_access_key[[:space:]]*[:=]|secret_access_key[[:space:]]*[:=]|client_secret[[:space:]]*[:=]|refresh_token[[:space:]]*[:=]|access_token[[:space:]]*[:=]|api[_-]?key[[:space:]]*[:=]|password[[:space:]]*[:=]|passwd[[:space:]]*[:=]|private[_-]?key[[:space:]]*[:=]|cert_password[[:space:]]*[:=]|app_password[[:space:]]*[:=])'
PUBLICATION_REVIEW_REGEX='(CLAUDE_CODE_OAUTH_TOKEN|GH_APP_PRIVATE_KEY|VERSION_BOT_PRIVATE_KEY|BACKEND_PASSWORD|APPLE_ID|ANTHROPIC|OPENAI|STRIPE|SENTRY|POSTHOG|token|password|secret|credential|private key|signing)'
SENSITIVE_PATH_REGEX='(^|/)(\.env|\.env\..*|.*\.pem|.*\.key|.*\.p12|.*\.pfx|.*\.mobileprovision|.*\.kdbx|.*\.asc|.*\.gpg|.*secret.*|.*credential.*|.*cert.*|.*private.*|.*signing.*)$'

GIT_VISIBLE_NUL="$OUTPUT_DIR/git-visible-paths.nul"
TRACKED_NUL="$OUTPUT_DIR/git-visible-files.nul"
git ls-files -z --cached --others --exclude-standard > "$GIT_VISIBLE_NUL"
: > "$TRACKED_NUL"
while IFS= read -r -d '' path; do
  if [[ -f "$path" ]]; then
    printf '%s\0' "$path" >> "$TRACKED_NUL"
  fi
done < "$GIT_VISIBLE_NUL"
tr '\0' '\n' < "$TRACKED_NUL" > "$OUTPUT_DIR/tracked-files.txt"

if [[ -s "$TRACKED_NUL" ]]; then
  : > "$OUTPUT_DIR/tracked-secret-patterns.txt"
  while IFS= read -r -d '' path; do
    rg -n -I --color never -S -i -e "$HIGH_CONFIDENCE_SECRET_REGEX" "$path" \
      | sed "s|^|$path:|" \
      >> "$OUTPUT_DIR/tracked-secret-patterns.txt" || true
  done < "$TRACKED_NUL"
else
  : > "$OUTPUT_DIR/tracked-secret-patterns.txt"
fi

if [[ -s "$TRACKED_NUL" ]]; then
  : > "$OUTPUT_DIR/tracked-publication-review-keywords.txt"
  while IFS= read -r -d '' path; do
    rg -n -I --color never -S -i -e "$PUBLICATION_REVIEW_REGEX" "$path" \
      | sed "s|^|$path:|" \
      >> "$OUTPUT_DIR/tracked-publication-review-keywords.txt" || true
  done < "$TRACKED_NUL"
else
  : > "$OUTPUT_DIR/tracked-publication-review-keywords.txt"
fi

git log --all --name-only --pretty=format: \
  | sort -u \
  | rg -n -i --color never -e "$SENSITIVE_PATH_REGEX" \
  > "$OUTPUT_DIR/history-sensitive-paths.txt" || true

{
  echo "Optional tool availability"
  echo
  if command -v gitleaks >/dev/null 2>&1; then
    echo "gitleaks: available"
    gitleaks detect --source . --redact --report-format json \
      --report-path "$OUTPUT_DIR/gitleaks-report.json" \
      > "$OUTPUT_DIR/gitleaks-stdout.txt" 2> "$OUTPUT_DIR/gitleaks-stderr.txt" || true
  else
    echo "gitleaks: not installed"
  fi
  if command -v trufflehog >/dev/null 2>&1; then
    echo "trufflehog: available"
    trufflehog git "file://$(pwd)" --results=verified,unknown --json \
      > "$OUTPUT_DIR/trufflehog-report.jsonl" 2> "$OUTPUT_DIR/trufflehog-stderr.txt" || true
  else
    echo "trufflehog: not installed"
  fi
} > "$OUTPUT_DIR/optional-tools.txt"

{
  echo "Secret audit summary"
  echo
  echo "Git-visible files scanned: $(wc -l < "$OUTPUT_DIR/tracked-files.txt" | tr -d ' ')"
  echo "High-confidence git-visible secret-pattern matches: $(wc -l < "$OUTPUT_DIR/tracked-secret-patterns.txt" | tr -d ' ')"
  echo "Publication review keyword matches: $(wc -l < "$OUTPUT_DIR/tracked-publication-review-keywords.txt" | tr -d ' ')"
  echo "Sensitive historical path matches: $(wc -l < "$OUTPUT_DIR/history-sensitive-paths.txt" | tr -d ' ')"
  echo
  echo "Review required:"
  echo "- tracked-secret-patterns.txt"
  echo "- tracked-publication-review-keywords.txt"
  echo "- history-sensitive-paths.txt"
  echo "- optional-tools.txt"
  echo "- gitleaks/trufflehog reports if generated"
} > "$OUTPUT_DIR/summary.txt"

echo "Secret audit reports written to $OUTPUT_DIR"
