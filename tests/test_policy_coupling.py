"""A policy-coupled field must not block RE-RENDERING an already-released article.

Twice now, a change that must apply going forward bricked the whole archive, because
re-rendering re-ran a policy-coupled check against today's policy:

1. the packet's policy digest was re-checked for every article in the bundle;
2. the source's `reuse` record (generated from the provider's declared licence) was compared
   for every article, so declaring a provider's real licence failed every existing page.

The invariant these tests pin is expressed directly against the released bundles in the real
state directory, because that is where the failure actually appeared.
"""

import json
import unittest
from pathlib import Path

STATE = Path('/home/pertt/.local/share/uutistenlukija')


def released_bundles():
    """Every released article's (packet, draft) as stored, newest first."""
    import sqlite3
    if not (STATE / 'jobs.sqlite').is_file():
        return []
    connection = sqlite3.connect(f'file:{STATE}/jobs.sqlite?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT j.packet, j.draft FROM jobs j JOIN publications p ON p.job_id = j.id "
        "WHERE p.status = 'deployed'").fetchall()
    return [(json.loads(r['packet']), json.loads(r['draft'])) for r in rows]


def official_bundles():
    """Released articles that went through the official-source (text-only) path."""
    return [(p, d) for p, d in released_bundles() if isinstance(p.get('publication_basis'), dict)
            and p['publication_basis'].get('provider')]


class ArchiveCanAlwaysBeReRendered(unittest.TestCase):
    """The archive must stay renderable no matter how the policy moves on."""

    def test_every_released_article_re_renders_with_policy_gate_off(self):
        bundles = released_bundles()
        if not bundles:
            self.skipTest('no released articles in this environment')
        from news_mvp.release_contract import media
        failures = []
        for packet, draft in bundles:
            try:
                media(packet, draft, policy_gate=False)
            except ValueError as error:
                url = (packet.get('sources') or [{}])[0].get('url', '?')
                failures.append(f'{url}: {error}')
        self.assertEqual(failures, [],
                         'a released article cannot be re-rendered; this blocks ALL publishing')

    def test_re_rendering_still_enforces_structural_provenance(self):
        """Turning off policy coupling must not turn off provenance."""
        from news_mvp.release_contract import media
        bundles = official_bundles()
        if not bundles:
            self.skipTest('no official-source articles in this environment')
        packet, draft = json.loads(json.dumps(bundles[0][0])), bundles[0][1]
        packet['sources'][0]['publisher'] = 'Impostor Publisher'
        with self.assertRaises(ValueError):
            media(packet, draft, policy_gate=False)


class PolicyCouplingSemantics(unittest.TestCase):
    """The gate argument decides policy coupling; nothing else may skip provenance."""

    def test_media_accepts_a_policy_gate_keyword(self):
        import inspect
        from news_mvp.release_contract import media
        params = inspect.signature(media).parameters
        self.assertIn('policy_gate', params)
        self.assertTrue(params['policy_gate'].default, 'new releases must be gated by default')


if __name__ == '__main__':
    unittest.main()
