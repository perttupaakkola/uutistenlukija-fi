"""Check the exact reviewed static bundle, never invoke the model or publisher."""
import hashlib
import json
from pathlib import Path
import sys
# The actual script invocation starts with cutover/ on sys.path.
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from news_mvp.release_contract import receipt_media, check_article


def check(root, receipt):
    root = Path(root).resolve()
    if receipt.get('public_release_authorized') is not True or receipt.get('hermes_step') != 5:
        raise ValueError('Public release has not been authorized')
    if receipt.get('origin') != 'https://uutistenlukija.fi' or receipt.get('ga4_id') != 'G-35XERS8V6J':
        raise ValueError('Canonical site/analytics identity changed')
    binding=receipt_media(receipt)
    # Historical text-only receipts remain readable by release_contract, but the
    # deployment entrypoint may never authorize a new text-only publication.
    if receipt.get('schema_version') == 2 and not receipt['draft'].get('image'):
        raise ValueError('Text-only publication is prohibited; image preparation must retry')
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
    if binding['image_sha256'] is not None:
        image='mvp-assets/'+binding['image_sha256']+'.jpg'
        if image not in files or files[image]!=binding['image_sha256']:
            raise ValueError('Required reviewed image missing from bundle')
    if receipt.get('schema_version')==2:
        for name in receipt['new_article_files']:
            check_article((root/name).read_text(),receipt['packet'],receipt['draft'])
    if receipt.get('image_backfill'):
        from news_mvp.backfill import validate_records
        from news_mvp.editorial import digest
        if digest(receipt['image_backfill'])!=receipt.get('image_backfill_sha256'):
            raise ValueError('Archive correction receipt changed')
        validate_records(root,receipt['image_backfill'])
    return len(files)


if __name__=='__main__':
    import sys
    print(check(sys.argv[1],json.loads(Path(sys.argv[2]).read_text())))
