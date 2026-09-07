// DevTools pipe only: exact viewport, local sanitized fixture, no provider network.
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';
const [url, screenshot, profile, widthText, heightText] = process.argv.slice(2);
if (!url.startsWith('file:///home/pertt/outputs/news-rebuild-20260907/scratch/reader/')) throw Error('Fixture-only URL required');
const width = Number(widthText), height = Number(heightText);
const chrome = spawn('google-chrome', ['--headless', '--no-sandbox', '--disable-gpu', '--disable-background-networking', '--disable-component-update', '--no-first-run', '--no-default-browser-check', '--disable-sync', '--host-resolver-rules=MAP * ~NOTFOUND', '--remote-debugging-pipe', '--allow-file-access-from-files', '--user-data-dir='+profile], {stdio:['ignore','ignore','ignore','pipe','pipe']});
let sequence=0, buffer=''; const pending = new Map();
chrome.stdio[4].on('data', data => {
  buffer += data.toString();
  while (buffer.includes('\0')) {
    const end=buffer.indexOf('\0'), message=JSON.parse(buffer.slice(0,end)); buffer=buffer.slice(end+1);
    if (pending.has(message.id)) { const p=pending.get(message.id);pending.delete(message.id);message.error?p.reject(Error(JSON.stringify(message.error))):p.resolve(message.result); }
  }
});
function call(method, params={}, sessionId) {return new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});chrome.stdio[3].write(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})})+'\0');});}
const timeout=setTimeout(()=>{chrome.kill();process.exitCode=1;},20000);
try {
  const {targetId}=await call('Target.createTarget',{url:'about:blank'});
  const {sessionId}=await call('Target.attachToTarget',{targetId,flatten:true});
  await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false},sessionId);
  await call('Page.enable',{},sessionId);
  await call('Page.navigate',{url},sessionId);
  await new Promise(resolve=>setTimeout(resolve,600));
  const {result}=await call('Runtime.evaluate',{expression:'JSON.stringify({viewport:innerWidth,document:document.documentElement.scrollWidth,lead:!!document.querySelector(".portal-lead")})',returnByValue:true},sessionId);
  const shot=await call('Page.captureScreenshot',{format:'png'},sessionId);
  writeFileSync(screenshot,Buffer.from(shot.data,'base64'));
  console.log(result.value);
} finally { clearTimeout(timeout); await call('Browser.close').catch(()=>{}); }
