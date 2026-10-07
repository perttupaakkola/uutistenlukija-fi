"""Portable synthetic article render projections, never publication receipts."""
import copy
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from html import escape
from news_mvp import release_contract as rc, site, seo
from cutover.check_release import check
from tests.test_amendment_release_consumer import portable_amendment


def projected_html(packet, draft):
    e = packet['final_review_input']['source_packet']; m = e['public_metadata']
    sources = [dict(c['capture_source'], id=c['id']) for c in e['preparation']['citations']]
    route = m['canonical'].removeprefix('https://uutistenlukija.fi')
    numbers = {s['id']: i+1 for i,s in enumerate(sources)}
    paragraphs = ['<p>'+site._paragraph_text_html(route,p,sources)+' <span class="citations">'+
        ' '.join(f'<a href="#lahde-{numbers[s]}">[{numbers[s]}]</a>' for s in p['source_ids'])+'</span></p>' for p in draft['paragraphs']]
    image = site.display_image(draft['image']); url = '/mvp-assets/'+image['sha256']+'.jpg'
    ld = seo.news_article_jsonld(draft['title'],seo.meta_description(draft['summary'],[p['text'] for p in draft['paragraphs']]),route,
        published=site.timestamp(m['datePublished']).isoformat(),modified=site.timestamp(m['dateModified']).isoformat(),
        category=draft['category'],image_url=url,sources=sources)
    html = '<!doctype html><html><head><link rel="canonical" href="'+m['canonical']+'">'+ld+'</head><body><article class="story single-article">'
    html += '<h1>'+escape(draft['title'])+'</h1><p class="article-meta" data-category="'+draft['category']+'"><span>Julkaistu '+site.time_html(m['datePublished'])+'</span></p>'
    html += site.article_status_html(m['notice'])+'<p class="lead">'+escape(draft['summary'])+'</p>'
    html += '<div class="article-reading-grid"><div class="article-reading-main">'+site.article_hero_figure(image,url)+'<div class="content">'+''.join(paragraphs)+'</div></div>'
    html += '<div class="article-afterword"><div class="article-evidence"><section class="sources"><h2>Lähteet</h2><ol>'+site.source_list_html(sources)+'</ol></section>'
    html += site.reuse_rights_html(sources)+site.image_rights_html(image)+'</div></div></div></article></body></html>'
    return html, paragraphs


