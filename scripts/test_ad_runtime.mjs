#!/usr/bin/env node

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { createRuntime, evaluateAccess, normalizedConfig } = require('../static/js/ad-runtime.js');

function fakeElement(tagName) {
  return {
    tagName: tagName.toUpperCase(),
    children: [],
    style: {},
    attributes: {},
    listeners: {},
    appendChild(child) { this.children.push(child); child.parentNode = this; },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    addEventListener(name, handler) { this.listeners[name] = handler; },
  };
}

function fakeBrowser() {
  const inserted = [];
  const intent = {
    textContent: JSON.stringify({ position: 'in-article' }),
    parentNode: {
      insertBefore(node) { inserted.push(node); },
    },
  };
  const head = fakeElement('head');
  const document = {
    head,
    createElement: fakeElement,
    querySelectorAll(selector) {
      return selector === 'script[data-ul-ad-slot-intent]' ? [intent] : [];
    },
  };
  return { root: { document }, head, inserted };
}

const currentConfig = {
  enabled: true,
  providerId: 'ca-test-provider',
  consentRevision: 3,
  activationRevision: 3,
};

test('required dormant-ad regression matrix gates provider access', () => {
  const cases = [
    ['disabled+ID', { ...currentConfig, enabled: false }, { v: 3, advertising: true }, false, false],
    ['enabled+empty ID', { ...currentConfig, providerId: '' }, { v: 3, advertising: true }, false, false],
    ['enabled+ID+no consent', currentConfig, null, false, true],
    ['enabled+ID+old v2 true', currentConfig, { v: 2, advertising: true }, false, true],
    ['enabled+ID+current advertising false', currentConfig, { v: 3, advertising: false }, false, false],
    ['enabled+ID+current advertising true', currentConfig, { v: 3, advertising: true }, true, false],
  ];

  for (const [label, config, prefs, mayLoad, shouldReprompt] of cases) {
    const result = evaluateAccess(config, prefs);
    assert.equal(result.mayLoad, mayLoad, label);
    assert.equal(result.shouldReprompt, shouldReprompt, label);
  }
});

test('immutable activation floor blocks stale and invalid revisions and forces a fresh choice', () => {
  const blockedRevisions = [
    ['activation v2', { ...currentConfig, activationRevision: 2 }],
    ['activation zero', { ...currentConfig, activationRevision: 0 }],
    ['activation negative', { ...currentConfig, activationRevision: -1 }],
    ['activation invalid', { ...currentConfig, activationRevision: 'invalid' }],
    ['consent v2', { ...currentConfig, consentRevision: 2 }],
    ['consent zero', { ...currentConfig, consentRevision: 0 }],
    ['consent negative', { ...currentConfig, consentRevision: -1 }],
    ['consent invalid', { ...currentConfig, consentRevision: 'invalid' }],
  ];

  for (const [label, config] of blockedRevisions) {
    const result = evaluateAccess(config, { v: 2, advertising: true });
    assert.equal(result.providerReady, false, label);
    assert.equal(result.mayLoad, false, label);
    assert.equal(result.shouldReprompt, true, label);
  }
});

test('missing revisions use the same safe defaults as server and business gates', () => {
  const config = { enabled: true, providerId: 'ca-test-provider' };
  const normalized = normalizedConfig(config);
  assert.equal(normalized.configuredConsentRevision, 2);
  assert.equal(normalized.activationRevision, 3);
  assert.equal(normalized.consentRevision, 3);

  const decision = evaluateAccess(config, { v: 2, advertising: true });
  assert.equal(decision.providerReady, false);
  assert.equal(decision.mayLoad, false);
  assert.equal(decision.shouldReprompt, true);
});

test('blocked matrix states create no hints, provider script, slots, or initialization', () => {
  const cases = [
    [{ ...currentConfig, enabled: false }, { v: 3, advertising: true }],
    [{ ...currentConfig, providerId: '' }, { v: 3, advertising: true }],
    [currentConfig, null],
    [currentConfig, { v: 2, advertising: true }],
    [currentConfig, { v: 3, advertising: false }],
    [{ ...currentConfig, activationRevision: 2 }, { v: 3, advertising: true }],
    [{ ...currentConfig, activationRevision: 0 }, { v: 3, advertising: true }],
    [{ ...currentConfig, activationRevision: -1 }, { v: 3, advertising: true }],
    [{ ...currentConfig, activationRevision: 'invalid' }, { v: 3, advertising: true }],
    [{ ...currentConfig, consentRevision: 2 }, { v: 3, advertising: true }],
    [{ ...currentConfig, consentRevision: 'invalid' }, { v: 3, advertising: true }],
  ];

  for (const [config, prefs] of cases) {
    const browser = fakeBrowser();
    browser.root.adsbygoogle = [];
    createRuntime(browser.root, config).applyConsent(prefs);
    assert.equal(browser.head.children.length, 0);
    assert.equal(browser.inserted.length, 0);
    assert.equal(browser.root.adsbygoogle.length, 0);
  }
});

test('only current explicit advertising consent hydrates and initializes provider slots', () => {
  const browser = fakeBrowser();
  const decision = createRuntime(browser.root, currentConfig).applyConsent({
    v: 3,
    advertising: true,
  });

  assert.equal(decision.mayLoad, true);
  assert.equal(browser.head.children.filter(node => node.rel === 'preconnect').length, 1);
  assert.equal(browser.head.children.filter(node => node.rel === 'dns-prefetch').length, 1);
  const providerScripts = browser.head.children.filter(node =>
    node.tagName === 'SCRIPT' && node.src?.startsWith('https://pagead2.googlesyndication.com/'),
  );
  assert.equal(providerScripts.length, 1);
  assert.equal(browser.inserted.length, 1);
  assert.equal(browser.inserted[0].className, 'ad-slot ad-slot-in-article');
  assert.equal(browser.inserted[0].children[0].attributes['data-ad-client'], 'ca-test-provider');
  assert.equal(browser.root.adsbygoogle, undefined);

  providerScripts[0].listeners.load();
  assert.equal(browser.root.adsbygoogle.length, 1);
});
