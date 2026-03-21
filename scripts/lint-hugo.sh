#!/bin/bash
# lint-hugo.sh — catch common Hugo template errors before they break builds
# Run: bash scripts/lint-hugo.sh
set -euo pipefail

ERRORS=0

echo "=== Hugo Template Lint ==="

# 1. Invalid pipe syntax: `| first` WITHOUT a count (Hugo needs `| first N` or `index .Coll 0`)
# `| first 3` is valid Hugo. `| first` alone is NOT.
BAD_FIRST=$(grep -rn '| first[^[:space:]0-9]' layouts/ 2>/dev/null || true)
BAD_FIRST2=$(grep -rn '| first }}' layouts/ 2>/dev/null || true)
BAD_FIRST3=$(grep -rn '| first$' layouts/ 2>/dev/null || true)
ALL_BAD="${BAD_FIRST}${BAD_FIRST2}${BAD_FIRST3}"
if [ -n "$ALL_BAD" ]; then
    echo "❌ INVALID: '| first' without count (use 'index .Collection 0' or '| first 1')"
    echo "$ALL_BAD" | sort -u
    ERRORS=$((ERRORS + 1))
fi

# 2. YAML frontmatter: unescaped quotes in image_alt
BAD_ALT=$(grep -rn 'image_alt: ".*\\"' content/posts/ 2>/dev/null | grep -v '""$' | grep -v '\""$' || true)
if [ -n "$BAD_ALT" ]; then
    echo "❌ BROKEN YAML: image_alt with unescaped quotes"
    echo "$BAD_ALT"
    ERRORS=$((ERRORS + 1))
fi

# 3. Go template if/else inside JS that creates context mismatch
BAD_JS=$(grep -rn '{{- if \$\.Is' layouts/ 2>/dev/null | grep -v 'var\|isPage\|isNode' || true)
if [ -n "$BAD_JS" ]; then
    echo "⚠️  WARNING: Go template conditional inside JS (potential context mismatch)"
    echo "$BAD_JS"
fi

if [ "$ERRORS" -eq 0 ]; then
    echo "✅ All checks passed"
    exit 0
else
    echo ""
    echo "Found $ERRORS error(s). Fix before committing."
    exit 1
fi