def mutations(html, paragraphs, packet, draft):
    m = packet['final_review_input']['source_packet']['public_metadata']
    article = html[html.index('<article '):html.index('</article>')+len('</article>')]
    yield 'closed_details_ancestor', html.replace(article, '<details><summary>Open story</summary>'+article+'</details>')
    yield 'whole_article_in_head', html.replace(article, '').replace('</head>', article+'</head>')
    yield 'css_hidden_body', html.replace('</head>', '<style>.content { display: none !important; }</style></head>')
    yield 'hidden_hero', html.replace('<figure class="article-hero"', '<figure hidden class="article-hero"', 1)
    yield 'inert_hero', html.replace('<figure class="article-hero"', '<figure inert class="article-hero"', 1)
    yield 'styled_hero', html.replace('<figure class="article-hero"', '<figure style="opacity:0" class="article-hero"', 1)
    yield 'inert_body', html.replace('<body>', '<body inert>')
    yield 'extra_direct_prose', html.replace('</h1>', '</h1><p>Stale unreviewed claim.</p>', 1)
    yield 'extra_grid_prose', html.replace('<div class="article-reading-grid">', '<div class="article-reading-grid"><p>Stale unreviewed claim.</p>', 1)
    yield 'extra_meta_prose', html.replace('</span></p>', '</span>Wrong publication claim.</p>', 1)
    yield 'extra_afterword_prose', html.replace('<div class="article-afterword">', '<div class="article-afterword">Wrong prose', 1)
    yield 'extra_evidence_prose', html.replace('<div class="article-evidence">', '<div class="article-evidence"><p>Wrong prose</p>', 1)
    yield 'empty', '<html><body></body></html>'
    yield 'stale', '<html><body><article class="story single-article"><h1>Old</h1><p class="lead">Old</p><div class="content"><p>Old</p><p>Old</p><p>Extra</p></div></article></body></html>'
    for name, body in [('shuffled',list(reversed(paragraphs))),('duplicate',paragraphs+[paragraphs[0]]),('extra',paragraphs+['<p>Stale extra</p>']),('missing',paragraphs[1:])]:
        yield name, html.replace(''.join(paragraphs),''.join(body))
    yield 'hidden', html.replace('<article class=', '<article hidden class=')
    yield 'duplicate_article', html.replace('</body>','<article class="story single-article"></article></body>')
    yield 'duplicate_h1', html.replace('</article>','<h1>'+escape(draft['title'])+'</h1></article>')
    yield 'duplicate_lead', html.replace('</article>','<p class="lead">'+escape(draft['summary'])+'</p></article>')
    yield 'duplicate_content', html.replace('</article>','<div class="content"></div></article>')
    yield 'missing_status', re.sub(r'<section class="article-status .*?</section>','',html)
    yield 'wrong_note', html.replace(escape(m['notice']['note']), 'Wrong notice')
    yield 'wrong_canonical', html.replace('rel="canonical" href="'+m['canonical'], 'rel="canonical" href="https://uutistenlukija.fi/uutiset/wrong/')
    yield 'wrong_date', html.replace('datetime="'+site.semantic_datetime(m['datePublished'])[0], 'datetime="2000-01-01T00:00:00+00:00')
    yield 'wrong_jsonld', html.replace('"dateModified":', '"staleDateModified":')
    yield 'wrong_source', html.replace('<li id="lahde-1"><a href="', '<li id="lahde-1"><a href="https://wrong.invalid/')
    yield 'wrong_citation', html.replace('href="#lahde-1"','href="#lahde-99"')
    yield 'wrong_rights', html.replace('class="source-reuse"','class="wrong-reuse"')
    yield 'wrong_image', html.replace('/mvp-assets/'+draft['image']['sha256']+'.jpg', '/mvp-assets/'+('0'*64)+'.jpg')
    yield 'wrong_image_license', html.replace(escape(draft['image']['license_url']), 'https://wrong.invalid/license')
    yield 'text_only_in_comment', html.replace(paragraphs[0], '<!--'+paragraphs[0]+'-->')
    yield 'hidden_ancestor', html.replace('<body>', '<body hidden>')
    yield 'wrong_publication_label', html.replace('Julkaistu ', 'Wrong publication ')
    yield 'wrong_category', html.replace('data-category="'+draft['category']+'"', 'data-category="Wrong"')
    status = site.article_status_html(m['notice'])
    yield 'duplicate_status', html.replace(status, status+status)
    lead = '<p class="lead">'+escape(draft['summary'])+'</p>'
    yield 'reordered_lead', html.replace(lead, '').replace('<h1>',lead+'<h1>',1)
    canonical = '<link rel="canonical" href="'+m['canonical']+'">'
    yield 'duplicate_canonical', html.replace(canonical,canonical+canonical)
    yield 'noncanonical_link', html.replace('rel="canonical"','rel="alternate"')
    ld = re.search(r'<script type="application/ld\+json">.*?</script>',html).group()
    yield 'duplicate_jsonld', html.replace(ld,ld+ld)
    yield 'duplicate_jsonld_key', html.replace('"datePublished":','"datePublished":"2000-01-01T00:00:00Z","datePublished":')
    sources = [dict(c['capture_source'],id=c['id']) for c in packet['final_review_input']['source_packet']['preparation']['citations']]
    yield 'reordered_sources', html.replace(site.source_list_html(sources),site.source_list_html(list(reversed(sources))))
    yield 'wrong_text_license', html.replace(escape(sources[0]['reuse']['license']), 'Wrong text license')
    yield 'wrong_text_changes', html.replace(escape(sources[0]['reuse']['changes']), 'Wrong changes')
    yield 'wrong_source_date', html.replace(site.time_html(sources[0]['published_at']),site.time_html('2000-01-01T00:00:00Z'))
    yield 'wrong_source_label', html.replace(escape(sources[0]['publisher'])+': '+escape(sources[0]['title']), 'Wrong source')
    yield 'paragraph_in_script', html.replace(paragraphs[0],'<script>'+paragraphs[0]+'</script>')
    yield 'relocated_body', html.replace('<div class="article-reading-main">','<div class="wrong-main">')
    yield 'extra_reading_prose', html.replace('<div class="content">','<p>Stale outside body</p><div class="content">')
    yield 'wrong_text_license_link', html.replace(escape(sources[0]['reuse']['license_url']), 'https://wrong.invalid/text-license')
    if sources[0]['reuse'].get('notice'):
        yield 'wrong_reuse_notice', html.replace(escape(sources[0]['reuse']['notice']), 'Wrong notice')


