#!/usr/bin/env python3
"""Fix ALL Hugo template issues blocking GitHub Actions deploys."""
import os, re

BASE = os.path.dirname(os.path.abspath(__file__))

def fix_file(rel_path, replacements):
    path = os.path.join(BASE, rel_path)
    if not os.path.exists(path):
        print(f"SKIP (not found): {rel_path}")
        return
    with open(path) as f:
        content = f.read()
    original = content
    for old, new in replacements:
        content = content.replace(old, new)
    if content != original:
        with open(path, 'w') as f:
            f.write(content)
        print(f"FIXED: {rel_path}")
    else:
        print(f"OK (no changes needed): {rel_path}")

# Fix 1: index.html — all deprecated math shortcuts
fix_file('layouts/index.html', [
    ('sub $nowUnix 86400', 'math.Sub $nowUnix 86400'),
    ('div (sub $nowUnix', 'math.Div (math.Sub $nowUnix'),
    ('sub 1.0 (div $hoursAgo', 'math.Sub 1.0 (math.Div $hoursAgo'),
    ('mul (sub $sourceCount', 'math.Mul (math.Sub $sourceCount'),
    ('sub 1.0 $sourcePenalty', 'math.Sub 1.0 $sourcePenalty'),
    ('mul (sub $categoryCount', 'math.Mul (math.Sub $categoryCount'),
    ('sub 1.0 $categoryPenalty', 'math.Sub 1.0 $categoryPenalty'),
    # The big score line
    ('add (add (mul $recencyScore 0.4) (mul $sourceDiversityScore 0.2)) (add (mul $categoryBalanceScore 0.2) (mul $imageScore 0.2))',
     'math.Add (math.Add (math.Mul $recencyScore 0.4) (math.Mul $sourceDiversityScore 0.2)) (math.Add (math.Mul $categoryBalanceScore 0.2) (math.Mul $imageScore 0.2))'),
])

# Fix 2: single.html — reading time calc
fix_file('layouts/_default/single.html', [
    ('div (add .WordCount 199) 200', 'math.Div (math.Add .WordCount 199) 200'),
])

# Fix 3: freshness-label.html — math shortcuts + time()
fix_file('layouts/partials/freshness-label.html', [
    ('(sub $now.Unix $date.Unix)', '(math.Sub $now.Unix $date.Unix)'),
    ('(div $diffSec 3600)', '(math.Div $diffSec 3600)'),
    ('$yesterdayUnix := sub $now.Unix 86400', '$yesterdayDay := (now.AddDate 0 0 -1) | time.Format "2006-01-02"'),
    ('$yesterday := time $yesterdayUnix', ''),
    ('$yesterday := time.AsTime $yesterdayUnix', ''),
    ('$yesterdayDay := $yesterday | time.Format "2006-01-02"', ''),
])

# Fix 4: paivan-kooste/list.html — _internal/pagination.html
fix_file('layouts/paivan-kooste/list.html', [
    ('{{ template "_internal/pagination.html" . }}',
     '{{/* Pagination — Hugo 0.147 removed _internal/pagination */}}'),
])

# Fix 5: paivan-kooste/single.html — sort empty slice
fix_file('layouts/paivan-kooste/single.html', [
    ('{{ $dayPosts = $dayPosts | sort "Date" "desc" }}',
     '{{ if gt (len $dayPosts) 0 }}{{ $dayPosts = sort $dayPosts "Date" "desc" }}{{ end }}'),
])

# Fix 6: toimitus.html — hugo.Data → .Site.Data
fix_file('layouts/_default/toimitus.html', [
    ('hugo.Data.writers', '.Site.Data.writers'),
])

# Clean up empty lines left from removing $yesterday lines
path = os.path.join(BASE, 'layouts/partials/freshness-label.html')
if os.path.exists(path):
    with open(path) as f:
        lines = f.readlines()
    # Remove blank lines that are just whitespace + newline between template lines
    cleaned = []
    for line in lines:
        if line.strip() == '' and cleaned and cleaned[-1].strip() == '':
            continue  # skip consecutive blank lines
        if line.strip() in ('{{- -}}', '{{-  -}}'):
            continue  # skip empty template blocks
        cleaned.append(line)
    with open(path, 'w') as f:
        f.writelines(cleaned)

print("\nAll template fixes applied. Run 'bash scripts/validate_templates.sh --no-discord' to verify.")
