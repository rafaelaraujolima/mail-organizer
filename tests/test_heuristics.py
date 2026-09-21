from mail_organizer.heuristics import (
    AuthResult,
    parse_authentication_results,
    detect_domain_mismatch,
    extract_links,
    has_suspicious_links,
)


def test_parses_all_three_mechanisms_when_present():
    headers = {
        "Authentication-Results": (
            "mx.google.com; spf=pass smtp.mailfrom=foo@bar.com; "
            "dkim=fail header.i=@bar.com; dmarc=pass (p=REJECT) header.from=bar.com"
        )
    }

    result = parse_authentication_results(headers)

    assert result == AuthResult(spf="pass", dkim="fail", dmarc="pass")


def test_returns_all_none_when_header_missing():
    result = parse_authentication_results({})

    assert result == AuthResult(spf=None, dkim=None, dmarc=None)


def test_header_lookup_is_case_insensitive():
    headers = {"authentication-results": "spf=fail"}

    result = parse_authentication_results(headers)

    assert result.spf == "fail"


def test_missing_mechanism_stays_none():
    headers = {"Authentication-Results": "spf=pass"}

    result = parse_authentication_results(headers)

    assert result == AuthResult(spf="pass", dkim=None, dmarc=None)


def test_detects_mismatch_between_sender_and_return_path():
    headers = {"Return-Path": "<bounce@evil.com>"}

    assert detect_domain_mismatch("victim@bank.com", headers) is True


def test_no_mismatch_when_domains_match():
    headers = {"Return-Path": "<bounce@bank.com>"}

    assert detect_domain_mismatch("victim@bank.com", headers) is False


def test_no_mismatch_when_return_path_header_missing():
    assert detect_domain_mismatch("victim@bank.com", {}) is False


def test_no_mismatch_when_sender_has_no_domain():
    headers = {"Return-Path": "<bounce@evil.com>"}

    assert detect_domain_mismatch("", headers) is False


def test_extract_links_finds_href_urls():
    html = '<a href="https://example.com/a">A</a> <a href="http://x.com">B</a>'

    assert extract_links(html) == ["https://example.com/a", "http://x.com"]


def test_extract_links_returns_empty_list_for_empty_html():
    assert extract_links("") == []
    assert extract_links(None) == []


def test_has_suspicious_links_true_for_url_shortener():
    html = '<a href="https://bit.ly/abc123">click</a>'

    assert has_suspicious_links(html) is True


def test_has_suspicious_links_true_for_lookalike_domain():
    html = '<a href="https://paypal.com.evil.com/login">login</a>'

    assert has_suspicious_links(html, expected_domain="paypal.com") is True


def test_has_suspicious_links_false_for_legitimate_matching_domain():
    html = '<a href="https://paypal.com/login">login</a>'

    assert has_suspicious_links(html, expected_domain="paypal.com") is False


def test_has_suspicious_links_false_for_empty_html():
    assert has_suspicious_links("") is False