def exercise(packet, draft, image_bytes, root):
    html, paragraphs = projected_html(packet,draft)
    binding = rc.media(packet,draft)
    assert hashlib.sha256(image_bytes).hexdigest() == binding['image_sha256']
    m = binding['amendment']['public_metadata']; name = m['canonical'].removeprefix('https://uutistenlukija.fi/').rstrip('/')+'/index.html'
    image_name = 'mvp-assets/'+binding['image_sha256']+'.jpg'
    receipt = {'schema_version':3,'packet':packet,'draft':draft,'review':packet['final_review_result']['review'],
        'packet_sha256':rc.digest(packet),'draft_sha256':rc.digest(draft),'job_id':binding['amendment']['job_id'],
        'source_commit':packet['final_review_result']['source_ref'],**binding,
        'public_release_authorized':True,'hermes_step':5,'origin':'https://uutistenlukija.fi','ga4_id':'G-35XERS8V6J',
        'new_article_files':[name]}
    # In-memory synthetic authorization only; no deployment or production receipt.
    files = {'index.html':b'<html><body>News</body></html>',name:html.encode(),image_name:image_bytes}
    for n,data in files.items():
        p=root/n; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(data)
    receipt['files'] = {n:hashlib.sha256(data).hexdigest() for n,data in files.items()}
    rc.check_article(html,packet,draft,canonical=m['canonical']); assert check(root,receipt)==3
    count=0
    for label, changed in mutations(html,paragraphs,packet,draft):
        (root/name).write_text(changed); receipt['files'][name]=hashlib.sha256(changed.encode()).hexdigest()
        for caller in ('shared','hosted'):
            try:
                if caller=='shared': rc.check_article(changed,packet,draft,canonical=m['canonical'])
                else: check(root,receipt)
            except ValueError: pass
            else: raise AssertionError(label+' accepted by '+caller)
        count+=1
    (root/name).write_text(html); receipt['files'][name]=hashlib.sha256(html.encode()).hexdigest()
    for names in ([],[name,name],['index.html']):
        receipt['new_article_files']=names
        try: check(root,receipt)
        except ValueError: pass
        else: raise AssertionError('bad canonical article manifest accepted')
    try: rc.check_article(html,packet,draft,canonical='https://uutistenlukija.fi/uutiset/wrong/')
    except ValueError: pass
    else: raise AssertionError('canonical argument accepted')
    return count


class AmendmentArticleGateTests(unittest.TestCase):
    def test_actual_renderer_shell_and_supported_adjuncts(self):
        packet, draft = portable_amendment()
        html, _ = projected_html(packet, draft)
        m = packet['final_review_input']['source_packet']['public_metadata']
        route = m['canonical'].removeprefix('https://uutistenlukija.fi')
        breadcrumb = ('<nav class="article-breadcrumb" aria-label="Murupolku"><ol>'
            '<li><a href="/">Etusivu</a></li><li><a href="'+escape(site.category_route(draft['category']))+'">'+
            escape(site.category_display(draft['category']))+'</a></li><li aria-current="page">Juttu</li></ol></nav>')
        html = html.replace('<h1>', breadcrumb+'<h1>', 1)
        html = html.replace('</span></p>', '</span><span class="article-reading-time">'+
            str(site.reading_time_minutes(draft))+' min lukuaika</span></p>', 1)
        html = html.replace('<div class="article-reading-grid">',
            site.article_actions_html(route, draft['category'], True, draft['title'])+'<div class="article-reading-grid">', 1)
        context = site.article_context_html({'id': 1}, draft,
            [({'id': 2, 'slug': 'other-story', 'created_at': m['datePublished']}, {}, draft, {})])
        html = html.replace('<div class="article-afterword">', context+'<div class="article-afterword">', 1)
        sources = packet['final_review_input']['source_packet']['preparation']['citations']
        label = '1 uutislähde' if len(sources) == 1 else str(len(sources))+' uutislähdettä'
        html = html.replace('<h2>Lähteet</h2><ol>', '<h2>Lähteet</h2><p class="source-count">'+label+'</p><ol>')
        article = html[html.index('<article '):html.index('</article>')+len('</article>')]
        ld_match = re.search(r'<script type="application/ld\+json">.*?</script>', html)
        assert ld_match is not None
        ld = ld_match.group()
        rendered = site.page(draft['title'], article, canonical_path=route, head_meta=ld)
        self.assertNotIn('<style', rendered)
        rc.check_article(rendered, packet, draft, canonical=m['canonical'])

    def test_unmocked_shared_and_hosted_projection(self):
        packet,draft=portable_amendment()
        with tempfile.TemporaryDirectory() as directory:
            self.assertGreaterEqual(exercise(packet,draft,b'synthetic image bytes',Path(directory)),20)

if __name__=='__main__': unittest.main()
