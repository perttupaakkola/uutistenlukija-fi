# OPE-192 Article Description Backfill

Run time: 2026-06-15 19:03 UTC

## Baseline

`python3 pipeline/validate_articles.py --dry-run` before the backfill checked 3,129 articles and reported:

- Content score: 89/100
- Missing or too-long descriptions: 193
- Missing hero images: 160
- Missing tags: 28
- Thin content: 0
- Duplicate titles: 0
- Missing categories: 0

## Change

- Backfilled 187 empty article descriptions using the repository's existing body-derived description logic.
- Manually tightened the remaining 6 overlong descriptions to stay within the validator's 155-character limit.
- Fixed `pipeline/validate_articles.py --dry-run --fix-descriptions` so dry-run mode no longer mutates files.
- Added `pipeline/test_validate_articles.py` coverage for dry-run and live fix behavior.

## Verification

`python3 pipeline/validate_articles.py --dry-run` after the backfill checked 3,129 articles and reported:

- Content score: 95/100
- Missing or too-long descriptions: 0
- Missing hero images: 160
- Missing tags: 28
- Thin content: 0
- Duplicate titles: 0
- Missing categories: 0

`python3 pipeline/validate_frontmatter.py` passed with only existing non-blocking warnings for missing images and long titles.

Full frontmatter YAML parse scan reported `yaml_errors=0`.

`python3 -m py_compile pipeline/validate_articles.py pipeline/test_validate_articles.py` passed.

`python3 -m unittest pipeline.test_validate_articles -q` passed.

`./scripts/validate_templates.sh` passed with 112 files scanned, 0 errors, and the existing 2 identical-shadow warnings.

`/home/pertt/.openclaw/workspace/hugo --minify --destination /tmp/uutistenlukija-ope192-description-check` passed with 8,563 pages.

`python3 scripts/check_public_file_count.py --public-dir /tmp/uutistenlukija-ope192-description-check --limit 20000` passed with 15,252 files and 4,748 headroom.

## Remaining SEO Trust Work

The article-description part of OPE-192 is closed by this pass. The next metadata trust gap is image coverage: 160 older articles still lack hero images.
