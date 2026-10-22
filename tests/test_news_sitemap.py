"""Focused, synthetic coverage for Google News metadata in the ordinary sitemap."""
import json
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import test_release_v2 as base
from news_mvp import publish
from news_mvp.site import article_path
from news_mvp.store import database


SITEMAP_NS='http://www.sitemaps.org/schemas/sitemap/0.9'
NEWS_NS='http://www.google.com/schemas/sitemap-news/0.9'
NS={'sm':SITEMAP_NS,'news':NEWS_NS}
NOW=datetime(2026,10,7,12,0,tzinfo=timezone.utc)


def row(number,created_at,title='Synteettinen uutinen'):
    identifier=f'{number:012x}'+'a'*52
    return {
        'id':identifier,
        'created_at':created_at if isinstance(created_at,str) else created_at.isoformat(),
        'draft':json.dumps({'title':title},ensure_ascii=False),
    }


def write_page(site,job,canonical=True):
    path=article_path(job)
    output=site/path/'index.html'
    output.parent.mkdir(parents=True,exist_ok=True)
    href=('https://uutistenlukija.fi/'+path if canonical
          else 'https://uutistenlukija.fi/eri-sivu/')
    try: rendered_date=publish.timestamp(job['created_at']).astimezone(timezone.utc).isoformat()
    except (ValueError,OverflowError): rendered_date=job['created_at']
    payload={'@type':'NewsArticle','headline':json.loads(job['draft'])['title'],
             'mainEntityOfPage':{'@type':'WebPage','@id':href},
             'datePublished':rendered_date}
    output.write_text('<!doctype html><link rel="canonical" href="'+href+'">'
                      '<script type="application/ld+json">'+json.dumps(payload)+
                      '</script>',encoding='utf-8')
    return path


