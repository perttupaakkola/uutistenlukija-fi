// Offline mocked browser: no network, provider scripts or real analytics events.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const sourcePath = path.join(__dirname, '../layouts/partials/event-tracking.html');
const rendered = process.argv[2] ? fs.readFileSync(process.argv[2], 'utf8') : null;
let source = rendered ? [...rendered.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]).find(s => s.includes('visible_dwell_v2')) : fs.readFileSync(sourcePath, 'utf8').split('<script>')[1].split('</script>')[0];
assert(source, 'Rendered page includes the real tracking script');
if (!rendered) for (const [name, value] of Object.entries({_isPage:'true', _articleTitle:'"Fixture"', _articleCategory:'"uutiset"', _articleSlug:'"fixture"', _gaId:'"G-FIXTURE"'})) {
  source = source.replace(new RegExp('  var ' + name + ' = .*'), '  var ' + name + ' = ' + value + ';');
}
assert(!source.includes('{{'), 'All Hugo expressions must be rendered in fixture');
if (rendered) {
  const contextValue = name => JSON.parse(source.match(new RegExp('var ' + name + ' = (.*);'))[1]);
  assert.equal(contextValue('_gaId'), 'G-FIXTURE', 'Hugo must not double-encode the GA disable key');
  assert(!contextValue('_articleSlug').startsWith('\"'), 'Slug must not contain JSON wrapper quotes');
  assert(!contextValue('_articleCategory').startsWith('\"'), 'Category must not contain JSON wrapper quotes');
}
function browser(consented = false, viewTarget = null) {
  const events = [], observers = [], timers = [], listeners = {};
  let now = 0;
  const storageCalls = [];
  const localStorage = {getItem(key) {storageCalls.push(["read", key]); return null;},
    setItem(key, value) {storageCalls.push(["write", key, value]);}};
  const body = {scrollHeight: 100, style: {}, appendChild() {}};
  class Observer {
    constructor(callback) { this.callback = callback; this.targets = []; observers.push(this); }
    observe(el) { this.targets.push(el); }
    disconnect() { this.disconnected = true; }
    unobserve(el) { this.targets = this.targets.filter(target => target !== el); }
    show(show = true) { this.callback(this.targets.map(target => ({target, isIntersecting: show, intersectionRatio: show ? 1 : 0}))); }
  }
  const document = {readyState: 'complete', visibilityState: 'visible',
    querySelector: selector => selector === '[data-article-body]' && (!rendered || /<div[^>]*\sdata-article-body(?:[\s=>])/.test(rendered)) ? body : selector === '[data-monetization-view]' ? viewTarget : null,
    addEventListener: (name, callback) => (listeners[name] ||= []).push(callback),
    createElement: () => ({style: {}, attrs: {}, setAttribute(k,v) {this.attrs[k] = v;}, getAttribute(k) {return this.attrs[k];}, remove() {this.removed = true;}})};
  const window = {IntersectionObserver: Observer, getComputedStyle: () => ({position:'static'}),
    location: {hostname:'fixture.invalid', pathname:'/fixture/'},
    addEventListener() {}, setInterval: callback => timers.push(callback),
    __UL_AD_CONSENT__: {analytics: consented}, 'ga-disable-G-FIXTURE': !consented,
    gtag: (...args) => events.push(args)};
  vm.runInNewContext(source, {localStorage, window, document, IntersectionObserver: Observer, performance: {now: () => now}, URL}, {filename: sourcePath});
  return {events, observers, window, document, storageCalls,
    signalClick(el) { (listeners.click || []).forEach(fn => fn({target: {closest: selector =>
      (selector === "[data-monetization-signal]" && el.dataset.monetizationSignal) || (selector === "[data-track]" && el.dataset.track) ? el : null}})); },
    tick(seconds) { for (let i=0; i<seconds*2; i++) {now += 500; timers.forEach(fn => fn());} },
    consent(value) {window.__UL_AD_CONSENT__.analytics = value; window['ga-disable-G-FIXTURE'] = !value;},
    visibility(value) {document.visibilityState = value; (listeners.visibilitychange || []).forEach(fn => fn());},
    clicks() { const el = {dataset: {track:'fixture_click'}, href:'https://fixture.invalid/', textContent:'Fixture'}; (listeners.click || []).forEach(fn => fn({target: {closest: selector => selector === '[data-track]' ? el : null}})); },
    reads() {return events.filter(e => e[1] === 'article_read');}
  };
}
const delayed = browser();
delayed.tick(40); delayed.clicks();
assert.equal(delayed.observers.length, 0, 'No observer before consent even with gtag present');
assert.equal(delayed.events.length, 0, 'No pre-consent event replay queue');
delayed.consent(true); delayed.tick(1);
assert.equal(delayed.events.length, 0, 'Grant does not replay pre-consent events');
delayed.observers.at(-1).show(); delayed.tick(14);
assert.equal(delayed.reads().length, 0, 'Visible short article is not immediately read');
delayed.tick(2); assert.equal(delayed.reads().length, 1);
delayed.tick(30); assert.equal(delayed.reads().length, 1, 'At most one read per page');
const hidden = browser(true);
hidden.observers[0].show(); hidden.tick(8);
hidden.visibility('hidden'); hidden.tick(60);
assert.equal(hidden.reads().length, 0, 'Hidden time does not count');
hidden.visibility('visible'); hidden.tick(9); assert.equal(hidden.reads().length, 1);
const revoked = browser(true);
revoked.observers[0].show(); revoked.tick(10); revoked.consent(false); revoked.clicks(); revoked.tick(20);
assert.equal(revoked.reads().length, 0);
assert(revoked.observers[0].disconnected, 'Revocation removes observer and dwell');
revoked.consent(true); revoked.tick(1); revoked.observers.at(-1).show(); revoked.tick(6);
assert.equal(revoked.reads().length, 0, 'Regrant cannot reuse earlier dwell');
revoked.tick(10); assert.equal(revoked.reads().length, 1);
const unseen = browser(true); unseen.observers[0].show(false); unseen.tick(40);
assert.equal(unseen.events.length, 0, 'Offscreen article accumulates no engagement');
const qa = browser(true); qa.window.__UL_ANALYTICS_TRAFFIC_TYPE__ = 'qa'; qa.clicks();
assert.equal(qa.events[0][2].traffic_type, 'qa');
qa.window.__UL_ANALYTICS_TRAFFIC_TYPE__ = 'internal'; qa.clicks();
assert.equal(qa.events[1][2].traffic_type, 'internal');
qa.window.__UL_ANALYTICS_TRAFFIC_TYPE__ = 'bot'; qa.clicks();
assert.equal(qa.events[2][2].traffic_type, 'unclassified');
console.log('PASS: delayed/prior consent, no replay, dwell, visibility, revoke/regrant, one read, explicit QA/internal classification');

