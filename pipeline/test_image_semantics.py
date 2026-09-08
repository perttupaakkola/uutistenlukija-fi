"""IMG-DIAG-1/2: attribution, final-only concepts, real publisher projection.

Use run_image_semantics_tests.py for pre-import I/O enforcement. All external
boundaries are assertions/mocks; fixture metadata is never provider evidence.
"""
from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

import audit_image_flow as audit
import image_candidate_guard as guard
import publisher

OUTLETS = ('Yle Uutisten mukaan', 'MTV Uutisten mukaan', 'The Guardianin mukaan')
RAIL = 'railway tracks, rail infrastructure, or railway construction'
SURVEY = 'public opinion survey or questionnaire'
ELECTION = 'election voting or ballot'
CANDIDATES = {
    'rail': {'id': 'railTest123', 'alt': 'railway tracks and rail infrastructure construction'},
    'survey': {'id': 'surveyT1234', 'alt': 'public opinion survey questionnaire documents'},
    'ballot': {'id': 'ballotT1234', 'alt': 'election voting ballot box'},
    'winter_rail': {'id': 'winterT1234', 'alt': 'railway tracks and rail infrastructure in snow winter'},
    'paris_rail': {'id': 'parisT12345', 'alt': 'railway tracks and rail infrastructure in Paris France'},
}
for candidate in CANDIDATES.values():
    candidate['photo_page'] = (
        'https://unsplash.com/photos/'
        + candidate['alt'].lower().replace(' ', '-') + '-' + candidate['id']
    )


def article(**updates):
    return {
        'title': 'Rautatiehanke uudistaa rataverkon', 'category': 'Kotimaa',
        'summary': '', 'key_points': [], 'content': 'Rautatien rakennustyöt etenevät.',
        'tags': ['hanke'], **updates,
    }


def fields(value) -> dict[str, Any]:
    return {key: value.get(key) or ([] if key == 'key_points' else '')
            for key in ('title', 'category', 'summary', 'key_points', 'content')} | {
        'source_evidence': value.get('source_text') or value.get('research') or '',
    }


def project(value):
    # Exercise the actual production Markdown publisher, not a replica of its
    # front matter. Tags keep the unrelated SEO file fallback out of this test.
    text = publisher._article_to_markdown(value, '2026-09-08T00:00:00+00:00')
    return text, audit._frontmatter_from_text(text), audit._body_from_text(text).strip()


