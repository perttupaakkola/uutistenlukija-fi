#!/usr/bin/env python3
"""Fix Hugo template issues blocking GitHub Actions deploys."""
import os

BASE = os.path.dirname(os.path.abspath(__file__))

# Fix 1: paivan-kooste/list.html — remove _internal/pagination.html
path = os.path.join(BASE, 'layouts/paivan-kooste/list.html')
if os.path.exists(path):
    with open(path) as f:
        c = f.read()
    c = c.replace(
        '{{ template "_internal/pagination.html" . }}',
        '{{/* Pagination — Hugo 0.147 removed _internal/pagination */}}'
    )
    with open(path, 'w') as f:
        f.write(c)
    print(f"Fixed: {path}")

# Fix 2: paivan-kooste/single.html — protect sort from empty slice
path = os.path.join(BASE, 'layouts/paivan-kooste/single.html')
if os.path.exists(path):
    with open(path) as f:
        c = f.read()
    c = c.replace(
        '{{ $dayPosts = $dayPosts | sort "Date" "desc" }}',
        '{{ if gt (len $dayPosts) 0 }}{{ $dayPosts = sort $dayPosts "Date" "desc" }}{{ end }}'
    )
    with open(path, 'w') as f:
        f.write(c)
    print(f"Fixed: {path}")

# Fix 3: toimitus.html — hugo.Data → .Site.Data
path = os.path.join(BASE, 'layouts/_default/toimitus.html')
if os.path.exists(path):
    with open(path) as f:
        c = f.read()
    c = c.replace('hugo.Data.writers', '.Site.Data.writers')
    with open(path, 'w') as f:
        f.write(c)
    print(f"Fixed: {path}")

print("All fixes applied.")
