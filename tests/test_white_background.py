"""Owner rule (Perttu, 10 Oct 2026): the site page background stays WHITE in light mode.

Guards every stylesheet that defines the light-mode page background so a future
redesign cannot reintroduce a grey/beige/"warm paper" page colour. Dark mode is
unaffected.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHITE = {"#fff", "#ffffff", "white"}
PAGE_VARS = ("--bg", "--portal-bg")


def strip_dark_media(css: str) -> str:
    """Remove @media (prefers-color-scheme: dark) { ... } blocks, brace-matched."""
    out, i = [], 0
    pat = re.compile(r"@media[^{]*prefers-color-scheme\s*:\s*dark[^{]*\{")
    while True:
        m = pat.search(css, i)
        if not m:
            out.append(css[i:])
            return "".join(out)
        out.append(css[i:m.start()])
        depth, j = 1, m.end()
        while depth and j < len(css):
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        i = j


def light_blocks(css: str):
    """Yield declaration blocks whose selector is a light/default root (not dark)."""
    css = strip_dark_media(css)
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        sel = selector.strip()
        if "dark" in sel:
            continue
        if ":root" in sel or sel.startswith("html") or sel == "body":
            yield sel, body


class WhitePageBackground(unittest.TestCase):
    def test_light_page_background_variables_are_white(self):
        sheets = list((ROOT / "static").rglob("*.css"))
        self.assertTrue(sheets)
        offenders = []
        for sheet in sheets:
            css = re.sub(r"/\*.*?\*/", "", sheet.read_text(), flags=re.S)
            for sel, body in light_blocks(css):
                for var in PAGE_VARS:
                    for value in re.findall(rf"{re.escape(var)}\s*:\s*([^;}}]+)", body):
                        if value.strip().lower() not in WHITE:
                            offenders.append(f"{sheet.relative_to(ROOT)} {sel} {var}:{value.strip()}")
        self.assertEqual(offenders, [], "Light-mode page background must stay white")


if __name__ == "__main__":
    unittest.main()
