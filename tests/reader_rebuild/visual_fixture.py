"""Local static visual check. Never executes site JavaScript or requests providers."""
from pathlib import Path
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = Path('/home/pertt/outputs/news-rebuild-20260907/scratch/reader')
css = '\n'.join((ROOT / p).read_text() for p in [
    'themes/uutistenlukija/static/css/style.css',
    'themes/uutistenlukija/static/css/homepage-polish.css',
    'themes/uutistenlukija/static/css/article.css',
    'assets/css/portal-overhaul.css',
])
results = []
for name, width, height, theme in [('home',390,844,'light'), ('home',390,844,'dark'), ('home',1366,900,'light'), ('tyre',390,844,'light')]:
    html = (SCRATCH / 'rendered' / (name+'.html')).read_text()
    html = re.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=re.S)
    html = re.sub(r'<link\b[^>]*>', '', html)
    html = re.sub(r'\s+on[a-z]+="[^"]*"', '', html)
    html = html.replace('class="article-image ', 'class="img-loaded article-image ').replace('class="article-hero-img"', 'class="loaded article-hero-img"')
    html = re.sub(r'\s+srcset="[^"]*"', '', html)
    html = re.sub(r'<source\b[^>]*>', '', html)
    def local_image(match):
        source = match.group(1).split('?')[0]
        for directory in ['static', 'themes/uutistenlukija/static']:
            candidate = ROOT / directory / source.lstrip('/')
            if source.startswith('/') and candidate.is_file():
                return 'src="'+candidate.as_uri()+'"'
        return 'src="data:,"'
    html = re.sub(r'src="([^"]*)"', local_image, html)
    html = html.replace('<html lang="fi">', '<html lang="fi" data-theme="'+theme+'">')
    html = html.replace('</head>', '<style>'+css+'</style></head>')
    # This fixture-only probe records layout dimensions; all site scripts are gone.
    html = html.replace('</body>', '''<script>window.addEventListener('load',function(){var e=document.createElement('pre');e.id='fixture-metrics';e.hidden=true;e.textContent=JSON.stringify({viewport:innerWidth,document:document.documentElement.scrollWidth,lead:!!document.querySelector('.portal-lead')});document.body.appendChild(e)});</script></body>''')
    stem = f'{name}-{width}-{theme}'
    fixture = SCRATCH / (stem+'.html'); fixture.write_text(html)
    command = ['node', str(ROOT / 'tests/reader_rebuild/capture_fixture.mjs'), fixture.as_uri(), str(SCRATCH / (stem+'.png')), str(SCRATCH / 'chrome-profile'), str(width), str(height)]
    run = subprocess.run(command,capture_output=True,text=True,timeout=30)
    if run.returncode: raise RuntimeError(run.stderr[-1000:])
    result = {'fixture':stem, **json.loads(run.stdout)}
    if result['viewport'] != width: raise AssertionError(result)
    results.append(result)
    if result['document'] > result['viewport']: raise AssertionError(result)
(SCRATCH/'visual-results.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,indent=2))
