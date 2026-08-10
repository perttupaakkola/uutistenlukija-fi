#!/usr/bin/env python3
"""Focused regressions for the OPE-455 homepage hierarchy slice."""

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX_TEMPLATE = ROOT / "layouts" / "index.html"
CRITICAL_CSS = ROOT / "layouts" / "partials" / "critical-css.html"
HUGO_BIN = shutil.which("hugo") or "/workspace/hugo"


def _story(
    title: str,
    published: str,
    *,
    image: str | None = None,
    category_fallback: bool = False,
    active_live: bool = False,
) -> dict[str, object]:
    return {
        "title": title,
        "published": published,
        "image": image,
        "category_fallback": category_fallback,
        "active_live": active_live,
    }


def _render_homepage(stories: list[dict[str, object]]) -> str:
    with tempfile.TemporaryDirectory(prefix="ope-455-homepage-") as temp_dir:
        fixture_root = Path(temp_dir)
        posts_dir = fixture_root / "content" / "posts"
        public_dir = fixture_root / "public"
        posts_dir.mkdir(parents=True)

        for rank, story in enumerate(stories, 1):
            image = story["image"]
            frontmatter = [
                "---",
                f'title: "{story["title"]}"',
                f'description: "{story["title"]} fixture description."',
                f'date: {story["published"]}',
                'categories: ["Kotimaa"]',
                'source_name: "Fixture source"',
                "draft: false",
            ]
            if image is not None:
                frontmatter.extend(
                    (
                        f'image: "{image}"',
                        f'image_thumb: "{image}"',
                        (
                            'image_source: "category_fallback"'
                            if story["category_fallback"]
                            else 'image_source: "generated"'
                        ),
                        "image_category_fallback: "
                        + str(story["category_fallback"]).lower(),
                    )
                )
            if story["active_live"]:
                frontmatter.append("is_live: true")
            frontmatter.extend(("---", "", f'{story["title"]} fixture body.', ""))
            (posts_dir / f"fixture-{rank:02d}.md").write_text(
                "\n".join(frontmatter), encoding="utf-8"
            )

        completed = subprocess.run(
            (
                HUGO_BIN,
                "--source",
                str(ROOT),
                "--contentDir",
                str(fixture_root / "content"),
                "--destination",
                str(public_dir),
                "--cleanDestinationDir",
                "--quiet",
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        if completed.returncode != 0:
            raise AssertionError(
                "Hugo fixture render failed:\n"
                f"{completed.stdout}\n{completed.stderr}"
            )
        return (public_dir / "index.html").read_text(encoding="utf-8")


def _teaser_cards(rendered: str) -> list[tuple[str, str, str]]:
    cards: list[tuple[str, str, str]] = []
    for classes, body in re.findall(
        r'<article class="([^"]*portal-teaser[^"]*)">(.*?)</article>',
        rendered,
        re.DOTALL,
    ):
        title_match = re.search(r"<h3><a[^>]*>(.*?)</a></h3>", body, re.DOTALL)
        if title_match is None:
            raise AssertionError("homepage teaser is missing its linked headline")
        cards.append((classes, re.sub(r"\s+", " ", title_match.group(1)).strip(), body))
    return cards


def _livebar(rendered: str) -> tuple[str, str]:
    match = re.search(
        r'<a class="([^"]*portal-livebar[^"]*)"[^>]*>(.*?)</a>',
        rendered,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError("homepage status bar is missing")
    return match.group(1), match.group(2)


def _compact_css(path: Path) -> str:
    return re.sub(r"\s+", "", path.read_text(encoding="utf-8")).replace(";}", "}")


class HomepagePeerBenchmarkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fallback = "/images/categories/kotimaa.jpg"
        cls.fallback_only = _render_homepage(
            [
                _story("Newest image-free lead", "2020-08-10T12:00:00+00:00"),
                _story("Ordinary status story", "2020-08-10T11:00:00+00:00"),
                *[
                    _story(
                        f"Fresh fallback {number}",
                        f"2020-08-10T{10 - number:02d}:00:00+00:00",
                        image=fallback,
                        category_fallback=True,
                    )
                    for number in range(1, 5)
                ],
                *[
                    _story(
                        f"Older illustrated July 19 story {number}",
                        f"2020-07-19T{13 - number:02d}:00:00+00:00",
                        image=f"/images/articles/older-{number}.jpg",
                    )
                    for number in range(1, 5)
                ],
            ]
        )
        cls.mixed_live = _render_homepage(
            [
                _story("Newest mixed lead", "2020-08-10T12:00:00+00:00"),
                _story(
                    "Explicit active live story",
                    "2020-08-10T11:00:00+00:00",
                    active_live=True,
                ),
                _story(
                    "Fresh category fallback",
                    "2020-08-10T10:00:00+00:00",
                    image=fallback,
                    category_fallback=True,
                ),
                _story(
                    "Fresh approved image",
                    "2020-08-10T09:00:00+00:00",
                    image="/images/articles/fresh-approved.jpg",
                ),
                _story("Fresh missing image", "2020-08-10T08:00:00+00:00"),
                _story(
                    "Fresh generated image",
                    "2020-08-10T07:00:00+00:00",
                    image="/images/articles/fresh-generated.jpg",
                ),
                _story(
                    "Older approved image",
                    "2020-07-19T12:00:00+00:00",
                    image="/images/articles/older-approved.jpg",
                ),
            ]
        )

    def test_four_july_19_visual_substitutes_do_not_displace_fresh_stories(self) -> None:
        cards = _teaser_cards(self.fallback_only)
        self.assertEqual(
            [title for _classes, title, _body in cards],
            [f"Fresh fallback {number}" for number in range(1, 5)],
        )
        for classes, _title, body in cards:
            self.assertIn("portal-teaser--no-image", classes)
            self.assertNotIn("<img ", body)
            self.assertNotIn("2020-07-19", body)

    def test_mixed_primary_followups_keep_order_and_only_safe_images(self) -> None:
        cards = _teaser_cards(self.mixed_live)
        self.assertEqual(
            [title for _classes, title, _body in cards],
            [
                "Fresh category fallback",
                "Fresh approved image",
                "Fresh missing image",
                "Fresh generated image",
            ],
        )
        self.assertIn("portal-teaser--no-image", cards[0][0])
        self.assertNotIn("<img ", cards[0][2])
        self.assertNotIn("portal-teaser--no-image", cards[1][0])
        self.assertIn("/images/articles/fresh-approved.jpg", cards[1][2])
        self.assertIn("portal-teaser--no-image", cards[2][0])
        self.assertNotIn("<img ", cards[2][2])
        self.assertNotIn("portal-teaser--no-image", cards[3][0])
        self.assertIn("/images/articles/fresh-generated.jpg", cards[3][2])

    def test_ordinary_story_has_no_false_live_status_and_exact_time(self) -> None:
        classes, body = _livebar(self.fallback_only)
        self.assertIn("portal-livebar--latest", classes)
        self.assertNotIn("portal-livebar__badge", body)
        self.assertNotRegex(body, r"(?i)>\s*live\s*<")
        self.assertIn('datetime="2020-08-10T11:00:00Z"', body)
        self.assertIn("Ordinary status story", body)
        self.assertIn("Lue juttu", body)
        self.assertNotIn("Katso kaikki päivitykset", body)

    def test_explicit_active_live_story_keeps_live_semantics(self) -> None:
        classes, body = _livebar(self.mixed_live)
        self.assertNotIn("portal-livebar--latest", classes)
        self.assertRegex(body, r'portal-livebar__badge">\s*Live\s*</span>')
        self.assertIn('datetime="2020-08-10T11:00:00Z"', body)
        self.assertIn("Explicit active live story", body)
        self.assertIn("Katso kaikki päivitykset", body)

    def test_image_free_lead_and_teasers_have_content_driven_css_contract(self) -> None:
        lead_grid = re.search(
            r'<section class="([^"]*portal-front-grid[^"]*)"', self.fallback_only
        )
        self.assertIsNotNone(lead_grid)
        self.assertIn("portal-front-grid--image-free-lead", lead_grid.group(1))
        lead = re.search(
            r'<article class="([^"]*portal-lead[^"]*)">(.*?)</article>',
            self.fallback_only,
            re.DOTALL,
        )
        self.assertIsNotNone(lead)
        self.assertNotIn("portal-lead__image", lead.group(2))

        template = INDEX_TEMPLATE.read_text(encoding="utf-8")
        self.assertNotIn("$visualPosts", template)
        self.assertIn("portal-teaser--no-image", template)
        self.assertIn("card.classList.add('portal-teaser--no-image')", template)
        self.assertNotIn("this.src=", template.split("portal-center-list", 1)[1].split("</div>", 1)[0])

        css = _compact_css(CRITICAL_CSS)
        for rule in (
            ".portal-front-grid.portal-front-grid--image-free-lead.portal-lead{"
            "min-height:0}",
            ".portal-front-grid.portal-front-grid--image-free-lead.portal-lead__body{"
            "position:relative;left:auto;right:auto;bottom:auto;padding:24px}",
            "@media(min-width:681px){"
            ".portal-front-grid.portal-front-grid--image-free-lead.portal-lead.portal-kicker{"
            "color:#fff!important}}",
            ".portal-teaser.portal-teaser--no-image{"
            "grid-template-columns:minmax(0,1fr)}",
        ):
            self.assertIn(rule, css)


if __name__ == "__main__":
    unittest.main()
