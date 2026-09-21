from mail_organizer.heuristics import AuthResult, parse_authentication_results, detect_domain_mismatch


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
