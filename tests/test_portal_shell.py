"""Shell and asset-port checks for the portal shell task.

These cover the ported masthead, the byte-identical imported assets, the
public/private markers, the compatibility-sheet plumbing and the real behaviour of
static/portal.js (executed under node against a stub DOM, so the assertions are
about what the script does, not what it looks like). Brand-image and text-only
gates live in the older suites and are deliberately not duplicated here.
"""
import json
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

import test_release_v2 as base
from news_mvp import site
from news_mvp.store import database


FOOTER_RE = re.compile(r"<footer\b.*?</footer\s*>", re.I | re.S)
NAV_RE = re.compile(r'<nav class="main-nav".*?</nav>', re.I | re.S)
HREF_RE = re.compile(r'href="([^"]+)"')
SHEET_RE = re.compile(r'<link rel="stylesheet" href="([^"]+)">')
SCRIPT_RE = re.compile(r"<script\b[^>]*>", re.I)
TAG_CLASS_RE = re.compile(r'class="([^"]*)"')
ATTR_RE = re.compile(r'([a-zA-Z][\w:-]*)\s*=\s*"([^"]*)"')
SHEETS = ("style.css", "homepage-polish.css", "article.css", "category.css",
          "category-hero.css", "empty-state.css", "search.css", "portal-overhaul.css")
NAV_HREFS = ["/", "/categories/kotimaa/", "/categories/ulkomaat/", "/categories/talous/",
             "/categories/teknologia/", "/categories/urheilu/", "/categories/kulttuuri/",
             "/categories/tiede/", "/oppaat/", "/tuoreimmat/"]
# Theme-native footer structure: the reference's own class names, nothing invented.
FOOTER_CLASSES = {"site-footer", "container", "site-footer-grid", "site-footer-col",
                  "site-footer-brand-col", "site-footer-brand", "site-footer-slogan",
                  "site-footer-links", "site-footer-copyright"}
# The palette the ported theme actually uses; the compatibility sheets must not
# reintroduce the retired brown/green values.
RETIRED_HEXES = {"#fffdf6", "#17302c", "#a34422", "#f6f3eb", "#59645d", "#d7d8cd",
                 "#183f31", "#fffcf4", "#f3f0e6", "#fff4dc"}
# Shell controls that must keep a 44px touch target at both widths.
TAP_SELECTORS = (".portal-icon-button", ".hamburger-btn", ".theme-toggle-btn",
                 ".search-toggle-btn", ".portal-action", ".main-nav a", ".site-search__submit",
                 ".site-footer-consent-button", ".site-footer-links li a",
                 ".consent-settings", "dialog button")
READABLE_PROPERTIES = {"scroll-margin-top", "overflow-wrap", "hyphens", "-webkit-hyphens"}


