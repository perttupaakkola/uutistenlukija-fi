// Local rendered-resource acceptance. No dependencies, external requests,
// analytics transports, service workers or public writes. Run after the Python
// fixture test: node capture_category_resources.mjs <fixture>/public <evidence>.
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {readFileSync, writeFileSync, mkdirSync, mkdtempSync, rmSync, statSync, existsSync} from 'node:fs';
import {resolve, join, extname, sep} from 'node:path';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
const [rootArg, outArg] = process.argv.slice(2);
const root = resolve(rootArg), out = resolve(outArg);
assert(existsSync(join(root, '../hugo-output.txt')), 'Must be bounded test fixture output');
mkdirSync(out, {recursive:true});
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const server = createServer((req,res) => {
  let path = resolve(root, '.' + new URL(req.url,'http://localhost').pathname);
  if (req.method !== 'GET' || (path !== root && !path.startsWith(root + sep))) {res.writeHead(403).end();return;}
  if (existsSync(path) && statSync(path).isDirectory()) path = join(path,'index.html');
  try {
    const data = readFileSync(path);
    res.writeHead(200, {'Content-Type': ({'.html':'text/html; charset=utf-8','.css':'text/css','.js':'application/javascript','.webp':'image/webp','.jpg':'image/jpeg','.png':'image/png','.svg':'image/svg+xml'})[extname(path)] || 'application/octet-stream', 'Content-Length':data.length});
    res.end(data);
  } catch {res.writeHead(404).end();}
});
await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
const origin = 'http://127.0.0.1:' + server.address().port;
const profile = mkdtempSync(join(tmpdir(),'ul-category-chrome-'));
const chrome = spawn('google-chrome', ['--headless=new','--no-sandbox','--disable-gpu','--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run','--no-default-browser-check','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1','--remote-debugging-pipe','--user-data-dir='+profile], {stdio:['ignore','ignore','ignore','pipe','pipe']});
let sequence=0, buffer='', sessionId;
const pending = new Map(), blocked=[], exceptions=[], pages=[];
let resources = new Map(), jobs=[];
function call(method, params={}, sid=sessionId) {
  return new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});chrome.stdio[3].write(JSON.stringify({id,method,params,...(sid?{sessionId:sid}:{})})+'\0');});
}
chrome.stdio[4].on('data', data => {
  buffer+=data.toString();
  while(buffer.includes('\0')) {
    const end=buffer.indexOf('\0'), msg=JSON.parse(buffer.slice(0,end));buffer=buffer.slice(end+1);
    if(pending.has(msg.id)) {const p=pending.get(msg.id);pending.delete(msg.id);msg.error?p.reject(Error(JSON.stringify(msg.error))):p.resolve(msg.result);continue;}
    const p=msg.params;
    if(msg.method==='Fetch.requestPaused') {
      const allow=p.request.url.startsWith(origin+'/') && p.request.method==='GET' && ['Document','Stylesheet','Script','Image','Font'].includes(p.resourceType) && !p.request.url.endsWith('/sw.js');
      if(!allow) blocked.push({url:p.request.url, type:p.resourceType});
      call(allow?'Fetch.continueRequest':'Fetch.failRequest', {requestId:p.requestId,...(allow?{}:{errorReason:'BlockedByClient'})}).catch(()=>{});
    }
    if(msg.method==='Runtime.exceptionThrown') exceptions.push(p.exceptionDetails);
    if(msg.method==='Network.responseReceived' && p.type==='Image') resources.set(p.requestId,{url:p.response.url,status:p.response.status,mime:p.response.mimeType,fromDiskCache:p.response.fromDiskCache});
    if(msg.method==='Network.loadingFinished' && resources.has(p.requestId)) {
      const item=resources.get(p.requestId);
      jobs.push(call('Network.getResponseBody',{requestId:p.requestId}).then(body=>{
        const bytes=Buffer.from(body.body,body.base64Encoded?'base64':'utf8');
        Object.assign(item,{bodyBytes:bytes.length,sha256:hash(bytes),encodedDataLength:p.encodedDataLength});
      }));
    }
  }
});
async function evaluate(expression) {
  const result=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
  if(result.exceptionDetails) throw Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
const timeout=setTimeout(()=>{chrome.kill();process.exitCode=1;},120000);
try {
  const {targetId}=await call('Target.createTarget',{url:'about:blank'});
  sessionId=(await call('Target.attachToTarget',{targetId,flatten:true})).sessionId;
  await call('Page.enable');await call('Runtime.enable');await call('Network.enable');
  await call('Network.setCacheDisabled',{cacheDisabled:true});
  await call('Network.setBypassServiceWorker',{bypass:true});
  await call('Fetch.enable',{patterns:[{urlPattern:'*'}]});
  const relativeEpoch=Date.parse(process.env.UL_RELATIVE_CLOCK || '');
  if(Number.isFinite(relativeEpoch)) await call('Page.addScriptToEvaluateOnNewDocument',{source:`window.__relativeClock=${relativeEpoch}; Date.now=()=>window.__relativeClock;`});
  const categories=['kotimaa','talous','ulkomaat','kulttuuri','teknologia','tiede','urheilu'];
  const routes=categories.map(cat=>'categories/'+cat+'/').concat(['','posts/talous-2/','posts/ulkomaat-1/','component-cases/']);
  for(const width of [390,1366]) for(const theme of ['light','dark']) for(const route of routes) {
    resources=new Map();jobs=[];
    const errorStart=exceptions.length;
    await call('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});
    await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:theme}]});
    const targetUrl=origin+'/'+route;
    await call('Page.navigate',{url:targetUrl});
    // Readiness polling, then explicitly trigger all native-lazy images and await
    // successful decode; don't misclassify a 400ms unsettled currentSrc as broken.
    const ready=`location.href === ${JSON.stringify(targetUrl)} && document.readyState === "complete"`;
    for(let i=0;i<80;i++) {if(await evaluate(ready)) break;await new Promise(r=>setTimeout(r,50));}
    assert(await evaluate(ready), 'Navigation did not settle: '+targetUrl);
    await evaluate(`Promise.all([...document.images].map(img => {img.loading='eager';return img.decode().catch(()=>{});} ))`);
    // Failed local fixture card recovers asynchronously via real onerror.
    for(let i=0;i<80;i++) {if(await evaluate('[...document.images].every(img => img.complete && img.naturalWidth>0)')) break;await new Promise(r=>setTimeout(r,50));}
    const dom=await evaluate(`({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,theme:document.documentElement.dataset.theme||'light',images:[...document.images].map(img=>({src:img.getAttribute('src'),currentSrc:img.currentSrc,alt:img.alt,complete:img.complete,naturalWidth:img.naturalWidth,naturalHeight:img.naturalHeight,renderedWidth:img.getBoundingClientRect().width,renderedHeight:img.getBoundingClientRect().height})),timing:performance.getEntriesByType('resource').filter(r=>r.initiatorType==='img'||r.name.includes('/images/illustrations/')).map(r=>({name:r.name,encodedBodySize:r.encodedBodySize,decodedBodySize:r.decodedBodySize,transferSize:r.transferSize}))})`);
    await Promise.all(jobs);
    const images=[...resources.values()];
    assert(dom.images.length>0);
    for(const image of dom.images) {
      assert(image.complete && image.naturalWidth>0,JSON.stringify(image));
      assert(!image.currentSrc.includes('/images/categories/'),JSON.stringify(image));
      if(image.currentSrc.includes('/images/illustrations/')) assert.equal(image.alt,'Kuvituskuva – ei kuva uutisen tapahtumasta');
    }
    for(const image of images.filter(r=>r.url.includes('/images/illustrations/'))) {
      const file=join(root,new URL(image.url).pathname);
      const bytes=readFileSync(file);
      assert.equal(image.status,200);assert.equal(image.bodyBytes,bytes.length);assert.equal(image.sha256,hash(bytes));
    }
    assert.equal(dom.theme,theme,'Wrong rendered theme '+route);
    assert(dom.scrollWidth <= width,'Horizontal overflow '+route);
    if(Number.isFinite(relativeEpoch)) {
      const readTimes=`[...document.querySelectorAll('time[data-relative-date]')].map(t=>({absolute:t.firstChild.textContent,stamp:t.dateTime,label:t.querySelector('[data-relative-label]').textContent,hidden:t.querySelector('[data-relative-label]').hidden}))`;
      const before=await evaluate(readTimes);
      assert(before.length>0,'Missing progressive times '+route);
      assert(before.every(t=>t.absolute.includes('(Suomen aikaa)') && !t.hidden && t.label.includes('min sitten')));
      await evaluate(`window.__relativeClock += 3600000; window.dispatchEvent(new Event('pageshow'))`);
      const after=await evaluate(readTimes);
      assert.equal(after.length,before.length);
      for(let i=0;i<after.length;i++) {
        assert.equal(after[i].absolute,before[i].absolute);assert.equal(after[i].stamp,before[i].stamp);
        assert.equal(after[i].label,' · 1 t sitten');
      }
      dom.relativeElapsed={before,after};
    }
    pages.push({route,width,theme,htmlSha256:hash(readFileSync(join(root,route,'index.html'))),dom,resources:images,exceptions:exceptions.slice(errorStart)});
    writeFileSync(join(out,'browser-resources.json'),JSON.stringify({pages,blocked,exceptions},null,2));
    if(route==='categories/talous/'||route==='categories/ulkomaat/') {
      const shot=await call('Page.captureScreenshot',{format:'png'});
      writeFileSync(join(out,`${route.split('/')[1]}-${width}-${theme}.png`),Buffer.from(shot.data,'base64'));
    }
  }
  assert.equal(pages.length,routes.length*4);
  assert(exceptions.every(e=>(e.exception?.description||'').startsWith('TypeError: Failed to register a ServiceWorker')), 'Unexpected script exception');
  console.log(JSON.stringify({pages:pages.length,categories:7,widths:[390,1366],themes:['light','dark'],allImagesDecoded:true,allCategoryDisplayResponsesHashMatched:true,exceptions:exceptions.length,blocked:blocked.length}));
} finally {
  clearTimeout(timeout);
  await call('Browser.close').catch(()=>{});
  await new Promise(resolve=>{if(chrome.exitCode!==null)resolve();else chrome.once('exit',resolve);});
  server.close();rmSync(profile,{recursive:true,force:true});
}