class NewsSitemapHelpers(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site=Path(self.tmp.name)/'site'
        self.site.mkdir()

    def test_48_hour_boundary_offsets_future_and_invalid_records(self):
        boundary=row(1,NOW-timedelta(hours=48),'Täsmälleen 48 tuntia')
        old=row(2,NOW-timedelta(hours=48,seconds=1),'Liian vanha')
        future=row(3,NOW+timedelta(seconds=1),'Tulevaisuudessa')
        offset=row(4,'2026-10-07T13:00:00+02:00','Aikavyöhykkeen uutinen')
        escaped=row(5,NOW-timedelta(hours=2),'A & B <C> "D"')
        bad_date=row(6,'ei-aika','Virheellinen aika')
        bad_title=row(7,NOW-timedelta(hours=1),'   ')
        bad_xml=row(8,NOW-timedelta(hours=1),'Nolla\x00merkki')
        wrong_canonical=row(9,NOW-timedelta(hours=1),'Väärä canonical')
        missing_page=row(10,NOW-timedelta(hours=1),'Puuttuva sivu')
        unpublished=row(11,NOW-timedelta(hours=1),'Ei julkaistu')
        rows=[boundary,old,future,offset,escaped,bad_date,bad_title,bad_xml,
              wrong_canonical,missing_page,unpublished]
        for job in rows:
            if job is not missing_page:
                write_page(self.site,job,canonical=job is not wrong_canonical)
        eligible={job['id'] for job in rows if job is not unpublished}

        metadata=publish._recent_news_metadata(self.site,eligible,rows,NOW)

        self.assertEqual(set(metadata),{boundary['id'],offset['id'],escaped['id']})
        self.assertEqual(metadata[boundary['id']]['publication_date'],
                         '2026-10-05T12:00:00+00:00')
        self.assertEqual(metadata[offset['id']]['publication_date'],
                         '2026-10-07T11:00:00+00:00')
        self.assertEqual(metadata[escaped['id']]['title'],'A & B <C> "D"')

    def test_overflow_and_stale_render_omit_optional_news(self):
        for date in ('0001-01-01T00:00:00+14:00','9999-12-31T23:59:59-14:00'):
            job=row(12,date)
            self.assertEqual(publish._recent_news_metadata(self.site,{job['id']},[job],NOW),{})
        job=row(13,NOW-timedelta(hours=1),'Alpha beta gamma delta epsilon zeta eta theta OLD')
        path=write_page(self.site,job)
        page=self.site/path/'index.html'
        original=page.read_text()
        self.assertTrue(publish._recent_news_metadata(self.site,{job['id']},[job],NOW))
        for changed in (original.replace('theta OLD','theta NEW'),
                        original.replace('2026-10-07T11:00:00+00:00','2026-10-07T10:00:00+00:00'),
                        original+original[original.index('<script'):],
                        original.replace('"@type": "NewsArticle"','not-json')):
            self.assertNotEqual(changed,original)
            page.write_text(changed)
            self.assertEqual(publish._recent_news_metadata(self.site,{job['id']},[job],NOW),{})

    def test_xml_escaping_and_original_date_stays_distinct_from_amendment_lastmod(self):
        original='2026-10-07T08:15:00+00:00'
        amended='2026-10-07T11:45:00+00:00'
        title='A & B <C> "D"'
        entry=publish._sitemap_url_entry(
            'https://uutistenlukija.fi/uutiset/a-b/?x=1&y=2',amended,
            {'publication_date':original,'title':title})
        document=('<?xml version="1.0"?><urlset xmlns="'+SITEMAP_NS+
                  '" xmlns:news="'+NEWS_NS+'">'+entry+'</urlset>')

        self.assertIn('<news:title>A &amp; B &lt;C&gt; &quot;D&quot;</news:title>',entry)
        self.assertIn('?x=1&amp;y=2</loc>',entry)
        root=ET.fromstring(document)
        url=root.find('sm:url',NS)
        self.assertEqual(url.findtext('sm:lastmod',namespaces=NS),amended)
        self.assertEqual(url.findtext('news:news/news:publication_date',namespaces=NS),original)
        self.assertEqual(url.findtext('news:news/news:title',namespaces=NS),title)
        self.assertEqual(url.findtext('news:news/news:publication/news:name',namespaces=NS),
                         'Uutistenlukija')
        self.assertEqual(url.findtext('news:news/news:publication/news:language',namespaces=NS),'fi')

    def test_1000_cap_is_deterministic_and_retains_every_ordinary_entry(self):
        rows=[row(index,NOW-timedelta(seconds=index),f'Uutinen {index}')
              for index in range(1002)]
        eligible={job['id'] for job in rows}
        with patch.object(publish,'_published_news_metadata',
                          side_effect=lambda site,path,title,published:
                          {'publication_date':published.isoformat(),'title':title}):
            first=publish._recent_news_metadata(self.site,eligible,rows,NOW)
            second=publish._recent_news_metadata(self.site,eligible,list(reversed(rows)),NOW)
        expected={job['id'] for job in rows[:1000]}
        self.assertEqual(set(first),expected)
        self.assertEqual(list(first),list(second))

        title_by_id={job['id']:job['draft'] for job in rows}
        article_mod={job['id']:'2026-10-07T12:00:00+00:00' for job in rows}
        entries=publish._article_sitemap_entries(eligible,title_by_id,article_mod,first)
        document=('<urlset xmlns="'+SITEMAP_NS+'" xmlns:news="'+NEWS_NS+'">'+
                  ''.join(entries)+'</urlset>')
        root=ET.fromstring(document)
        urls=root.findall('sm:url',NS)
        self.assertEqual(len(urls),1002)
        self.assertEqual(sum(url.find('news:news',NS) is not None for url in urls),1000)
        self.assertTrue(all(url.find('sm:loc',NS) is not None for url in urls))


class NewsSitemapBundleCallsite(unittest.TestCase):
    def test_public_bundle_pauses_news_metadata_preserving_ordinary_date_and_url(self):
        case=base.ReleaseV2('source_fetch')
        case.setUp()
        self.addCleanup(case.doCleanups)
        job=case.ready()
        draft=json.loads(job['draft'])
        published=publish.timestamp(job['created_at'])
        frozen=published+timedelta(hours=1)

        class FrozenDateTime:
            calls=0

            @classmethod
            def now(cls,tz):
                cls.calls+=1
                self.assertIs(tz,timezone.utc)
                return frozen

        with database(case.state) as store, \
                patch.object(publish,'cmd',return_value=base.COMMIT), \
                patch.object(publish,'datetime',FrozenDateTime):
            site,_receipt=publish.public_bundle(store,job,case.state)

        sitemap=(site/'sitemap.xml').read_text(encoding='utf-8')
        self.assertIn('xmlns:news="'+NEWS_NS+'"',sitemap)
        root=ET.fromstring(sitemap)
        wanted='https://uutistenlukija.fi/'+article_path(job)
        article_url=next(url for url in root.findall('sm:url',NS)
                         if url.findtext('sm:loc',namespaces=NS)==wanted)
        news=article_url.find('news:news',NS)
        self.assertIsNone(news)
        self.assertEqual(root.findall('.//news:news',NS),[])
        self.assertEqual(article_url.findtext('sm:lastmod',namespaces=NS),
                         published.strftime('%Y-%m-%dT%H:%M:%S+00:00'))
        self.assertEqual(FrozenDateTime.calls,1)
        self.assertEqual((site/'robots.txt').read_text(encoding='utf-8'),
                         'User-agent: *\nAllow: /\nSitemap: https://uutistenlukija.fi/sitemap.xml\n')
        home=next(url for url in root.findall('sm:url',NS)
                  if url.findtext('sm:loc',namespaces=NS)=='https://uutistenlukija.fi/')
        self.assertIsNone(home.find('news:news',NS))


if __name__=='__main__':
    unittest.main()
