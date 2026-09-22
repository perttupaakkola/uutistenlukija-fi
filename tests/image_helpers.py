"""Exact branding-aware image parsing shared by rendering contract tests."""
from html.parser import HTMLParser


BRANDING_SRCS = frozenset({
    "/mvp-assets/images/logo.png",
    "/assets/images/logo.png",
})
VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
})


class PageScan(HTMLParser):
    """Start tags, exact branding context, images and visible text."""

    def __init__(self):
        super().__init__()
        self.starts = []
        self.imgs = []
        self.image_records = []
        self.captions = []
        self.text = []
        self._caption = 0
        self._chrome = 0
        self._blocked = 0
        self._picture = 0
        self._has_alternative = False
        self._scopes = []

    @staticmethod
    def _scope(tag, classes):
        blocked = (
            tag in ("main", "article")
            or any(
                token == "teaser" or "teaser" in token or token == "article"
                or token.startswith("article-") or token.endswith("-article")
                or token.startswith("portal-article")
                for token in classes
            )
        )
        return {
            "tag": tag,
            "chrome": tag in ("header", "footer"),
            "blocks": int(tag in ("main", "article")) + int(blocked),
            "picture": tag == "picture",
            "caption": tag == "figcaption",
        }

    def _push(self, scope):
        self._scopes.append(scope)
        self._chrome += scope["chrome"]
        self._blocked += scope["blocks"]
        self._picture += scope["picture"]
        self._caption += scope["caption"]

    def _close(self, scope):
        self._chrome -= scope["chrome"]
        self._blocked -= scope["blocks"]
        self._picture -= scope["picture"]
        self._caption -= scope["caption"]

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        pairs = dict(attrs)
        self.starts.append((tag, pairs))
        classes = pairs.get("class", "").split()
        scope = self._scope(tag, classes)
        if tag == "source":
            self._has_alternative = True
        elif tag == "picture":
            self._has_alternative = True
        if tag == "img":
            names = [name.lower() for name, _value in attrs]
            values = {name.lower(): value for name, value in attrs}
            branding = (
                values.get("src") in BRANDING_SRCS
                and "srcset" not in names
                and len(names) == len(set(names))
                and (self._chrome > 0 or scope["chrome"])
                and self._blocked == 0
                and scope["blocks"] == 0
                and self._picture == 0
                and not scope["picture"]
                and not self._has_alternative
            )
            self.imgs.append(pairs)
            self.image_records.append((pairs, branding))
        if tag not in VOID_TAGS:
            self._push(scope)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in VOID_TAGS or not self._scopes or self._scopes[-1]["tag"] != tag:
            return
        self._close(self._scopes.pop())

    def handle_data(self, data):
        self.text.append(data)
        if self._caption:
            self.captions.append(data)


def scan(text):
    parsed = PageScan()
    parsed.feed(text)
    return parsed


def editorial_images(page):
    """Images that are not exact outer header/footer branding."""
    return [attrs for attrs, branding in page.image_records if not branding]