def css_rules(text):
    """Yield (selector, declarations, media-preludes) for one stylesheet.

    A deliberately small scan: enough to inspect real declarations and their
    enclosing @media context without adding a CSS dependency.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    rules = []
    stack = []
    buf = ""
    for char in text:
        if char == "{":
            stack.append(buf.strip())
            buf = ""
        elif char == "}":
            if stack and not stack[-1].startswith("@") and buf.strip():
                _flush(rule_selector=stack[-1], raw=buf, stack=stack, rules=rules)
            if stack:
                stack.pop()
            buf = ""
        elif char == ";":
            if stack and not stack[-1].startswith("@") and buf.strip():
                _flush(rule_selector=stack[-1], raw=buf, stack=stack, rules=rules)
            buf = ""
        else:
            buf += char
    return rules


def _flush(rule_selector, raw, stack, rules):
    declarations = {}
    for declaration in raw.split(";"):
        if ":" in declaration:
            prop, value = declaration.split(":", 1)
            declarations[prop.strip().lower()] = value.strip()
    if declarations:
        media = tuple(item for item in stack[:-1] if item.startswith("@"))
        rules.append((rule_selector, declarations, media))


def declarations_for(rules, selector):
    return [decls for rule_selector, decls, _media in rules if selector in rule_selector.split(",")]


def tap_pixels(value):
    match = re.match(r"(\d+)px", value or "")
    return int(match.group(1)) if match else None


PORTAL_JS_DRIVER = r'''
"use strict";
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const scenario = JSON.parse(process.argv[3]);

function makeElement(id, initialClasses) {
  const attrs = {};
  const classes = new Set(initialClasses || []);
  const el = {
    id: id,
    style: {},
    focused: 0,
    handlers: {},
    setAttribute(name, value) { attrs[name] = String(value); },
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(attrs, name) ? attrs[name] : null;
    },
    addEventListener(type, handler) { (el.handlers[type] = el.handlers[type] || []).push(handler); },
    focus() { el.focused += 1; },
    classList: {
      contains(name) { return classes.has(name); },
      add(name) { classes.add(name); },
      remove(name) { classes.delete(name); },
      toggle(name, force) {
        const on = force === undefined ? !classes.has(name) : !!force;
        if (on) { classes.add(name); } else { classes.delete(name); }
        return on;
      },
    },
    _classes: classes,
  };
  return el;
}

const elements = {
  "theme-toggle": makeElement("theme-toggle"),
  "theme-toggle-menu": makeElement("theme-toggle-menu"),
  "header-search": makeElement("header-search", ["site-search--collapsed"]),
  "header-search-toggle": makeElement("header-search-toggle"),
  "header-search-input": makeElement("header-search-input"),
  hamburger: makeElement("hamburger"),
  "main-nav-menu": makeElement("main-nav-menu", scenario.navInitiallyOpen ? ["nav-open"] : []),
};
const rootElement = makeElement("root");
const documentHandlers = {};
const store = {};
if (scenario.stored) store["uutistenlukija-theme"] = scenario.stored;
const storage = {
  getItem(key) { return Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null; },
  setItem(key, value) { store[key] = String(value); },
};

const sandbox = {
  window: {
    localStorage: storage,
    matchMedia(query) { return { matches: scenario.systemDark === true, media: query }; },
  },
  document: {
    documentElement: rootElement,
    getElementById(id) { return elements[id] || null; },
    addEventListener(type, handler) { (documentHandlers[type] = documentHandlers[type] || []).push(handler); },
  },
};
vm.createContext(sandbox);
vm.runInContext(source, sandbox);

const toggle = elements["theme-toggle"];
const menuToggle = elements["theme-toggle-menu"];
const search = elements["header-search"];
const searchToggle = elements["header-search-toggle"];
const searchInput = elements["header-search-input"];
const hamburger = elements.hamburger;
const nav = elements["main-nav-menu"];
if (scenario.clickToggle) (toggle.handlers.click || []).forEach((handler) => handler());
if (scenario.clickMenuTheme) (menuToggle.handlers.click || []).forEach((handler) => handler());
if (scenario.clickMenu) (hamburger.handlers.click || []).forEach((handler) => handler());
if (scenario.clickSearch) (searchToggle.handlers.click || []).forEach((handler) => handler());
if (scenario.escape) (documentHandlers.keydown || []).forEach((handler) => handler({ key: "Escape" }));

process.stdout.write(JSON.stringify({
  theme: rootElement.getAttribute("data-theme"),
  colorScheme: rootElement.style.colorScheme || null,
  pressed: toggle.getAttribute("aria-pressed"),
  menuPressed: menuToggle.getAttribute("aria-pressed"),
  navOpen: nav._classes.has("nav-open"),
  navExpanded: hamburger.getAttribute("aria-expanded"),
  menuFocused: hamburger.focused,
  searchCollapsed: search._classes.has("site-search--collapsed"),
  searchExpanded: searchToggle.getAttribute("aria-expanded"),
  searchFocused: searchInput.focused,
  searchToggleFocused: searchToggle.focused,
  stored: storage.getItem("uutistenlukija-theme"),
}));
'''


class PortalShell(unittest.TestCase):
    def setUp(self):
        case = base.ReleaseV2("source_fetch")
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.base = case
        self.state = case.state
        self.job = case.ready()

    def _site_root(self, output):
        pages = [path.parent for path in output.rglob("index.html")]
        self.assertTrue(pages, f"no rendered index.html under {output}")
        return min(pages, key=lambda path: (len(path.parts), str(path)))

    def _page(self, output, job):
        path = self._site_root(output) / site.article_path(job).lstrip("/")
        return path if path.suffix else path / "index.html"

    @staticmethod
    def _attrs(tag):
        return {key.lower(): value for key, value in ATTR_RE.findall(tag)}

    def _footer_classes(self, text):
        footer = FOOTER_RE.search(text)
        self.assertIsNotNone(footer, "footer is missing")
        classes = set()
        for tag in re.findall(r"<[a-z][^>]*>", footer.group(0), re.I):
            for value in TAG_CLASS_RE.findall(tag):
                classes.update(value.split())
        return footer.group(0), classes

    def _run_portal_js(self, scenario):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required to exercise static/portal.js")
        directory = Path(tempfile.mkdtemp(prefix="portal-js-"))
        self.addCleanup(shutil.rmtree, directory, True)
        driver = directory / "driver.js"
        driver.write_text(PORTAL_JS_DRIVER, encoding="utf-8")
        completed = subprocess.run(
            [node, str(driver), str(site.ROOT / "static/portal.js"), json.dumps(scenario)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def _render_public(self):
        output = self.base.root / "portal-public"
        output.mkdir()
        with database(self.state) as store:
            site.render_site(store, output, self.state, public=True)
        return output

    def _render_private(self, name):
        output = self.base.root / name
        output.mkdir()
        with database(self.state) as store:
            site.render_site(store, output, self.state, public=False)
        return output

    def test_page_links_original_sheets_then_compatibility_layer(self):
        public = site.page("Uusimmat uutiset", "<p>x</p>", "/")
        self.assertEqual(
            SHEET_RE.findall(public),
            [f"/mvp-assets/css/{name}" for name in SHEETS]
            + ["/mvp-assets/style.css", "/mvp-assets/style-readability.css"],
        )
        private = site.page("Luonnos", "<p>x</p>", readability_present=False)
        self.assertEqual(
            SHEET_RE.findall(private),
            [f"/assets/css/{name}" for name in SHEETS] + ["/assets/style.css"],
        )

    def test_public_shell_semantics(self):
        home = (self._site_root(self._render_public()) / "index.html").read_text(encoding="utf-8")
        self.assertIn('<header class="site-header" role="banner">', home)
        self.assertIn('class="portal-masthead"', home)
        self.assertIn(
            '<img src="/mvp-assets/images/logo.png" alt="Uutistenlukija" class="portal-logo__image"'
            ' loading="eager" decoding="async" width="977" height="191">',
            home,
        )
        # The one search is Google's, explicitly labelled and site-scoped.
        self.assertIn('action="https://www.google.com/search"', home)
        self.assertIn('name="sitesearch" value="uutistenlukija.fi"', home)
        self.assertIn("Hae uutisia Googlesta", home)
        self.assertIn("Haku avautuu Googlen omalla sivulla.", home)
        # Weather is stated as unavailable instead of showing an invented reading.
        self.assertIn("Sääennuste ei ole nyt saatavilla", home)
        self.assertNotIn("data-weather-widget", home)
        self.assertIn('class="portal-weather" href="/#saa"', home)
        self.assertIn('id="saa"', home)
        self.assertIn('Sääennuste ei ole nyt saatavilla.', home)
        self.assertIn('id="markkinat"', home)
        self.assertIn('Valuuttakurssit eivät ole nyt saatavilla.', home)
        # Theme toggle and mobile menu button.
        self.assertIn('id="theme-toggle"', home)
        self.assertIn('id="theme-toggle-menu"', home)
        self.assertIn('class="portal-search site-search site-search--collapsed"', home)
        self.assertIn('aria-controls="header-search-form"', home)
        self.assertIn('aria-describedby="header-search-note"', home)
        self.assertIn('id="hamburger"', home)
        self.assertIn('aria-controls="main-nav-menu"', home)
        nav = NAV_RE.search(home)
        self.assertIsNotNone(nav, "masthead nav is missing")
        self.assertEqual(HREF_RE.findall(nav.group(0)), NAV_HREFS)
        # Footer uses the theme's own classes and keeps the three truthful destinations.
        footer, classes = self._footer_classes(home)
        self.assertTrue(FOOTER_CLASSES <= classes, f"missing footer classes: {FOOTER_CLASSES - classes}")
        self.assertFalse(
            [name for name in classes if name.startswith("site-footer__")],
            f"invented footer classes: {classes}",
        )
        for generic in ("grid", "col"):
            self.assertNotIn(generic, classes, f"generic {generic!r} override leaked into the footer")
        self.assertIn('role="contentinfo"', footer)
        for required in ("/tietosuoja/", "/lahteet/", "/rss.xml"):
            self.assertIn(required, footer)

    def test_consent_dialog_has_a_compact_accessible_choice_layout(self):
        fragment = (site.ROOT / "static/consent.html").read_text(encoding="utf-8")
        self.assertIn('aria-describedby="consent-description"', fragment)
        self.assertIn('tabindex="-1"', fragment)
        self.assertIn('class="consent-dialog__actions"', fragment)
        self.assertIn('class="consent-dialog__privacy"', fragment)
        self.assertIn('aria-label="Sulje evästeasetukset"', fragment)
        self.assertLess(fragment.index('id="consent-accept"'), fragment.index('id="consent-reject"'))
        script = (site.ROOT / "static/consent.js").read_text(encoding="utf-8")
        self.assertIn("box.focus({ preventScroll: true })", script)
        styles = (site.ROOT / "static/style.css").read_text(encoding="utf-8")
        self.assertIn(".consent-dialog__actions{display:grid", styles)
        self.assertIn("@media(max-width:520px)", styles)

    def test_imported_assets_are_copied_byte_for_byte(self):
        root = self._site_root(self._render_public())
        static = site.ROOT / "static"
        logo = (root / "mvp-assets/images/logo.png").read_bytes()
        self.assertEqual(logo, (static / "images/logo.png").read_bytes())
        self.assertEqual(struct.unpack(">II", logo[16:24]), (977, 191))
        for name in SHEETS:
            self.assertEqual(
                (root / "mvp-assets/css" / name).read_bytes(),
                (static / "css" / name).read_bytes(),
                name,
            )
        self.assertEqual(
            (root / "mvp-assets/style-readability.css").read_bytes(),
            (static / "style-readability.css").read_bytes(),
        )
        # The root sheet IS static/style.css now, byte for byte: the theme's own
        # tokens live in one place, and the retired style-compat.css is gone.
        self.assertEqual(
            (root / "mvp-assets/style.css").read_bytes(),
            (static / "style.css").read_bytes(),
        )
        self.assertEqual(
            (root / "mvp-assets/portal.js").read_bytes(),
            (static / "portal.js").read_bytes(),
        )
        self.assertFalse((static / "style-compat.css").exists())
        self.assertFalse((root / "mvp-assets/style-compat.css").exists())
        # Nested image directories survive, so relative CSS URLs keep resolving.
        self.assertTrue((root / "mvp-assets/images/categories").is_dir())
        self.assertTrue((root / "mvp-assets/images/illustrations").is_dir())

    def test_compatibility_sheet_is_theme_native_and_keeps_controls_tappable(self):
        rules = css_rules((site.ROOT / "static/style.css").read_text(encoding="utf-8"))
        self.assertTrue(rules, "compatibility sheet has no rules")
        # No retired brown/green values, and colours resolve through theme tokens.
        retired = [
            (selector, prop, value)
            for selector, decls, _media in rules
            for prop, value in decls.items()
            if prop in {"color", "background", "background-color", "border-color"}
            for hex_value in re.findall(r"#[0-9a-fA-F]{3,6}", value)
            if hex_value.lower() in RETIRED_HEXES
        ]
        self.assertEqual(retired, [], f"retired palette values survived: {retired}")
        token_values = [
            value for _selector, decls, _media in rules
            for value in decls.values() if "var(--portal-" in value or "var(--bg" in value or "var(--text" in value
        ]
        self.assertTrue(token_values, "compatibility sheet does not use the theme tokens")
        # A focused skip link must clear the sticky header (z-index 200/50 in the theme).
        skip_rules = [
            decls for selector, decls, _media in rules
            if any(".skip" in part for part in selector.split(",") if ":focus" in part)
        ]
        self.assertTrue(skip_rules, "no focused skip-link rule")
        self.assertTrue(
            any(int(re.sub(r"\D", "", decls.get("z-index", "0")) or 0) >= 1000 for decls in skip_rules),
            f"skip-link focus does not clear the sticky header: {skip_rules}",
        )
        # Mobile search remains the theme's native collapsed control; the compatibility
        # layer must not add a second masthead row or force the form open.
        compat = (site.ROOT / "static/style.css").read_text(encoding="utf-8")
        self.assertNotIn("grid-template-areas", compat)
        self.assertNotIn(".site-search__form{display:flex !important", compat)
        self.assertNotIn("site-search:not(.site-search--collapsed)", compat)
        # Every shell control declares a 44px target outside any media query.
        for selector in TAP_SELECTORS:
            candidates = [
                pixels
                for rule_selector, decls, media in rules
                if selector in rule_selector.split(",") and not media
                for prop, value in decls.items()
                if prop in {"min-height", "height"}
                for pixels in [tap_pixels(value)]
                if pixels is not None
            ]
            self.assertTrue(
                any(pixels >= 44 for pixels in candidates),
                f"{selector} has no 44px target: {candidates}",
            )

    def test_readability_sheet_is_accessibility_rules_only(self):
        rules = css_rules((site.ROOT / "static/style-readability.css").read_text(encoding="utf-8"))
        self.assertTrue(rules, "readability sheet has no rules")
        for selector, decls, media in rules:
            for prop in decls:
                self.assertIn(prop, READABLE_PROPERTIES, f"{selector} {prop} is not an accessibility rule")
            self.assertFalse(media, f"{selector} should not need a media query")
            self.assertTrue(
                set(decls).issubset(READABLE_PROPERTIES),
                f"{selector} restyles the design: {decls}",
            )
        self.assertTrue(declarations_for(rules, "[id]"), "anchor targets do not clear the sticky header")

    def test_shell_scripts_use_src_and_the_right_asset_namespace(self):
        public = site.page("T", "<p>x</p>", "/")
        private = site.page("T", "<p>x</p>")
        for text, prefix, forbidden in (
            (public, "/mvp-assets/", "/assets/"),
            (private, "/assets/", "mvp-assets"),
        ):
            scripts = SCRIPT_RE.findall(text)
            self.assertTrue(scripts, "shell has no scripts")
            for tag in scripts:
                attrs = self._attrs(tag)
                self.assertNotIn("href", attrs, f"script uses href instead of src: {tag}")
                self.assertIn("src", attrs, f"script has no src: {tag}")
                self.assertTrue(attrs["src"].startswith(prefix), tag)
            self.assertNotIn(forbidden, text)
        self.assertIn('src="/mvp-assets/portal.js"', public)
        self.assertIn('src="/assets/portal.js"', private)

    def test_portal_js_initialises_resolved_theme_and_toggles(self):
        # First load with no stored choice follows the OS preference.
        dark = self._run_portal_js({"systemDark": True})
        self.assertEqual(dark["theme"], "dark")
        self.assertEqual(dark["colorScheme"], "dark")
        self.assertEqual(dark["pressed"], "true")
        self.assertEqual(dark["menuPressed"], "true")
        self.assertIsNone(dark["stored"], "initial page load must not write a stored preference")
        light = self._run_portal_js({"systemDark": False})
        self.assertEqual(light["theme"], "light")
        self.assertEqual(light["pressed"], "false")
        # A stored choice wins over the OS preference.
        override = self._run_portal_js({"systemDark": True, "stored": "light"})
        self.assertEqual(override["theme"], "light")
        self.assertEqual(override["pressed"], "false")
        # The toggle flips the resolved theme, records it and keeps aria-pressed honest.
        toggled = self._run_portal_js({"systemDark": True, "clickToggle": True})
        self.assertEqual(toggled["theme"], "light")
        self.assertEqual(toggled["pressed"], "false")
        self.assertEqual(toggled["menuPressed"], "false")
        self.assertEqual(toggled["stored"], "light")

    def test_portal_js_mobile_search_expands_focuses_and_escape_collapses(self):
        opened = self._run_portal_js({"systemDark": False, "clickSearch": True})
        self.assertFalse(opened["searchCollapsed"])
        self.assertEqual(opened["searchExpanded"], "true")
        self.assertEqual(opened["searchFocused"], 1)
        escaped = self._run_portal_js({"systemDark": False, "clickSearch": True, "escape": True})
        self.assertTrue(escaped["searchCollapsed"])
        self.assertEqual(escaped["searchExpanded"], "false")
        self.assertEqual(escaped["searchToggleFocused"], 1)

    def test_portal_js_mobile_menu_opens_and_escape_closes(self):
        opened = self._run_portal_js({"systemDark": False, "clickMenu": True})
        self.assertTrue(opened["navOpen"])
        self.assertEqual(opened["navExpanded"], "true")
        themed = self._run_portal_js({"systemDark": False, "clickMenuTheme": True})
        self.assertEqual(themed["theme"], "dark")
        self.assertEqual(themed["pressed"], "true")
        self.assertEqual(themed["menuPressed"], "true")
        escaped = self._run_portal_js({"systemDark": False, "clickMenu": True, "escape": True})
        self.assertFalse(escaped["navOpen"])
        self.assertEqual(escaped["navExpanded"], "false")
        self.assertEqual(escaped["menuFocused"], 1)
        # Escape on a closed menu changes nothing and steals no focus.
        untouched = self._run_portal_js({"systemDark": False, "escape": True})
        self.assertFalse(untouched["navOpen"])
        self.assertEqual(untouched["menuFocused"], 0)

    def test_private_preview_markers_and_escaping(self):
        private = site.page("</title><script>alert(1)</script>", "<p>x</p>")
        self.assertIn("noindex", private)
        self.assertNotIn('rel="canonical"', private)
        self.assertNotIn("rss.xml", private)
        self.assertIn("Yksityinen esikatselu", private)
        self.assertNotIn("<script>alert(1)</script>", private)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", private)
        self.assertNotIn("mvp-assets", private)
        self.assertNotIn("consent-dialog", private)
        self.assertNotIn("analytics.js", private)
        # The private shell still ships the ported assets, under /assets/.
        self.assertIn('/assets/css/portal-overhaul.css', private)
        self.assertIn('/assets/images/logo.png', private)
        self.assertIn('/assets/portal.js', private)
        public = site.page("T", "<p>x</p>", "/")
        self.assertIn('rel="canonical" href="https://uutistenlukija.fi/"', public)
        self.assertIn('src="/mvp-assets/consent.js"', public)

    def test_private_render_copies_assets_without_public_only_files(self):
        root = self._site_root(self._render_private("portal-private"))
        self.assertTrue((root / "assets/images/logo.png").is_file())
        self.assertTrue((root / "assets/css/portal-overhaul.css").is_file())
        self.assertTrue((root / "assets/portal.js").is_file())
        self.assertFalse((root / "assets/analytics.js").exists())
        article = self._page(root, self.job).read_text(encoding="utf-8")
        self.assertNotIn("mvp-assets", article)
        self.assertNotIn("analytics.js", article)
        footer = FOOTER_RE.search(article)
        self.assertIsNotNone(footer, "private footer is missing")
        self.assertEqual(HREF_RE.findall(footer.group(0)), [])


if __name__ == "__main__":
    unittest.main()
