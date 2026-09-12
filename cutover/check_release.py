"""Check the exact reviewed static bundle, never invoke the model or publisher."""
import hashlib
import json
from pathlib import Path


def check(root, receipt):
    root = Path(root).resolve()
    if receipt.get('public_release_authorized') is not True or receipt.get('hermes_step') != 5:
        raise ValueError('Public release has not been authorized')
    if receipt.get('origin') != 'https://uutistenlukija.fi' or receipt.get('ga4_id') != 'G-35XERS8V6J':
        raise ValueError('Canonical site/analytics identity changed')
    files=receipt['files']
    if not files or 'index.html' not in files:
        raise ValueError('Missing release files')
    actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
    if actual != set(files):
        raise ValueError('Release file set changed')
    for name,sha in files.items():
        file=root/name
        if not file.resolve().is_relative_to(root) or hashlib.sha256(file.read_bytes()).hexdigest()!=sha:
            raise ValueError('Release bytes changed: '+name)
    for name in ['index.html']+receipt['new_article_files']:
        data=(root/name).read_text()
        if any(s in data for s in ('noindex,nofollow','Yksityinen esikatselu','keksitty uutinen','example.invalid')):
            raise ValueError('Private or fixture page in public release')
    return len(files)


if __name__=='__main__':
    import sys
    print(check(sys.argv[1],json.loads(Path(sys.argv[2]).read_text())))
