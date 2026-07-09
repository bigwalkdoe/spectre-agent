#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-.}"
issues=0

echo "==> Scanning $TARGET for secrets..."

# Expanded patterns: API keys, tokens, passwords, JWTs, connection strings, private keys
patterns=(
  '(api[_-]?key|apikey|api_key|secret|token|password|passwd|pwd|jwt|bearer)\s*[:=]\s*["'\'']{0,1}[A-Za-z0-9_\-]{16,}'
  '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'
  'postgresql://[^:]+:[^@]+@'
  'redis://[^:]+:[^@]+@'
  'mongodb://[^:]+:[^@]+@'
  'aws_access_key_id|aws_secret_access_key'
  'ghp_[A-Za-z0-9_]{36,}'
  'gho_[A-Za-z0-9_]{36,}'
  'ghu_[A-Za-z0-9_]{36,}'
  'sk-[A-Za-z0-9_]{32,}'
)

exclude_dirs='.venv|node_modules|__pycache__|.git|dist|build|.next'

for pattern in "${patterns[@]}"; do
    matches=$(grep -rnI --include="*.py" --include="*.ts" --include="*.js" --include="*.yml" \
      --include="*.yaml" --include="*.json" --include="*.env" --include="*.toml" \
      -E "$pattern" "$TARGET" 2>/dev/null | grep -vE "$exclude_dirs" || true)
    if [ -n "$matches" ]; then
        echo "$matches"
        issues=1
    fi
done

# Check for .env files not in gitignore
if find "$TARGET" -maxdepth 2 -name '.env' -not -path '*/.venv/*' 2>/dev/null | grep -q .; then
    echo "WARNING: .env files found — ensure they are in .gitignore"
    issues=1
fi

# Check file permissions — warn on world-readable private keys or .env
while IFS= read -r -d '' f; do
    perms=$(stat -c "%a" "$f")
    if [ "${perms: -1}" -ge "4" ] 2>/dev/null; then
        echo "WARNING: World-readable secrets file: $f (perms $perms)"
        issues=1
    fi
done < <(find "$TARGET" -type f \( -name '*.pem' -o -name '*.key' -o -name '.env' -o -name '.env.*' \) -not -path '*/.venv/*' -not -path '*/node_modules/*' -print0 2>/dev/null || true)

if [ "$issues" -eq 0 ]; then
    echo "No security issues detected."
else
    echo "SECURITY ISSUES FOUND — review warnings above."
    exit 1
fi
