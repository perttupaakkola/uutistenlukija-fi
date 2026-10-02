"""Synthetic credential-free RSS onboarding tests; exact unchanged portal JS."""
import json, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from news_mvp import site

DRIVER = r"""
const fs=require('fs'),vm=require('vm');
const mode=process.argv[3];
let handler, copied=null, writes=0, shares=0, networks=0;
const feedback={textContent:''};
const button={hidden:true,getAttribute:n=>n==='data-rss-copy-url'?'https://uutistenlukija.fi/rss.xml':'rss-copy-feedback',addEventListener:(n,f)=>{handler=f;}};
const navigator={share:()=>{shares++;throw Error('must not share');}};
if(mode.startsWith('clipboard')) navigator.clipboard={writeText:async value=>{if(mode==='clipboard-reject')throw Error('NotAllowedError');copied=value;}};
const doc={addEventListener(){},documentElement:{setAttribute(){},style:{}},getElementById:id=>id==='rss-copy-feedback'?feedback:null,
querySelectorAll:s=>s==='[data-rss-copy-url]'&&mode!=='absent'?[button]:[],
createElement:()=>({style:{},setAttribute(){},select(){}}),body:{appendChild:f=>{copied=f.value;},removeChild(){}},
execCommand:()=>{if(mode==='legacy-throw')throw Error('blocked');return mode!=='legacy-fail';}};
const sandbox={document:doc,window:{navigator,isSecureContext:mode!=='insecure',localStorage:{getItem:()=>null,setItem:()=>{writes++;}},matchMedia:()=>({matches:false})},fetch:()=>{networks++;throw Error('no network');}};
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),sandbox);
(async()=>{if(handler)await handler();console.log(JSON.stringify({copied,feedback:feedback.textContent,hidden:button.hidden,writes,shares,networks}));})();
"""
class RssOnboarding(unittest.TestCase):
    def run_js(self,mode):
        node=shutil.which('node');self.assertIsNotNone(node)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'driver.js';p.write_text(DRIVER)
            r=subprocess.run([node,str(p),str(site.ROOT/'static/portal.js'),mode],capture_output=True,text=True,timeout=15,check=False)
            self.assertEqual(r.returncode,0,r.stderr)
            return json.loads(r.stdout)
    def test_clipboard_and_legacy_success_no_tracking_or_share(self):
        for mode in ('clipboard-success','legacy-success','insecure'):
            with self.subTest(mode=mode):
                r=self.run_js(mode)
                self.assertEqual(r['copied'],'https://uutistenlukija.fi/rss.xml')
                self.assertEqual(r['feedback'],'Syötteen osoite kopioitu. Lisää se RSS-lukijaasi.')
                self.assertFalse(r['hidden'])
                self.assertEqual([r[k] for k in ('writes','shares','networks')],[0,0,0])
    def test_permission_denial_and_legacy_failure_manual_instruction(self):
        for mode in ('clipboard-reject','legacy-fail','legacy-throw'):
            with self.subTest(mode=mode):
                r=self.run_js(mode)
                self.assertIn('Valitse ja kopioi yllä näkyvä',r['feedback'])
                self.assertNotIn('osoite kopioitu',r['feedback'])
                self.assertEqual([r[k] for k in ('writes','shares','networks')],[0,0,0])
    def test_no_control_is_safe(self):
        r=self.run_js('absent');self.assertEqual(r['feedback'],'');self.assertIsNone(r['copied'])
    def test_real_homepage_module_preserves_reader_paths(self):
        # Reuse actual homepage renderer on synthetic rows; no production state.
        import test_homepage_images as fixtures
        case=fixtures.generated.GeneratedIntegrity(fixtures.SEED);case.setUp();self.addCleanup(case.doCleanups)
        packet,draft=case.generated();job=case.ready(packet,draft)
        output=Path(tempfile.mkdtemp(dir=case.root))
        site.render_site(fixtures.FakeStore([job]),output,case.state,public=True)
        html=(output/'index.html').read_text()
        self.assertEqual(html.count('data-rss-copy-url='),1)
        self.assertIn('data-rss-copy-url="https://uutistenlukija.fi/rss.xml"',html)
        self.assertIn('href="/rss.xml">RSS-syöte</a>',html)
        self.assertIn('aria-describedby="rss-copy-feedback" hidden',html)
        self.assertIn('aria-live="polite"',html)
        self.assertIn('Lisää syötteen osoite omaan RSS-lukijaasi',html)
        self.assertEqual(html.count('class="portal-newsletter"'),1)
        self.assertNotIn('type="email"',html)
        self.assertNotIn('front-shortcuts',html)
        self.assertIn('portal-lead',html)
