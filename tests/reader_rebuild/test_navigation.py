"""Small offline render of the actual all-news route/header, including page two."""
import json, os, re, shutil, subprocess, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
HUGO = os.environ.get('HUGO_BIN', '/home/pertt/.openclaw/workspace/bin/hugo')
class ArchiveContract(unittest.TestCase):
    def test_all_categories_pagination_and_honest_labels(self):
        scratch = Path('/home/pertt/outputs/news-rebuild-20260907/scratch/navigation')
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            site = Path(directory)
            shutil.copytree(ROOT/'layouts/partials', site/'layouts/partials')
            (site/'layouts/_default').mkdir()
            shutil.copy(ROOT/'layouts/_default/digest-page.html', site/'layouts/_default/digest-page.html')
            (site/'layouts/_default/baseof.html').write_text('<html><head>{{ block "extra_head" . }}{{ end }}</head><body>{{ partial "header.html" . }}<main>{{ block "main" . }}{{ end }}</main></body></html>')
            (site/'layouts/_default/single.html').write_text('{{ define "main" }}{{ .Content }}{{ end }}')
            (site/'hugo.toml').write_text('baseURL="https://fixture.invalid/"\ntitle="Uutistenlukija"\ndisableKinds=["home","RSS","sitemap","taxonomy","term","404"]\n'+ '[menu]\n'+(ROOT/'hugo.toml').read_text().split('[menu]\n',1)[1])
            (site/'content/posts').mkdir(parents=True)
            shutil.copytree(ROOT/'content/paivan-tarkeimmat-uutiset', site/'content/paivan-tarkeimmat-uutiset')
            stories=[('Current domestic','Kotimaa','2026-09-07T10:00:00Z')]+[(f'Current {cat}',cat,'2026-09-06T10:00:00Z') for cat in ['Urheilu','Kulttuuri','Tiede']]+[(f'Archive {i:02}','Ulkomaat',f'2026-09-05T10:{i:02}:00Z') for i in range(31)]+[('Old technology','Teknologia','2026-08-26T10:00:00Z')]
            for i,(title,category,date) in enumerate(stories):
                (site/f'content/posts/story-{i}.md').write_text(f'---\ntitle: "{title}"\ndate: {date}\ncategories: ["{category}"]\ndescription: Test\n---\nBody\n')
            result=subprocess.run([HUGO,'--source',str(site),'--noBuildLock','--cacheDir',str(site/'cache')],capture_output=True,text=True,timeout=40)
            self.assertEqual(result.returncode,0,result.stderr)
            pages=[(site/'public/paivan-tarkeimmat-uutiset'/x/'index.html').read_text() for x in ['', 'page/2']]
            all_titles=[]
            for index,html in enumerate(pages):
                self.assertNotIn('>Live<',html)
                self.assertNotIn('portal-live-dot',html)
                self.assertNotIn('Päivän tärkeimmät',html)
                main=html.split('<main>')[1].split('</main>')[0]
                titles=re.findall(r'<h2><a[^>]*>(.*?)</a></h2>',main)
                all_titles+=titles
                schemas=[json.loads(x) for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>',html,re.S)]
                collection=next(s for s in schemas if s.get('@type')=='CollectionPage')
                self.assertEqual([x['name'] for x in collection['itemListElement']],titles)
                for cat in ['Kotimaa','Ulkomaat','Talous','Teknologia','Urheilu','Kulttuuri','Tiede','Oppaat']:
                    self.assertIn(cat,html.split('<main>')[0])
                (scratch/f'archive-page-{index+1}.html').write_text(html)
            self.assertEqual(len(all_titles),len(stories))
            self.assertEqual(set(all_titles),{x[0] for x in stories})
            self.assertEqual(all_titles[0],'Current domestic')
            self.assertEqual(all_titles[-1],'Old technology')
            self.assertIn('/paivan-tarkeimmat-uutiset/page/2/',pages[0])
            self.assertIn('Uudempia uutisia',pages[1])
if __name__=='__main__':unittest.main()
