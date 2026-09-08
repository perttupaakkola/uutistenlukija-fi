#!/usr/bin/env python3
"""Isolated category regressions, including the actual staged caller closure.
Run with -I -B and an explicit preserved housing JSON fixture argument.
Adapted from morning-writer diagnosis's unchanged AST extraction/audit hook.
No production imports; only captured provider response and scratch storage.
All stdlib imports load BEFORE an audit hook denies external I/O.
"""
from __future__ import annotations
import argparse
import ast
from collections import Counter
import copy
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import types
import unittest
import tempfile
import shutil
from typing import Any, Iterable, NamedTuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

SOURCE = Path(__file__).resolve().parent
# Only the explicitly supplied preserved evidence is copied before the guard.
# Cleanup uses absolute paths below, not shutil's descriptor-relative traversal.
ROOT = Path(tempfile.mkdtemp(prefix="uutis-category-contract-")).resolve()
if len(sys.argv) != 2:
    raise SystemExit("usage: python3 -I -B pipeline/run_category_contract_tests.py SAVED_HOUSING_JSON")
shutil.copyfile(sys.argv[1], ROOT / "housing.json")
sys.argv = [sys.argv[0]]
os.chdir(ROOT)
os.environ.clear()
sys.dont_write_bytecode = True
DENIALS = []

