import pytest

from mail_organizer.sanitize import sanitize_html


def test_removes_script_tag_and_its_content():
    html = "<p>Hello</p><script>alert('xss')</script>"

    assert sanitize_html(html) == "<p>Hello</p>"


def test_removes_style_tag_and_its_content():
    html = "<style>body{display:none}</style><p>Hi</p>"

    assert sanitize_html(html) == "<p>Hi</p>"


def test_strips_img_tag_entirely_to_block_remote_images():
    html = '<p>Look</p><img src="https://evil.com/track.png">'

    assert sanitize_html(html) == "<p>Look</p>"


def test_converts_link_to_visible_text_plus_url():
    html = '<a href="https://evil.example/login">Click here</a>'

    assert sanitize_html(html) == "Click here (https://evil.example/login)"


def test_javascript_uri_link_becomes_inert_text():
    html = '<a href="javascript:alert(1)">Click</a>'

    result = sanitize_html(html)

    assert "<a" not in result
    assert "javascript:alert(1)" in result


def test_strips_event_handler_attributes_from_surviving_tags():
    html = '<div onclick="alert(1)">Hi</div>'

    assert sanitize_html(html) == "<div>Hi</div>"


def test_preserves_allowed_formatting_tags():
    html = "<p>Hello <b>world</b></p>"

    assert sanitize_html(html) == "<p>Hello <b>world</b></p>"


def test_empty_or_none_input_returns_empty_string():
    assert sanitize_html("") == ""
    assert sanitize_html(None) == ""


@pytest.mark.parametrize(
    "html",
    [
        "<SCRIPT>alert(1)</SCRIPT>x",
        "<a href=javascript:alert(1)>click</a>",
        "<a href='javascript:x'>t</a>",
        '<a href="https://e.com"><img src=x onerror=alert(1)>pay</a>',
        "<script>alert(1)",
        "<scr<script>ipt>alert(1)</scr</script>ipt>",
        "<svg onload=alert(1)>",
        "<!-- c --><p>t</p>",
    ],
)
def test_adversarial_input_yields_inert_output(html):
    out = sanitize_html(html).lower()

    assert "<script" not in out
    assert "onerror" not in out
    assert "onload" not in out
    assert "<a " not in out
    assert "<img" not in out
    assert "<svg" not in out
    assert "<!--" not in out


def test_uppercase_script_tag_is_removed_but_surrounding_text_kept():
    assert sanitize_html("<SCRIPT>alert(1)</SCRIPT>x") == "x"


def test_single_quoted_javascript_link_is_rendered_as_text_with_its_url():
    assert sanitize_html("<a href='javascript:x'>t</a>") == "t (javascript:x)"
