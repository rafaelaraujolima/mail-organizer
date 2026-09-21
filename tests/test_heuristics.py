from mail_organizer.heuristics import AuthResult, parse_authentication_results


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
