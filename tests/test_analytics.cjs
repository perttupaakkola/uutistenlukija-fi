const fs = require('fs'), vm = require('vm'), assert = require('assert');
const code=fs.readFileSync('cutover/analytics.js','utf8');
function run(origin,prefs,broken=false){
 let loads=0,reloads=0,stored=JSON.stringify(prefs);
 const ctx={window:{},location:{origin,reload(){reloads++;}},localStorage:{getItem(){if(broken)throw Error();return stored;},setItem(k,v){if(broken)throw Error();stored=v;}},document:{createElement(){return{};},head:{appendChild(){loads++;}}}};
 vm.runInNewContext(code,ctx);
 return {ctx,loads:()=>loads,reloads:()=>reloads};
}
for(const prefs of [null,{v:1,analytics:true},{v:2,analytics:false}])assert.equal(run('https://uutistenlukija.fi',prefs).loads(),0);
assert.equal(run('http://127.0.0.1:8000',{v:2,analytics:true}).loads(),0);
assert.equal(run('https://uutistenlukija.fi',null,true).loads(),0);
const yes=run('https://uutistenlukija.fi',{v:2,analytics:true});assert.equal(yes.loads(),1);
yes.ctx.window.newsAnalyticsConsent(true);assert.equal(yes.loads(),1);
yes.ctx.window.newsAnalyticsConsent(false);assert.equal(yes.reloads(),1);
console.log('PASS: missing, stale, denied, private, storage-failure, granted, duplicate grant and revocation consent cases; no network');
