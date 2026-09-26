"""Source charts require their own explicit grant, original exports and exact binding."""
from copy import deepcopy
import tempfile
import unittest
from news_mvp import imagery, source_charts as charts, site
from news_mvp.editorial import digest
from news_mvp.release_contract import stock_binding, _check_rendered_stock
from test_stock_imagery import _checkerboard_bytes

URL = 'https://stat.fi/fi/julkaisu/cmfp96le0a4mm07vyv0oyqv4n'
TITLE = 'Työllisyysaste ja työllisyysasteen trendi'
SVG = (f'<svg xmlns="http://www.w3.org/2000/svg" class="highcharts-root">'
       f'<text>{TITLE}</text><text>Lähde: Tilastokeskus, työvoimatutkimus</text></svg>').encode()
HTML = f'<html><main><h2>{TITLE}</h2></main></html>'.encode()
RIGHTS = f'<p>{charts.GRANT}</p>'.encode()


class SourceCharts(unittest.TestCase):
    def evidence(self, **overrides):
        values = dict(source_url=URL,source_html=HTML,rights_html=RIGHTS,
                      svg=SVG,png=_checkerboard_bytes(),title=TITLE)
        values.update(overrides)
        return charts.capture_evidence(**values)

    def image(self):
        e = self.evidence()
        candidate = {'photo_id':charts.photo_id(e),'name':'Tilastokeskus',
            'profile':'https://stat.fi/fi/tietoa-meista','photo_page':URL,'image_url':URL,
            'license':'CC BY 4.0','license_url':charts.LICENSE_URL,'title':TITLE,'chart_evidence':e}
        decision = {'subject':'Employment statistical chart','category':'Talous',
            'depictable_scene':'A statistical employment chart with lines and labelled axes.',
            'must_show':['chart'],'must_avoid':['violence'],
            'search_queries':['employment chart','statistical chart','employment lines']}
        relevance = imagery.relevance_check('A statistical employment chart.',decision,'vision')
        with tempfile.TemporaryDirectory() as state:
            sha,path,pixels = imagery._persist_verified_image(_checkerboard_bytes(),state)
            return imagery._open_source_record('statfi',candidate,'employment chart',state,
                pixels,sha,path,'A statistical employment chart.',decision,relevance,'2026-09-26T00:00:00Z')

    def test_exact_source_chart_grant_and_exports_bind(self):
        image=self.image();stock_binding(image)
        html=site.image_rights_html(image)
        self.assertIn('Lähde:',html);self.assertIn('Tilastokeskus</a>',html)
        self.assertNotIn('Photo by',html)
        self.assertIn(charts.LICENSE_URL,html)
        self.assertIn(TITLE,html)
        article='<article>'+site.article_hero_figure(image,
            f'/mvp-assets/{image["sha256"]}.jpg')+html+'</article>'
        _check_rendered_stock(article,image)
        with self.assertRaisesRegex(ValueError,'attribution'):
            _check_rendered_stock(article.replace('Lähde:', ''),image)

    def test_text_rights_or_external_picture_cannot_be_promoted_to_chart(self):
        for changes in (
            {'source_url':URL.replace('stat.fi','stat.fi.evil.invalid')},
            {'rights_html':b'<p>You may reuse our texts.</p>'},
            {'source_html':b'<h2>Different chart</h2>'},
            {'svg':SVG.replace(b'</svg>',b'<image href="photo.jpg"/></svg>')},
            {'svg':SVG.replace(b'</svg>',b'<script>alert(1)</script></svg>')},
            {'svg':SVG.replace(TITLE.encode(),b'Another title')},
            {'svg':b'<!DOCTYPE svg>'+SVG},
        ):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                self.evidence(**changes)

    def test_rehashed_substitutions_do_not_change_source_or_rights_identity(self):
        original=self.image()
        for field,value in (('photo_url','https://example.org/other'),
                            ('photographer','Other organization'),
                            ('license_url','https://creativecommons.org/licenses/by-nc/4.0/'),
                            ('photo_id','statfi-'+'a'*24)):
            image=deepcopy(original);p=image['stock_provenance'];p[field]=value
            image['stock_provenance_sha256']=digest(p)
            with self.subTest(field=field),self.assertRaises(ValueError):stock_binding(image)
        for field,value in (('kind','photograph'),('rights_grant','Text reuse is allowed.'),
                            ('source_svg_sha256','broken'),('rights_url','https://example.org/rights')):
            image=deepcopy(original);p=image['stock_provenance'];p['chart_evidence'][field]=value
            image['stock_provenance_sha256']=digest(p)
            with self.subTest(field=field),self.assertRaises(ValueError):stock_binding(image)


if __name__=='__main__':unittest.main()
