#!/usr/bin/env bash
# validate_templates.sh — Hugo template validator for uutistenlukija.fi
#
# Checks for known Hugo 0.147-incompatible patterns and common template bugs.
# Exits 1 on any violation (blocking deploy). Exits 0 if all clean.
#
# Usage:
#   bash scripts/validate_templates.sh
#   bash scripts/validate_templates.sh --no-discord   # skip Discord alert
#
# Environment:
#   DISCORD_PIPELINE_WEBHOOK — if set, posts alert on failure
#
# Patterns checked:
#   1. {{ continue }} keyword — removed from Hugo range loops post-0.104
#   2. Standalone time() function — deprecated since Hugo 0.117
#   3. Standalone float() function — deprecated since Hugo 0.117
#   4. Standalone add/sub/mul/div outside math namespace — deprecated
#   5. Unbalanced {{ if/range/with/end }} blocks per file
#   6. Raw JS outside <script> tags (// comments, function calls in <head>)
#   7. Template files with 0-byte content

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DISCORD_WEBHOOK="${DISCORD_PIPELINE_WEBHOOK:-}"
NO_DISCORD="${1:-}"

ERRORS=()
WARNINGS=()

# ── Helpers ───────────────────────────────────────────────────────────────────

fail() { ERRORS+=("$1"); }
warn() { WARNINGS+=("$1"); }

# Find all Hugo template files
find_templates() {
  find "$REPO_ROOT/layouts" "$REPO_ROOT/themes/uutistenlukija/layouts" \
    -name "*.html" -type f 2>/dev/null | sort
}

# ── Check 1: {{ continue }} keyword ──────────────────────────────────────────
echo "[validate] Checking for {{ continue }} keyword..."
while IFS= read -r file; do
  if grep -qP '\{\{[-\s]*continue[-\s]*\}\}' "$file" 2>/dev/null; then
    rel="${file#$REPO_ROOT/}"
    line=$(grep -nP '\{\{[-\s]*continue[-\s]*\}\}' "$file" | head -1 | cut -d: -f1)
    fail "{{ continue }} found (invalid in Hugo 0.117+): $rel:$line"
  fi
done < <(find_templates)

# ── Check 2: Standalone time() function ──────────────────────────────────────
echo "[validate] Checking for deprecated time() function..."
while IFS= read -r file; do
  # Match (time ...) or {{... time "..." ...}} but NOT time.Format / time.AsTime / time.Now / time.Since
  if grep -qP '\(\s*time\s+[^A-Za-z]|\btime\s+"' "$file" 2>/dev/null; then
    if ! grep -qP '^\s*#' "$file" 2>/dev/null; then  # not a comment line (shouldn't be in HTML)
      rel="${file#$REPO_ROOT/}"
      line=$(grep -nP '\(\s*time\s+[^A-Za-z]|\btime\s+"' "$file" | head -1 | cut -d: -f1)
      fail "Deprecated time() function found (use time.AsTime): $rel:$line"
    fi
  fi
done < <(find_templates)

# ── Check 3: Standalone float() function ─────────────────────────────────────
echo "[validate] Checking for deprecated float() function..."
while IFS= read -r file; do
  if grep -qP '\bfloat\s*\(' "$file" 2>/dev/null; then
    rel="${file#$REPO_ROOT/}"
    line=$(grep -nP '\bfloat\s*\(' "$file" | head -1 | cut -d: -f1)
    fail "Deprecated float() function found: $rel:$line"
  fi
done < <(find_templates)

# ── Check 4: Deprecated math shortcuts (add/sub/mul/div as top-level funcs) ──
echo "[validate] Checking for deprecated math shortcuts..."
while IFS= read -r file; do
  # Pattern: | add N or | sub N or (add $x $y) etc — but NOT math.Add etc
  if grep -qP '\|\s+(add|sub|mul|div)\s+[\$\d]|\(\s*(add|sub|mul|div)\s+' "$file" 2>/dev/null; then
    rel="${file#$REPO_ROOT/}"
    line=$(grep -nP '\|\s+(add|sub|mul|div)\s+[\$\d]|\(\s*(add|sub|mul|div)\s+' "$file" | head -1 | cut -d: -f1)
    fail "Deprecated math shortcut (use math.Add/Sub/Mul/Div): $rel:$line"
  fi
done < <(find_templates)

# ── Check 5: Unbalanced {{ if/range/with/end }} blocks ───────────────────────
echo "[validate] Checking for unbalanced template blocks..."
while IFS= read -r file; do
  rel="${file#$REPO_ROOT/}"
  opens=$(grep -coP '\{\{[-\s]*(?:range|if|with|define|block)\b' "$file" 2>/dev/null || echo 0)
  ends=$(grep -coP '\{\{[-\s]*end\b' "$file" 2>/dev/null || echo 0)
  if [[ "$opens" != "$ends" ]]; then
    fail "Unbalanced blocks ($opens opens vs $ends ends): $rel"
  fi
done < <(find_templates)

# ── Check 6: Zero-byte template files ────────────────────────────────────────
echo "[validate] Checking for empty template files..."
while IFS= read -r file; do
  if [[ ! -s "$file" ]]; then
    rel="${file#$REPO_ROOT/}"
    warn "Empty template file: $rel"
  fi