// Exercise attributes from the actual active holiday CTA, not a generic click.
const holidayMarkup = fs.readFileSync(path.join(__dirname, '../layouts/partials/holiday-hours-reminder-cta.html'), 'utf8');
const holiday = {dataset: {
  track: holidayMarkup.match(/data-track="([^"]+)"/)[1],
  placement: holidayMarkup.match(/\$placement := "([^"]+)"/)[1]
}, href:'https://fixture.invalid/tilaa/pyhapaivien-kaupat-auki/', textContent:'Tilaa muistutus'};
const signal = browser();
signal.signalClick(holiday);
assert.equal(signal.storageCalls.length, 0, 'Actual signal target must not read or write local history before consent');
assert.equal(signal.events.length, 0);
signal.consent(true); signal.tick(1);
assert.equal(signal.events.length, 0, 'No replay of denied signal');
signal.signalClick(holiday);
assert.deepEqual(signal.events.map(e => e[1]), ['holiday_hours_guide_click']);
assert.equal(signal.events[0][2].placement, 'paasiaisopas-kaupat-auki-article');
assert.equal(signal.storageCalls.length, 0, 'Removed storage stays unused after consent');
signal.consent(false); signal.signalClick(holiday); signal.tick(2);
assert.equal(signal.events.length, 1);
signal.consent(true); signal.tick(1);
assert.equal(signal.events.length, 1, 'Regrant does not replay denied signals');
signal.signalClick(holiday);
assert.equal(signal.events.length, 2);
assert.equal(signal.storageCalls.length, 0);
signal.window['ga-disable-G-FIXTURE'] = true;
signal.signalClick(holiday);
assert.equal(signal.events.length, 2, 'GA disable also gates actual signals despite consent state');
signal.window['ga-disable-G-FIXTURE'] = false;
delete signal.window.gtag;
signal.signalClick(holiday);
assert.equal(signal.events.length, 2, 'Missing GA cannot collect or queue signals');
assert.equal(signal.storageCalls.length, 0);
const sponsor = browser(true);
sponsor.signalClick({dataset:{monetizationSignal:'founding_sponsor_contact_click', placement:'fixture'}, textContent:''});
assert(sponsor.events.some(e => e[1] === 'founding_sponsor_contact_click'), 'Existing named event stays available');
// No source markup consumes this dormant view path; a legacy target must not revive it.
const view = browser(false, {dataset:{monetizationView:'founding_sponsor_cta_view', placement:'fixture'}});
assert.equal(view.observers.length, 0, 'Even a legacy view target creates no pre-consent observer');
view.consent(true); view.tick(2);
assert.equal(view.observers.length, 1, 'Only the article observer remains');
assert.equal(view.events.length, 0);
assert.equal(view.storageCalls.length, 0);
console.log('PASS: actual holiday signal, no persistent storage, no dormant view observer, named event compatibility, revoke/regrant');
