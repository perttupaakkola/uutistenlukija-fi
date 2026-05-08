import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FrontpageInteractionTests(unittest.TestCase):
    def read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_weather_widget_is_dynamic_and_location_aware(self) -> None:
        header = self.read("layouts/partials/header.html")
        live_js = self.read("static/js/frontpage-live.js")

        self.assertIn("data-weather-widget", header)
        self.assertIn("data-weather-temp", header)
        self.assertIn("navigator.geolocation.getCurrentPosition", live_js)
        self.assertIn("api.open-meteo.com", live_js)
        self.assertNotIn("<strong>18 °C</strong>", header)

    def test_market_tabs_are_real_controls_backed_by_live_fetch(self) -> None:
        index = self.read("layouts/index.html")
        live_js = self.read("static/js/frontpage-live.js")

        self.assertIn("data-market-widget", index)
        self.assertIn('role="tablist"', index)
        self.assertEqual(index.count("data-market-tab="), 3)
        self.assertIn("query1.finance.yahoo.com", live_js)
        self.assertIn("loadSet(tab.getAttribute('data-market-tab'))", live_js)
        self.assertNotIn("4 512,35", index)

    def test_homepage_newsletter_uses_async_subscription_handler(self) -> None:
        index = self.read("layouts/index.html")
        base = self.read("layouts/_default/baseof.html")

        self.assertIn("js-newsletter-form", index)
        self.assertIn('action="/api/subscribe"', index)
        self.assertIn("data-newsletter-status", index)
        self.assertIn("Newsletter signup", base)

    def test_frontpage_script_loaded_only_on_home(self) -> None:
        base = self.read("layouts/_default/baseof.html")
        self.assertRegex(base, re.compile(r"{{ if \.IsHome }}<script defer src=\"/js/frontpage-live\.js\"></script>{{ end }}"))


if __name__ == "__main__":
    unittest.main()
