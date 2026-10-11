# tests/test_rules.py
from mail_organizer.rules import RuleCandidate, detect_rule_candidates


def _move(sender, folder="Promotions", **extra):
    proposal = {"action": "move", "target_folder": folder, "sender": sender}
    proposal.update(extra)
    return proposal


def test_three_emails_from_one_sender_to_one_folder_propose_a_sender_rule():
    proposals = [_move("news@shop.com")] * 3

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [RuleCandidate("sender", "news@shop.com", "Promotions", 3)]


def test_below_threshold_proposes_nothing():
    proposals = [_move("news@shop.com")] * 2

    assert detect_rule_candidates(proposals, [], threshold=3) == []


def test_threshold_is_configurable():
    proposals = [_move("news@shop.com")] * 2

    result = detect_rule_candidates(proposals, [], threshold=2)

    assert result == [RuleCandidate("sender", "news@shop.com", "Promotions", 2)]


def test_sender_is_normalized_to_lowercase():
    proposals = [_move("News@Shop.COM")] * 3

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [RuleCandidate("sender", "news@shop.com", "Promotions", 3)]


def test_tie_between_two_folders_proposes_nothing():
    proposals = [_move("a@shop.com", "Promotions")] * 3 + [_move("a@shop.com", "Updates")] * 3

    assert detect_rule_candidates(proposals, [], threshold=3) == []


def test_strict_majority_folder_wins_even_with_another_folder_present():
    proposals = [_move("a@shop.com", "Promotions")] * 4 + [_move("a@shop.com", "Updates")] * 1

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [RuleCandidate("sender", "a@shop.com", "Promotions", 4)]


def test_domain_rule_when_no_single_sender_reaches_threshold_but_the_domain_does():
    proposals = [_move("a@shop.com"), _move("b@shop.com"), _move("c@shop.com")]

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [RuleCandidate("domain", "shop.com", "Promotions", 3)]


def test_sender_rule_wins_and_domain_only_counts_uncovered_emails():
    # a@ has 3 (sender rule); the 2 others from the domain are below threshold on their own.
    proposals = [_move("a@shop.com")] * 3 + [_move("b@shop.com"), _move("c@shop.com")]

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [RuleCandidate("sender", "a@shop.com", "Promotions", 3)]


def test_domain_rule_is_built_from_emails_not_covered_by_a_sender_rule():
    proposals = (
        [_move("a@shop.com")] * 3
        + [_move("b@shop.com"), _move("c@shop.com"), _move("d@shop.com")]
    )

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [
        RuleCandidate("domain", "shop.com", "Promotions", 3),
        RuleCandidate("sender", "a@shop.com", "Promotions", 3),
    ]


def test_only_move_proposals_count():
    proposals = (
        [{"action": "flag_delete", "target_folder": None, "sender": "a@shop.com"}] * 5
        + [{"action": "keep", "target_folder": None, "sender": "a@shop.com"}] * 5
        + [{"action": "create_rule", "target_folder": "Promotions", "sender": "a@shop.com"}] * 5
    )

    assert detect_rule_candidates(proposals, [], threshold=3) == []


def test_existing_rule_for_same_condition_suppresses_candidate_for_any_folder():
    proposals = [_move("a@shop.com", "Promotions")] * 3

    result = detect_rule_candidates(proposals, [("sender", "a@shop.com")], threshold=3)

    assert result == []


def test_emails_of_a_sender_with_an_existing_rule_do_not_feed_a_domain_rule():
    proposals = [_move("a@shop.com")] * 3 + [_move("b@shop.com")] * 2

    result = detect_rule_candidates(proposals, [("sender", "a@shop.com")], threshold=3)

    assert result == []


def test_existing_domain_rule_suppresses_domain_candidate():
    proposals = [_move("a@shop.com"), _move("b@shop.com"), _move("c@shop.com")]

    result = detect_rule_candidates(proposals, [("domain", "shop.com")], threshold=3)

    assert result == []


def test_unsafe_or_malformed_senders_are_skipped():
    bad = [
        "a b@shop.com",
        'a"@shop.com',
        "a(b)@shop.com",
        "no-at-sign",
        "a@localhost",
        "",
        None,
    ]
    proposals = [_move(sender) for sender in bad for _ in range(5)]

    assert detect_rule_candidates(proposals, [], threshold=3) == []


def test_proposals_without_target_folder_are_ignored():
    proposals = [{"action": "move", "target_folder": None, "sender": "a@shop.com"}] * 5

    assert detect_rule_candidates(proposals, [], threshold=3) == []


def test_output_is_ordered_by_count_then_kind_then_value():
    proposals = (
        [_move("z@one.com")] * 3
        + [_move("a@two.com")] * 5
        + [_move("b@two.com")] * 3
    )

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert [(c.value, c.count) for c in result] == [("a@two.com", 5), ("b@two.com", 3), ("z@one.com", 3)]
