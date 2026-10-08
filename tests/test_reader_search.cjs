"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[2] || "static/search.js", "utf8");

class Element {
  constructor(tag, id) {
    this.tagName = tag.toUpperCase();
    this.id = id || "";
    this.attrs = {};
    this.children = [];
    this.handlers = {};
    this.className = "";
    this.textContent = "";
    this.value = "";
    Object.defineProperty(this, "innerHTML", {
      set() { throw new Error("search rendering must not use innerHTML"); },
    });
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null; }
  addEventListener(type, handler) { (this.handlers[type] = this.handlers[type] || []).push(handler); }
  appendChild(child) { this.children.push(child); return child; }
  removeChild(child) { this.children.splice(this.children.indexOf(child), 1); return child; }
  get firstChild() { return this.children[0] || null; }
  querySelector(selector) {
    if (selector !== 'input[name="q"]') return null;
    const stack = this.children.slice();
    while (stack.length) {
      const item = stack.shift();
      if (item.tagName === "INPUT" && item.getAttribute("name") === "q") return item;
      stack.push(...(item.children || []));
    }
    return null;
  }
}

function textTree(node) {
  return (node.textContent || "") + (node.children || []).map(textTree).join("");
}

function descendants(node, tag) {
  const found = [];
  (node.children || []).forEach((child) => {
    if (child.tagName === tag.toUpperCase()) found.push(child);
    found.push(...descendants(child, tag));
  });
  return found;
}

async function run(search, payload, options) {
  options = options || {};
  const elements = {};
  const createdTags = [];
  const assigned = [];
  const fetchCalls = [];
  function register(tag, id) {
    const element = new Element(tag, id);
    elements[id] = element;
    return element;
  }
  function form(id, inputId) {
    const node = register("form", id);
    node.setAttribute("action", "https://www.google.com/search");
    node.setAttribute("data-first-party-action", "/haku/");
    const input = register("input", inputId);
    input.setAttribute("name", "q");
    node.appendChild(input);
    return node;
  }
  const headerForm = form("header-search-form", "header-search-input");
  const pageForm = form("search-page-form", "search-input");
  const count = register("p", "search-count");
  const list = register("ol", "search-results");
  const document = {
    querySelectorAll(selector) {
      return selector === "form[data-first-party-action]" ? [headerForm, pageForm] : [];
    },
    getElementById(id) { return elements[id] || null; },
    createElement(tag) { createdTags.push(tag.toLowerCase()); return new Element(tag); },
    createTextNode(value) { const node = new Element("#text"); node.textContent = String(value); return node; },
  };
  const window = {
    URL,
    URLSearchParams,
    location: {
      origin: "https://uutistenlukija.fi",
      search,
      assign(value) { assigned.push(value); },
    },
    fetch(path, init) {
      fetchCalls.push({ path, init });
      if (options.reject) return Promise.reject(new Error("offline"));
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
    },
  };
  vm.runInNewContext(source, { window, document, Intl, Date, Number, Object, Array, String,
                               encodeURIComponent, Error });
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  return { elements, count, list, createdTags, assigned, fetchCalls, headerForm, pageForm };
}

(async function () {
  const empty = await run("", []);
  assert.strictEqual(empty.count.textContent, "Kirjoita hakusana.");
  assert.strictEqual(empty.fetchCalls.length, 0);
  empty.elements["search-input"].value = "  syys loma  ";
  let prevented = false;
  empty.pageForm.handlers.submit[0]({ preventDefault() { prevented = true; } });
  assert.strictEqual(prevented, true);
  assert.deepStrictEqual(empty.assigned, ["/haku/?q=syys%20loma"]);
  assert.strictEqual(empty.pageForm.getAttribute("action"), "https://www.google.com/search");

  const published = "2026-10-07T08:15:30Z";
  const payload = [
    { title: "Päiväkoti ja syysloma <img onerror=alert(1)>", summary: "Turvallinen ohjelma.",
      path: "/uutiset/uusin-0123456789ab/", published },
    { title: "Päiväkoti", summary: "Vain yksi hakusana.",
      path: "/uutiset/osuma-vain-yhteen-0123456789ab/", published: "2026-10-07T09:15:30Z" },
    { title: "Päiväkoti ja ohjelma", summary: "Syysloma alkaa myöhemmin.",
      path: "/uutiset/vanhempi-0123456789ab/", published: "2025-10-07T08:15:30Z" },
    { title: "Päiväkodin syysloma", summary: "Pois", path: "javascript:alert(1)", published },
    { title: "Päiväkodin syysloma", summary: "Pois", path: "https://evil.invalid/x", published },
    { title: "Päiväkodin syysloma", summary: "Pois", path: "/uutiset/debug-0123456789ab/",
      published, debug: "/private" },
  ];
  const matches = await run("?q=PAIVAKOTI%20syysloma", payload);
  assert.strictEqual(matches.fetchCalls.length, 1);
  assert.strictEqual(matches.fetchCalls[0].path, "/assets/search-index.json");
  assert.strictEqual(matches.fetchCalls[0].init.credentials, "same-origin");
  assert.strictEqual(matches.count.textContent, "2 tulosta.");
  assert.strictEqual(matches.list.children.length, 2);
  const links = descendants(matches.list, "a");
  assert.deepStrictEqual(links.map((link) => link.getAttribute("href")),
                         ["/uutiset/uusin-0123456789ab/", "/uutiset/vanhempi-0123456789ab/"]);
  assert(textTree(matches.list).includes("<img onerror=alert(1)>"));
  assert(!matches.createdTags.includes("img"));
  const times = descendants(matches.list, "time");
  assert.strictEqual(times[0].getAttribute("datetime"), published);

  const none = await run("?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E", payload);
  assert.strictEqual(none.count.textContent, "Ei tuloksia.");
  assert.strictEqual(none.list.children.length, 2);
  assert.deepStrictEqual(descendants(none.list, "a").map(link => link.getAttribute("href")), ["/oppaat/"]);
  assert(textTree(none.list).includes("Katso myös arjen oppaat ja viranomaisohjeet."));
  assert(textTree(none.list).includes("<script>alert(1)</script>"));
  assert(!none.createdTags.includes("script"));

  const many = [];
  for (let index = 0; index < 25; index += 1) {
    many.push({ title: "Syysloma ohjelma " + index, summary: "Päiväkoti",
      path: "/uutiset/tulos-" + String(index).padStart(2, "0") + "-0123456789ab/",
      published: "2026-09-" + String(index + 1).padStart(2, "0") + "T08:00:00Z" });
  }
  const bounded = await run("?q=syysloma", many);
  assert.strictEqual(bounded.list.children.length, 20);

  const failed = await run("?q=syysloma", [], { reject: true });
  assert.strictEqual(failed.count.textContent, "Haku ei ole juuri nyt käytettävissä.");
  assert.strictEqual(descendants(failed.list, "a").length, 0);
  assert.strictEqual(descendants(empty.list, "a").length, 0);

  process.stdout.write("PASS: empty, Enter/Back navigation, safe Finnish multiword, malformed index, no-hit, cap and fallback cases\n");
})().catch((error) => {
  process.stderr.write(error.stack + "\n");
  process.exitCode = 1;
});