def audit(event, args):
    def permitted(path):
        if isinstance(path, int):
            return False
        path = os.path.realpath(os.fsdecode(path))
        return path == str(ROOT) or path.startswith(str(ROOT) + os.sep)
    if event == 'open':
        if not permitted(args[0]):
            # unittest may load stdlib source for a failure traceback, never data.
            path = os.path.realpath(os.fsdecode(args[0])) if not isinstance(args[0], int) else ''
            write = bool((args[2] or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if not write and (path.startswith('/usr/') or path.startswith(str(SOURCE) + os.sep)) and path.endswith(('.py', '.pyc')):
                return
            DENIALS.append(event)
            raise PermissionError('fixture audit denies outside-scratch open')
    elif event.startswith(('socket.', 'subprocess.')) or event in {'os.system', 'os.posix_spawn', 'os.fork', 'os.exec', 'ctypes.dlopen'}:
        DENIALS.append(event)
        raise PermissionError('fixture audit denies network/process/native load')
    elif event in {'os.listdir', 'os.scandir', 'os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.utime', 'os.truncate'}:
        if not permitted(args[0]):
            DENIALS.append(event)
            raise PermissionError('fixture audit denies outside-scratch filesystem action')
    elif event in {'os.rename', 'os.link', 'os.symlink'}:
        if not permitted(args[0]) or not permitted(args[1]):
            DENIALS.append(event)
            raise PermissionError('fixture audit denies external mutation')

sys.addaudithook(audit)

# Verify guard denies before attempting real reads/writes or network/process.
GUARD_TESTS = []
for name, operation in [
    ('private_read', lambda: open('/home/pertt/.env', 'r')),
    ('production_write', lambda: open('/home/pertt/worktrees/uutistenlukija-rebuild-20260907/morning-diagnosis-MUST-NOT-EXIST', 'w')),
    ('network', lambda: socket.socket()),
    ('process', lambda: subprocess.run(['/usr/bin/true'], check=True)),
]:
    try:
        operation()
    except PermissionError:
        GUARD_TESTS.append(name)
    else:
        raise AssertionError('guard failed: ' + name)
EXPECTED_GUARD_DENIALS = len(DENIALS)

COMMON = {name: globals()[name] for name in ('re', 'json', 'math', 'html', 'os', 'Path', 'datetime', 'timedelta', 'timezone', 'dataclass', 'NamedTuple', 'Any', 'Iterable', 'Counter', 'SequenceMatcher', 'parsedate_to_datetime', 'parse_qsl', 'urlencode', 'urlparse', 'urlsplit', 'urlunsplit')}
LOADED = {}


def extract(module, targets, injected=None):
    """Compile unchanged AST declaration closure, excluding all import blocks.

    No production package is imported and no top-level configuration executes.
    Exact function source/line numbers remain unchanged. External dependencies
    are explicitly injected from other exact pure extracts, not reimplemented.
    """
    path = SOURCE / (module + '.py')
    tree = ast.parse(path.read_text(), filename=str(path))
    declarations = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            declarations[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            dests = node.targets if isinstance(node, ast.Assign) else [node.target]
            for dest in dests:
                if isinstance(dest, ast.Name):
                    declarations[dest.id] = node
    namespace = {**COMMON, **(injected or {})}
    needed = set(targets)
    scanned = set()
    while needed - scanned:
        name = sorted(needed - scanned)[0]
        scanned.add(name)
        if name in namespace or name not in declarations:
            continue
        node = declarations[name]
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) and child.id in declarations:
                needed.add(child.id)
    nodes = [node for node in tree.body if any(declarations.get(name) is node for name in needed if name not in namespace)]
    unit = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    ast.fix_missing_locations(unit)
    module_name = 'morning_fixture_' + module
    obj = types.ModuleType(module_name)
    obj.__dict__.update(namespace)
    obj.__file__ = str(path)
    sys.modules[module_name] = obj
    exec(compile(unit, str(path), 'exec'), obj.__dict__)
    LOADED[module] = [{'name': name, 'line': declarations[name].lineno} for name in sorted(needed) if name in declarations and name not in namespace]
    return obj.__dict__

category = extract('category_guard', ['category_text', 'protect_business_category', 'protect_tiede_category', 'contains_token'])
category_deps = {key: category[key] for key in ['category_text', 'protect_business_category', 'protect_tiede_category', 'contains_token']}
heading = extract('heading_integrity', ['corrupt_heading_lines'])
attribution = extract('source_attribution', ['normalize_source_usage', 'build_source_attributions', 'project_public_source_attributions', 'normalize_source_url', 'source_identity_key'])
attr_deps = {key: attribution[key] for key in ['normalize_source_usage', 'build_source_attributions', 'project_public_source_attributions', 'normalize_source_url', 'source_identity_key']}
sufficiency = extract('source_sufficiency', ['deduplicated_selected_source_words', 'article_source_ratio', 'MIN_DISTINCT_SOURCE_WORDS', 'MAX_ARTICLE_SOURCE_RATIO', 'word_count', 'selected_source_admission_errors'], attr_deps)
suff_deps = {key: sufficiency[key] for key in ['deduplicated_selected_source_words', 'article_source_ratio', 'MIN_DISTINCT_SOURCE_WORDS', 'MAX_ARTICLE_SOURCE_RATIO', 'word_count']}
writer_targets = ['_extract_json_object', '_basic_payload_issues', '_merge_article', '_persist_source_usage', '_synchronize_packet_category', '_packet_source_words', '_packet_source_blocks', '_build_prompt', '_build_repair_prompt', 'ALLOWED_CATEGORIES']
writer = extract('monica_writer', writer_targets, {**category_deps, **attr_deps, 'corrupt_heading_lines': heading['corrupt_heading_lines']})
packet_mod = extract('story_packet', ['_infer_category'], category_deps)
publisher = extract('publisher', ['effective_category', 'CANONICAL_CATEGORIES'], category_deps)
freshness = extract('freshness', ['freshness_reasons'])
description = extract('description_projection', ['project_public_description'])
preflight = extract('publish_preflight', ['evaluate_publish_preflight'], {**attr_deps, **suff_deps, 'CANONICAL_CATEGORIES': publisher['CANONICAL_CATEGORIES'], 'effective_category': publisher['effective_category'], 'corrupt_heading_lines': heading['corrupt_heading_lines'], 'freshness_reasons': freshness['freshness_reasons'], 'project_public_description': description['project_public_description']})

fixture = json.loads((ROOT / 'housing.json').read_text())
now = datetime.fromisoformat(fixture.get('publish_preflight_rejected_at') or fixture['completed_at'])

class CategoryContractTests(unittest.TestCase):
    def replay(self, original=None, packet=None, payload=None):
        data = copy.deepcopy(fixture)
        original = copy.deepcopy(original if original is not None else data['original_article'])
        packet = copy.deepcopy(packet if packet is not None else data['packet'])
        payload = copy.deepcopy(payload if payload is not None else data['payload'])
        article = writer['_merge_article'](original, packet, payload)
        sync = writer['_synchronize_packet_category'](packet, original, payload, article)
        data.update(original_article=original, packet=packet, payload=payload, article=article)
        verdict = preflight['evaluate_publish_preflight'](data, now=now)
        return article, sync, verdict, data

    def test_saved_canonical_payload_overwrite_counterfactual(self):
        payload = {**fixture['payload'], 'category': 'Kotimaa'}
        article, sync, verdict, data = self.replay(payload=payload)
        self.assertEqual(article['category'], 'Kotimaa')
        self.assertEqual(sync, 'Kotimaa')
        self.assertEqual(verdict.action, 'publish', verdict)
        for key in ('title', 'summary', 'content'):
            self.assertEqual(article[key], fixture['article'][key])

    def test_generic_payload_rejected_by_writer(self):
        self.assertNotIn('Uutiset', writer['ALLOWED_CATEGORIES'])
        self.assertTrue(any('category' in issue for issue in writer['_basic_payload_issues'](fixture['payload'], fixture['packet'])))

    def test_generic_feed_hint_does_not_hide_canonical_guess(self):
        self.assertEqual(packet_mod['_infer_category'](fixture['original_article'], fixture['packet']['clean_source_blocks']), 'Kotimaa')

    def test_generic_hint_does_not_hide_canonical_section(self):
        for cat in ('Kulttuuri', 'Urheilu', 'Teknologia'):
            with self.subTest(category=cat):
                self.assertEqual(packet_mod['_infer_category']({'category_hint':'Uutiset', 'category':cat, 'title':'Uusi uutinen'}, []), cat)

    def test_original_generic_packet_still_rejected_without_unanimity(self):
        article, sync, verdict, data = self.replay()
        self.assertEqual(sync, '')
        self.assertEqual(verdict.action, 'reject')
        self.assertIn('category_unresolved', verdict.reasons)

    def test_conflicting_canonical_signals_fail_closed(self):
        # Tiede is intentionally demoted for this non-science article by the
        # existing semantic guard, so use categories without that correction.
        for field, value in (('category', 'Kulttuuri'), ('category', 'Urheilu')):
            packet = {**fixture['packet'], field:value, 'category_hint':value}
            article, sync, verdict, data = self.replay(packet=packet, payload={**fixture['payload'], 'category':'Kotimaa'})
            self.assertEqual(sync, '')
            self.assertEqual(verdict.action, 'reject', verdict)

    def test_no_blank_or_unknown_merge_default_to_kotimaa(self):
        for category_value in ('', 'Uutiset', 'Unknown'):
            article = writer['_merge_article']({}, {'category':category_value}, {'category':category_value})
            self.assertEqual(article['category'], '')

    def test_unanimity_requires_all_four_canonical_signals(self):
        for index in range(4):
            for value in ('', 'Uutiset', 'Kulttuuri'):
                original={'_guessed_category':'Kotimaa'}
                article={'_guessed_category':'Kotimaa','category':'Kotimaa'}
                payload={'category':'Kotimaa'}
                destinations=[(original,'_guessed_category'),(article,'_guessed_category'),(payload,'category'),(article,'category')]
                target,key=destinations[index]; target[key]=value
                packet={'category':'Uutiset','category_hint':'Uutiset'}
                self.assertEqual(writer['_synchronize_packet_category'](packet,original,payload,article),'')
                self.assertEqual(packet['category'],'Uutiset')

    def test_semantic_category_controls(self):
        controls = [
            ({'title':'Wall Street ja Kiinan pörssi', 'category_hint':'Uutiset','_guessed_category':'Talous'}, 'Talous'),
            ({'title':'Venäjän sota Ukrainassa', 'category_hint':'Uutiset'}, 'Ulkomaat'),
            ({'title':'Poliisi otti kiinni Samkin tiloissa liikkuneen aseistautuneen henkilön', 'description':'Poliisi kertoo tilanteesta Satakunnan ammattikorkeakoulun kampuksella.', 'category_hint':'Tiede'}, 'Kotimaa'),
        ]
        for original, expected in controls:
            with self.subTest(expected=expected):
                self.assertEqual(packet_mod['_infer_category'](original, []), expected)
                article=writer['_merge_article'](original, {'category': original['category_hint']}, {'category':expected, 'title':original['title']})
                self.assertEqual(article['category'], expected)

    def test_existing_talous_ulkomaat_merge_controls(self):
        for stale, canonical in [('Ulkomaat','Talous'),('Kotimaa','Ulkomaat')]:
            original={'_guessed_category':canonical}
            packet={'category':stale, 'category_hint':stale}
            payload={'category':canonical}
            article=writer['_merge_article'](original,packet,payload)
            self.assertEqual(article['category'],canonical)
            self.assertEqual(writer['_synchronize_packet_category'](packet,original,payload,article),canonical)

    def test_actual_staged_process_one_packet_then_preflight(self):
        payload={**fixture['payload'],'category':'Kotimaa'}
        calls=[]
        def captured_writer(prompt):
            calls.append(prompt)
            return json.dumps(payload)
        injected={**attr_deps, **suff_deps,
            **{key:value for key,value in writer.items() if key.startswith('_') and not key.startswith('__')},
            'monica_packet_source_words':writer['_packet_source_words'],
            'monica_packet_source_blocks':writer['_packet_source_blocks'],
            'selected_source_admission_errors':sufficiency['selected_source_admission_errors'],
            'STAGED_ROOT': ROOT / 'staged', '_run_monica':captured_writer,
        }
        staged=extract('staged_publish',['process_one_packet'],injected)
        ready=ROOT / 'staged/ready/housing.json'
        ready.parent.mkdir(parents=True)
        ready.write_text(json.dumps({'packet':fixture['packet'],'original_article':fixture['original_article']}))
        status,detail=staged['process_one_packet'](ready, argparse.Namespace())
        self.assertEqual(status,'ok',detail)
        self.assertEqual(len(calls),1)
        self.assertFalse(ready.exists())
        self.assertFalse((ROOT/'staged/writing/housing.json').exists())
        out=json.loads((ROOT/'staged/outbox/housing.json').read_text())
        self.assertEqual(out['packet']['category'],'Kotimaa')
        self.assertEqual(out['article']['category'],'Kotimaa')
        verdict=preflight['evaluate_publish_preflight'](out,now=now)
        self.assertEqual(verdict.action,'publish',verdict)

if __name__ == '__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CategoryContractTests))
    receipt={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'expected_guard_denials':EXPECTED_GUARD_DENIALS,'unexpected_guard_denials':len(DENIALS)-EXPECTED_GUARD_DENIALS,'fixture_sha256':hashlib.sha256((ROOT/'housing.json').read_bytes()).hexdigest(),'source_sha256':{name:hashlib.sha256((SOURCE/(name+'.py')).read_bytes()).hexdigest() for name in ('story_packet','monica_writer','staged_publish','publish_preflight')}}
    print('CATEGORY_CONTRACT_RECEIPT '+json.dumps(receipt,sort_keys=True))
    assert len(DENIALS)==EXPECTED_GUARD_DENIALS, DENIALS
    for path in sorted(ROOT.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        path.rmdir() if path.is_dir() else path.unlink()
    ROOT.rmdir()
    sys.exit(not result.wasSuccessful())