class AttributionTests(unittest.TestCase):
    def test_verified_outlet_spans_are_not_people_in_either_classifier(self):
        for phrase in OUTLETS:
            with self.subTest(phrase=phrase):
                self.assertFalse(guard._named_person_like(phrase))
                self.assertEqual(audit._named_people(phrase), [])

    def test_outlets_preserve_railway_queries_in_every_input_field(self):
        for phrase in OUTLETS:
            for field in ('title', 'summary', 'key_points', 'content', 'source_text', 'research'):
                value = phrase + ' rautatiehanke uudistaa rataverkon.'
                data = article(**{field: [value] if field == 'key_points' else value})
                with self.subTest(phrase=phrase, field=field):
                    brief = guard.build_visual_brief(**fields(data))
                    self.assertFalse(brief.intent.named_person)
                    self.assertTrue(brief.intent.stock_ok)
                    self.assertEqual(brief.intent.must_have, [RAIL])
                    self.assertEqual(len(guard.build_stock_queries(**fields(data))), 3)

    def test_real_people_and_mixed_attributions_remain_unsafe(self):
        for phrase in OUTLETS:
            for person in (
                'Matti Virtanen kommentoi hanketta.', 'Matti Virtasen mukaan hanke etenee.',
                'Tutkija Virtanen kommentoi hanketta.', 'Virtanen vaatii muutosta.',
                'Presidentti Virtanen', 'Matti Virtanen',
            ):
                for text in (f'{phrase} {person}', f'{person} {phrase} hanke etenee.'):
                    with self.subTest(text=text):
                        self.assertTrue(guard._named_person_like(text))
                        brief = guard.build_visual_brief(**fields(article(summary=text)))
                        self.assertFalse(brief.intent.stock_ok)
                        self.assertEqual(guard.build_stock_queries(**fields(article(summary=text))), [])
                        if 'Matti' in person or person.startswith('Presidentti'):
                            self.assertTrue(audit._named_people(text))

    def test_only_exact_attributions_are_exempt_not_global_outlet_words(self):
        for text in (
            'Yle Uutisten kertoi hankkeesta.', 'The Guardianin vaatii muutosta.',
            'Yle Virtanen kommentoi.', 'Guardianin Virtanen kommentoi.',
            'Tutkija Uutisten kommentoi.', 'XThe Guardianin mukaan',
        ):
            with self.subTest(text=text):
                self.assertTrue(guard._named_person_like(text))

    def test_sensitive_source_and_final_stories_still_block_both_lanes(self):
        for phrase in OUTLETS:
            for field in ('summary', 'content', 'source_text', 'research'):
                data = article(**{field: f'{phrase} onnettomuus johti kuolemaan.'})
                with self.subTest(phrase=phrase, field=field):
                    intent = guard.build_image_intent(**fields(data))
                    self.assertTrue(intent.sensitive_story)
                    self.assertFalse(intent.stock_ok)
                    self.assertFalse(intent.generated_ok)

    def test_outlet_railway_candidate_survives_real_markdown_audit(self):
        for phrase in OUTLETS:
            with self.subTest(phrase=phrase), tempfile.TemporaryDirectory() as tmp:
                candidate = CANDIDATES['rail']
                data = article(summary=f'{phrase} rautatiehanke etenee.',
                               image='https://images.unsplash.com/photo-fixture',
                               image_source='unsplash', image_category_fallback=False,
                               image_candidate_id=candidate['id'],
                               image_source_url=candidate['photo_page'],
                               image_candidate_url=candidate['photo_page'])
                text, fm, body = project(data)
                self.assertIn(phrase, fm['summary'])
                self.assertEqual(body, data['content'])
                post = Path(tmp) / 'article.md'
                post.write_text(text)
                row = audit._audit_article(post)
                self.assertEqual(row['status'], 'ok', row['reason'])


