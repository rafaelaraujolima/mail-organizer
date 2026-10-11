import re

import bleach

ALLOWED_TAGS = [
    "p", "br", "b", "i", "strong", "em", "ul", "ol", "li", "blockquote",
    "div", "span", "table", "thead", "tbody", "tr", "th", "td",
]

# html5lib parses <script>/<style> content as raw text, so a bare bleach.clean()
# strip would leave their text content visible on the page (not executable, but
# noise). Remove both tags and their content before the allowlist pass.
_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_LINK = re.compile(r'<a\s[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)


def sanitize_html(html: str | None) -> str:
    if not html:
        return ""

    without_scripts = _SCRIPT_OR_STYLE.sub("", html)
    # Every link becomes inert text plus its raw URL -- nothing in the output is
    # ever clickable, which matters most for messages already flagged suspicious.
    as_text_links = _LINK.sub(lambda m: f"{m.group(2)} ({m.group(1)})", without_scripts)

    return bleach.clean(
        as_text_links,
        tags=ALLOWED_TAGS,
        attributes={},
        strip=True,
        strip_comments=True,
    )