done < <(find_templates)

# ── Check 7: Raw JS code outside <script> tags in layout files ───────────────
# Only check top-level layout files (baseof.html, list.html, single.html)
# A JS comment (//) or IIFE outside a <script>...</script> block = corruption
echo "[validate] Checking for raw JS outside <script> tags..."
for file in \
  "$REPO_ROOT/layouts/_default/baseof.html" \
  "$REPO_ROOT/themes/uutistenlukija/layouts/_default/baseof.html"; do
  [[ -f "$file" ]] || continue
  rel="${file#$REPO_ROOT/}"
  # Extract content BEFORE first <script> or AFTER </head> that isn't in a tag
  # Simple heuristic: find lines starting with '//' or 'function ' outside any <script> context
  # We use python for this since bash is poor at multi-line context
  if python3 - << 'PYEOF' "$file"
import sys, re
text = open(sys.argv[1]).read()
# Remove all <script>...</script> blocks
cleaned = re.sub(r'<script\b[^>]*>.*?</script>', '', text, flags=re.DOTALL|re.IGNORECASE)
# Remove Hugo template blocks
cleaned = re.sub(r'\{\{.*?\}\}', '', cleaned, flags=re.DOTALL)
# Check for raw JS patterns: lines starting with // or function
for i, line in enumerate(cleaned.split('\n'), 1):
    s = line.strip()
    if s.startswith('//') or re.match(r'^function\s+\w+|^\(function\s*\(', s):
        print(f"Raw JS at line ~{i}: {s[:60]!r}")
        sys.exit(1)
sys.exit(0)
PYEOF
  then
    : # clean
  else
    fail "Raw JS outside <script> tags detected: $rel"
  fi
done

# ── Summary ───────────────────────────────────────────────────────────────────

TEMPLATE_COUNT=$(find_templates | wc -l)
echo ""
echo "[validate] ══════════════════════════════════════════"
echo "[validate] Template Validation — $TEMPLATE_COUNT files scanned"
echo "[validate] Errors:   ${#ERRORS[@]}"

# ── Check 8: _internal/schema.html (we own json-ld.html — internal is redundant) ──
echo "[validate] Checking for _internal/schema.html (duplicate JSON-LD)..."
if grep -rn '_internal/schema\.html' "$REPO_ROOT/layouts" "$REPO_ROOT/themes" \
    --include="*.html" -l 2>/dev/null | grep -q .; then
  CULPRITS=$(grep -rn '_internal/schema\.html' "$REPO_ROOT/layouts" "$REPO_ROOT/themes" --include="*.html")
  warn "_internal/schema.html found — generates duplicate JSON-LD alongside json-ld.html: $CULPRITS"
fi

# ── Check 9: Identical shadow files (root == theme, theme copy is dead weight) ──
echo "[validate] Checking for identical shadow files..."
ROOT_LAYOUTS="$REPO_ROOT/layouts"
THEME_LAYOUTS="$REPO_ROOT/themes/uutistenlukija/layouts"
while IFS= read -r -d '' rfile; do
  rel="${rfile#$ROOT_LAYOUTS/}"
  tfile="$THEME_LAYOUTS/$rel"
  if [[ -f "$tfile" ]] && cmp -s "$rfile" "$tfile"; then
    warn "Identical shadow: $rel exists in both root and theme (remove theme copy)"
  fi
done < <(find "$ROOT_LAYOUTS" -name "*.html" -print0)

echo "[validate] Warnings: ${#WARNINGS[@]}"

for w in "${WARNINGS[@]}"; do
  echo "[validate] ⚠️  $w"
done

for e in "${ERRORS[@]}"; do
  echo "[validate] ❌ $e"
done

if [[ "${#ERRORS[@]}" -gt 0 ]]; then
  echo "[validate] ══════════════════════════════════════════"
  echo "[validate] VALIDATION FAILED — deploy aborted"

  # Discord alert
  if [[ -n "$DISCORD_WEBHOOK" && "$NO_DISCORD" != "--no-discord" ]]; then
    TS=$(date -u '+%Y-%m-%d %H:%M UTC')
    MSG="🚨 **Hugo template validation FAILED** — deploy aborted\\n**Time:** $TS\\n**Errors (${#ERRORS[@]}):**"
    for e in "${ERRORS[@]}"; do
      MSG+="\\n  \`$e\`"
    done
    python3 -c "
import urllib.request, json, sys
webhook = '$DISCORD_WEBHOOK'
msg = sys.argv[1].replace('\\\\n', '\n')
payload = json.dumps({'content': msg}).encode('utf-8')
req = urllib.request.Request(webhook, data=payload, headers={'Content-Type':'application/json'}, method='POST')
try:
    urllib.request.urlopen(req, timeout=10)
    print('[validate] Discord alert sent')
except Exception as ex:
    print(f'[validate] Discord alert failed: {ex}', file=sys.stderr)
" "$MSG"
  fi

  exit 1
fi

echo "[validate] ✅ All templates valid — proceeding with deploy"
exit 0
