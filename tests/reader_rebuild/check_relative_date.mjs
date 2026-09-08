// Execute exact Hugo-rendered script, with only clock/DOM boundaries controlled.
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
const html=readFileSync(0,'utf8');
const scripts=[...html.matchAll(/<script id="relative-date-enhancement">([\s\S]*?)<\/script>/g)];
assert.equal(scripts.length,1);
const source=scripts[0][1]; // Deliberately no source rewriting or replacement.
const times=[...html.matchAll(/<time datetime="([^"]+)" data-relative-date>([\s\S]*?)<\/time>/g)];
assert.equal(times.length,1);
const [_,encodedStamp,markup]=times[0];
// HTML attribute entity decoding, as the browser DOM does; script stays raw.
const stamp=encodedStamp.replace(/&#(\d+);/g,(_,n)=>String.fromCodePoint(Number(n)));
assert.equal(stamp,'2026-01-01T14:00:00+02:00'); // published_at, not Date/updated_at
assert.match(markup,/1\.1\.2026 klo 14:00 \(Suomen aikaa\)/);
assert.match(markup,/<span data-relative-label hidden><\/span>/);
assert(!markup.includes('sitten')); // no-JS HTML has only absolute age.
const published=Date.parse(stamp);
let checks=0;
for(const readyState of ['loading','complete']) {
  let now=published-1, ticks=[], events={}, windowEvents={};
  const label={hidden:true,textContent:''};
  const invalidLabel={hidden:true,textContent:''};
  const element={getAttribute:key=>{assert.equal(key,'datetime');return stamp;},querySelector:()=>label};
  const invalid={getAttribute:()=> 'invalid',querySelector:()=>invalidLabel};
  const document={readyState,hidden:false,querySelectorAll:selector=>{assert.equal(selector,'time[data-relative-date]');return [element,invalid];},addEventListener:(name,fn)=>events[name]=fn};
  const window={setInterval:(fn,ms)=>{assert.equal(ms,30000);ticks.push(fn);},addEventListener:(name,fn)=>windowEvents[name]=fn};
  vm.runInNewContext(source,{document,window,Date:{now:()=>now,parse:Date.parse}});
  if(readyState==='loading') {assert.equal(ticks.length,0);events.DOMContentLoaded();}
  assert.equal(ticks.length,1);
  for(const [elapsed,text] of [[-1,''],[0,' · alle minuutti sitten'],[60000,' · 1 min sitten'],[120000,' · 2 min sitten'],[3600000,' · 1 t sitten'],[86400000,' · 1 pv sitten'],[604800000,'']]) {
    now=published+elapsed;ticks[0]();
    assert.equal(label.textContent,text);assert.equal(label.hidden,!text);
    assert.equal(invalidLabel.hidden,true);assert.equal(invalidLabel.textContent,'');checks++;
  }
  // Resume after background/BFCache elapsed time, including clock correction.
  now=published+180000;events.visibilitychange();assert.equal(label.textContent,' · 3 min sitten');
  now=published+240000;windowEvents.pageshow();assert.equal(label.textContent,' · 4 min sitten');
  now=published-3600000;ticks[0]();assert.equal(label.hidden,true);
}
console.log(JSON.stringify({elapsedBoundaryChecks:checks,startupModes:2,backgroundAndBFCache:true,invalidAndFutureFallback:true,absoluteMarkupPreserved:true,renderedScriptSHA256:createHash('sha256').update(source).digest('hex')}));