class FinalGroundingTests(unittest.TestCase):
    def test_unpublished_fourth_key_point_cannot_ground_positive_intent(self):
        data = article(title='Valmistelu jatkuu', content='Päätös annetaan myöhemmin.',
                       key_points=['Valmistelu etenee.', 'Päätös annetaan pian.', 'Käsittely jatkuu.',
                                   'Kysely ja survey questionnaire julkaistiin.'])
        _, fm, body = project(data)
        self.assertEqual(len(fm['key_points']), 3)
        self.assertNotIn('Kysely', body)
        brief = guard.build_visual_brief(**fields(data))
        self.assertEqual(brief.intent.must_have, [])
        self.assertEqual(brief.acceptable_concepts, [])
        self.assertFalse(brief.intent.generated_ok)
        self.assertEqual(guard.build_stock_queries(**fields(data)), [])
        data['key_points'][3] = 'Matti Virtanen kommentoi väkivallan uhreja.'
        intent = guard.build_image_intent(**fields(data))
        self.assertTrue(intent.named_person)
        self.assertTrue(intent.sensitive_story)

    def test_audit_description_cannot_create_positive_article_truth(self):
        data = article(title='Valmistelu jatkuu', content='Päätös annetaan myöhemmin.',
                       description='Survey questionnaire snow winter weather in Paris France.')
        _, fm, body = project(data)
        truth = audit._derive_audit_truth(fm, body)
        self.assertEqual(truth.acceptable_concepts, ())
        self.assertEqual(truth.locations, ())
        self.assertEqual(truth.season_time, 'neutral')

    def test_audit_description_retains_safety_exclusions(self):
        data = article(description='Matti Virtanen kommentoi onnettomuutta.')
        _, fm, body = project(data)
        truth = audit._derive_audit_truth(fm, body)
        self.assertTrue(truth.named_person)
        self.assertTrue(truth.sensitive_story)
        self.assertFalse(truth.stock_ok)

    def test_key_point_projection_drops_blanks_before_three_point_cap(self):
        data = article(title='Valmistelu jatkuu', content='Päätös annetaan myöhemmin.',
                       key_points=['', 'Valmistelu etenee.', ' ', 'Päätös annetaan pian.',
                                   'Kysely ja kyselylomake julkaistiin.', 'Snow winter in Paris France.'])
        _, fm, body = project(data)
        brief = guard.build_visual_brief(**fields(data))
        self.assertEqual(brief.intent.must_have, [SURVEY])
        self.assertEqual(brief.intent.locations, [])
        self.assertEqual(brief.intent.season_time, 'neutral')
        self.assertEqual(audit._derive_audit_truth(fm, body).acceptable_concepts, (SURVEY,))

    def test_mixed_query_and_candidate_cannot_smuggle_unsupported_half(self):
        for title in ('Kysely mittaa mielipidettä', 'Vaalit järjestetään sunnuntaina'):
            inputs = fields(article(title=title, content='Valmistelu jatkuu.'))
            brief = guard.build_visual_brief(**inputs)
            query = 'public opinion survey questionnaire election voting ballot box'
            candidate = {'id': 'mixedT12345', 'alt': query}
            with self.subTest(title=title):
                queries = guard.build_stock_queries(**inputs, primary_query=query)
                self.assertNotIn(query, [q for q, _, _ in queries])
                decision = guard.score_image_candidate(candidate, intent=brief.intent, query=query, **inputs)
                self.assertFalse(decision.accepted)
                for provider in ('unsplash', 'generated'):
                    judge = guard.judge_visual_candidate(candidate, brief=brief, provider=provider)
                    self.assertFalse(judge.accepted)
                    self.assertTrue(judge.hard_fail)
                truth = audit._derive_audit_truth({'title': title}, 'Valmistelu jatkuu.')
                self.assertFalse(audit._constraint_supported(query, truth))

    def test_source_alone_cannot_create_any_positive_concept_weather_or_location(self):
        data = article(title='Valmistelu jatkuu', content='Päätös annetaan myöhemmin.',
                       source_text='Rautatie ja rataverkon hanke. Survey poll. Snow winter in Paris France.')
        intent = guard.build_image_intent(**fields(data))
        brief = guard.build_visual_brief(**fields(data))
        self.assertEqual(intent.must_have, [])
        self.assertEqual(intent.locations, [])
        self.assertEqual(intent.season_time, 'neutral')
        self.assertEqual(intent.evidence_terms, [])
        self.assertEqual(brief.acceptable_concepts, [])
        self.assertFalse(intent.generated_ok)
        self.assertEqual(guard.build_stock_queries(**fields(data)), [])
        _, fm, body = project(data)
        truth = audit._derive_audit_truth(fm, body, source_evidence=data['source_text'])
        self.assertEqual(truth.acceptable_concepts, ())
        self.assertEqual(truth.locations, ())
        self.assertEqual(truth.season_time, 'neutral')
        self.assertFalse(truth.stock_ok)

    def test_survey_and_election_have_distinct_final_grounded_queries(self):
        cases = (
            ('Kysely mittaa mielipidettä', 'Mielipidekysely ja kyselylomake julkaistiin.', SURVEY, 'survey', 'ballot'),
            ('Vaalit järjestetään sunnuntaina', 'Vaalien äänestys ja äänestysliput valmistellaan.', ELECTION, 'ballot', 'survey'),
            ('Puolue kertoo vaalivoitosta', 'Osavaltiovaalit ratkesivat sunnuntaina.', ELECTION, 'ballot', 'survey'),
        )
        for title, prose, expected, accepted, rejected in cases:
            for field in ('title', 'summary', 'key_points', 'content'):
                data = article(title='Valmistelu jatkuu', content='Päätös annetaan myöhemmin.')
                data[field] = [title + '. ' + prose] if field == 'key_points' else title + '. ' + prose
                with self.subTest(concept=expected, field=field):
                    inputs = fields(data)
                    brief = guard.build_visual_brief(**inputs)
                    self.assertEqual(brief.intent.must_have, [expected])
                    self.assertTrue(brief.intent.generated_ok)
                    queries = guard.build_stock_queries(**inputs)
                    self.assertTrue(queries)
                    self.assertNotIn(rejected, ' '.join(q for q, _, _ in queries))
                    for name, ok in ((accepted, True), (rejected, False)):
                        candidate = CANDIDATES[name]
                        decision = guard.score_image_candidate(candidate, intent=brief.intent, query=queries[0][0], **inputs)
                        self.assertEqual(decision.accepted, ok, decision.reasons)
                        judge = guard.judge_visual_candidate(candidate, brief=brief)
                        self.assertEqual(judge.accepted, ok, judge.reasons)
                    _, fm, body = project(data)
                    truth = audit._derive_audit_truth(fm, body)
                    self.assertIn(expected, truth.acceptable_concepts)
                    self.assertNotIn(SURVEY if expected == ELECTION else ELECTION, truth.acceptable_concepts)

    def test_election_does_not_inherit_an_omitted_source_survey(self):
        data = article(title='Vaalit järjestetään sunnuntaina',
                       content='Vaalien äänestys järjestetään viikonloppuna.',
                       journalist_note='Lähteen prosenttiosuus on jätetty pois riittämättömän yksilöinnin vuoksi.',
                       source_text='Exit poll survey questionnaire. Kysely mittaa mielipidettä.')
        with_source = guard.build_visual_brief(**fields(data))
        final_only = guard.build_visual_brief(**(fields(data) | {'source_evidence': ''}))
        self.assertEqual(with_source, final_only)
        self.assertEqual(with_source.intent.must_have, [ELECTION])
        self.assertNotIn('survey', ' '.join(with_source.acceptable_concepts))
        _, fm, body = project(data)
        self.assertNotIn('Exit poll', body)
        truth = audit._derive_audit_truth(fm, body, source_evidence=data['source_text'])
        self.assertEqual(truth.acceptable_concepts, (ELECTION,))

    def test_source_cannot_allow_unsupported_weather_or_geography_on_rail_candidate(self):
        data = article(source_text='Snow winter in Paris France.')
        inputs = fields(data)
        brief = guard.build_visual_brief(**inputs)
        for name in ('winter_rail', 'paris_rail'):
            with self.subTest(candidate=name):
                decision = guard.score_image_candidate(CANDIDATES[name], intent=brief.intent,
                                                       query='railway tracks', **inputs)
                self.assertFalse(decision.accepted, decision.reasons)
        self.assertEqual(brief.intent.locations, [])
        self.assertEqual(brief.intent.season_time, 'neutral')

    def test_source_people_and_sensitivity_still_exclude_independent_audit(self):
        for source, attr in (
            ('Matti Virtanen kommentoi. Matti Virtanen vaatii muutosta.', 'named_person'),
            ('Väkivalta ja kuolema koskevat uhreja.', 'sensitive_story'),
        ):
            with self.subTest(source=source):
                data = article(source_text=source)
                runtime = guard.build_image_intent(**fields(data))
                _, fm, body = project(data)
                truth = audit._derive_audit_truth(fm, body, source_evidence=source)
                self.assertTrue(getattr(runtime, attr))
                self.assertTrue(getattr(truth, attr))
                self.assertFalse(runtime.stock_ok)
                self.assertFalse(truth.stock_ok)
                self.assertEqual(runtime.must_have, [RAIL])

    def test_query_and_poisoned_intent_cannot_self_certify_source_survey(self):
        data = article(title='Vaalit järjestetään sunnuntaina', content='Vaalien äänestys valmistellaan.',
                       source_text='Survey questionnaire poll.')
        inputs = fields(data)
        grounded = guard.build_image_intent(**inputs)
        poisoned = replace(grounded, must_have=[SURVEY])
        decision = guard.score_image_candidate(CANDIDATES['survey'], intent=poisoned,
                                               query='survey questionnaire', **inputs)
        self.assertFalse(decision.accepted)
        self.assertIn('unsupported supplied intent', '; '.join(decision.reasons))
        _, fm, body = project(data)
        truth = audit._derive_audit_truth(fm, body, source_evidence=data['source_text'])
        for value in (SURVEY, 'public opinion survey or ballot', 'survey questionnaire election ballot'):
            with self.subTest(constraint=value):
                self.assertFalse(audit._constraint_supported(value, truth))

    def test_packet_audit_uses_rendered_final_not_source_or_stored_intent(self):
        for name, ok in (('survey', False), ('ballot', True)):
            with self.subTest(candidate=name), tempfile.TemporaryDirectory() as tmp:
                candidate = CANDIDATES[name]
                data = article(title='Vaalit järjestetään sunnuntaina',
                               content='Vaalien äänestys ja äänestysliput valmistellaan.',
                               source_text='Survey questionnaire poll.',
                               image='https://images.unsplash.com/photo-fixture', image_source='unsplash',
                               image_category_fallback=False, image_candidate_id=candidate['id'],
                               image_source_url=candidate['photo_page'], image_candidate_url=candidate['photo_page'],
                               image_query='survey questionnaire', image_visual_judge_score=100)
                data['image_visual_intent'] = {'must_have': [SURVEY if not ok else ELECTION], 'stock_ok': True}
                text, _, _ = project(data)
                post, packet = Path(tmp) / 'article.md', Path(tmp) / 'packet.json'
                post.write_text(text)
                packet.write_text(json.dumps({'packet': {'source_text': data['source_text']}, 'article': data}))
                # Audit must not delegate its truth to the runtime implementation.
                with patch.object(guard, 'build_image_intent', side_effect=AssertionError('circular audit')):
                    row = audit.audit_packet(packet, post)
                    recent = audit._audit_article(post)
                self.assertEqual(row['status'], 'ok' if ok else 'flag', row['reason'])
                self.assertEqual(recent['status'], 'ok' if ok else 'flag', recent['reason'])
                if not ok:
                    self.assertIn('unsupported stored intent', row['reason'])
                    self.assertIn('candidate unrelated', row['reason'])


