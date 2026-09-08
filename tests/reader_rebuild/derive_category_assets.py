"""Reproduce the six R6 display assets from retained repository originals.

No fetch/generation provider calls. Only writes the explicit derivatives/manifest;
never replaces an original, frontmatter, attribution, policy or publication file.
"""
import hashlib
import json
from pathlib import Path
import subprocess
from PIL import Image, __version__, features

ROOT = Path(__file__).resolve().parents[2]
CATEGORIES = ('talous', 'ulkomaat', 'kulttuuri', 'teknologia', 'tiede', 'urheilu')


def describe(path):
    with Image.open(path) as image:
        size, format_name = image.size, image.format
    return {'path': str(path.relative_to(ROOT)), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'width': size[0], 'height': size[1], 'format': format_name}


def main():
    rows = []
    for category in CATEGORIES:
        source = ROOT / f'static/images/categories/{category}.jpg'
        dest = ROOT / f'themes/uutistenlukija/static/images/illustrations/{category}.webp'
        dest.parent.mkdir(parents=True, exist_ok=True)
        original = describe(source)
        with Image.open(source) as image:
            image = image.convert('RGB')
            image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            image.save(dest, format='WEBP', quality=80, method=6)
        assert describe(source) == original
        result = describe(dest)
        assert result['bytes'] < min(120_000, original['bytes'] // 4)
        rows.append({'category': category, 'original': original, 'result': result,
                     'saved_bytes': original['bytes'] - result['bytes']})
    manifest = {'schema': 'retained-category-derivatives/v1',
                'original_asset_commit': '9f3c9afa44c6256d8a48d0c202b6fb9e4ef4a6ed',
                'pillow': __version__, 'libwebp': features.version('webp'),
                'recipe': 'RGB; thumbnail 1200x1200 LANCZOS (no crop); WEBP quality=80 method=6',
                'rights': 'Derived solely from existing site illustrations. Originals and original Git provenance retained; no new license or ownership claim. Caller attribution and generic-illustration semantics unchanged.',
                'assets': rows}
    (ROOT / 'tests/reader_rebuild/category-assets.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