class PublisherPolicyProjectionTests(unittest.TestCase):
    def test_actual_enrichment_cannot_generate_from_source_only_concept(self):
        import staged_publish as staged
        for source_field in ('source_text', 'research'):
            data = article(title='Valmistelu jatkuu', content='Päätös annetaan myöhemmin.',
                           **{source_field: 'Kysely ja survey questionnaire poll.'})
            with self.subTest(source_field=source_field), ExitStack() as stack:
                stack.enter_context(patch.dict(staged.os.environ, {}, clear=True))
                for name in ('load_env_files', 'sync_image_provider_keys'):
                    stack.enter_context(patch.object(staged, name))
                forbidden = []
                for name in ('unsplash_fetch_images', 'pexels_fetch_images', 'generate_images_for_articles',
                             'should_skip', 'record_success', 'record_failure'):
                    forbidden.append(stack.enter_context(patch.object(staged, name, side_effect=AssertionError(name))))
                staged.enrich_images_for_articles([data], unsplash_delay=0, pexels_delay=0)
                terminal = data[staged.GENERATION_TERMINAL_FIELD]
                self.assertEqual(terminal['reason'], staged.REASON_PRE_SAFETY_REJECT)
                self.assertFalse(terminal['provider_attempted'])
                self.assertTrue(data['image_category_fallback'])
                for mock in forbidden:
                    mock.assert_not_called()
                text, fm, body = project(data)
                self.assertEqual(fm['image_source'], 'category_fallback')
                self.assertTrue(fm['image_category_fallback'])
                self.assertEqual(body, 'Päätös annetaan myöhemmin.')
                self.assertNotIn('survey', text)


if __name__ == '__main__':
    unittest.main()
