# tests/test_rules.py
import pytest

from mail_organizer.rules import RuleCandidate, detect_rule_candidates, is_system_folder


def _move(sender, folder="Promotions", **extra):
    proposal = {"action": "move", "target_folder": folder, "sender": sender}
    proposal.update(extra)
    return proposal


def test_three_emails_from_one_sender_to_one_folder_propose_a_sender_rule():
    proposals = [_move("news@shop.com")] * 3

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [RuleCandidate("sender", "news@shop.com", "Promotions", 3, 3)]


def test_below_threshold_proposes_nothing():
    proposals = [_move("news@shop.com")] * 2

    assert detect_rule_candidates(proposals, [], threshold=3) == []


def test_threshold_is_configurable():
    proposals = [_move("news@shop.com")] * 2

    result = detect_rule_candidates(proposals, [], threshold=2)

    assert result == [RuleCandidate("sender", "news@shop.com", "Promotions", 2, 2)]


def test_sender_is_normalized_to_lowercase():
    proposals = [_move("News@Shop.COM")] * 3

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [RuleCandidate("sender", "news@shop.com", "Promotions", 3, 3)]


def test_tie_between_two_folders_proposes_nothing():
    proposals = [_move("a@shop.com", "Promotions")] * 3 + [_move("a@shop.com", "Updates")] * 3

    assert detect_rule_candidates(proposals, [], threshold=3) == []


def test_strict_majority_folder_wins_even_with_another_folder_present():
    proposals = [_move("a@shop.com", "Promotions")] * 4 + [_move("a@shop.com", "Updates")] * 1

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [RuleCandidate("sender", "a@shop.com", "Promotions", 4, 5)]


def test_domain_rule_when_no_single_sender_reaches_threshold_but_the_domain_does():
    proposals = [_move("a@shop.com"), _move("b@shop.com"), _move("c@shop.com")]

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [RuleCandidate("domain", "shop.com", "Promotions", 3, 3)]


def test_sender_rule_wins_and_domain_only_counts_uncovered_emails():
    # a@ has 3 (sender rule); the 2 others from the domain are below threshold on their own.
    proposals = [_move("a@shop.com")] * 3 + [_move("b@shop.com"), _move("c@shop.com")]

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [RuleCandidate("sender", "a@shop.com", "Promotions", 3, 3)]


def test_domain_rule_is_built_from_emails_not_covered_by_a_sender_rule():
    proposals = (
        [_move("a@shop.com")] * 3
        + [_move("b@shop.com"), _move("c@shop.com"), _move("d@shop.com")]
    )

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [
        RuleCandidate("domain", "shop.com", "Promotions", 3, 3),
        RuleCandidate("sender", "a@shop.com", "Promotions", 3, 3),
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


@pytest.mark.parametrize(
    "folder", ["TRASH", "Spam", "Deleted Items", "INBOX", "CATEGORY_PROMOTIONS", " trash ", "category_social"]
)
def test_moves_to_system_folders_never_become_rule_candidates(folder):
    proposals = [_move("a@shop.com", folder)] * 3 + [_move("b@news.com", "Promotions")] * 3

    result = detect_rule_candidates(proposals, [], threshold=3)

    # positive control: the same input with a regular folder still yields a rule
    assert result == [RuleCandidate("sender", "b@news.com", "Promotions", 3, 3)]


def test_system_folder_moves_do_not_feed_a_domain_rule():
    proposals = [_move("a@shop.com", "Trash"), _move("b@shop.com", "Trash"), _move("c@shop.com", "Trash")]
    assert detect_rule_candidates(proposals, [], threshold=3) == []

    regular = [_move("a@shop.com"), _move("b@shop.com"), _move("c@shop.com")]
    assert detect_rule_candidates(regular, [], threshold=3) == [
        RuleCandidate("domain", "shop.com", "Promotions", 3, 3)
    ]


@pytest.mark.parametrize(
    "name", ["inbox", "INBOX", "Trash", " Spam ", "Sent Items", "Junk E-mail", "Bin", "CATEGORY_UPDATES", "Category_x"]
)
def test_is_system_folder_recognises_system_names(name):
    assert is_system_folder(name) is True


@pytest.mark.parametrize("name", ["Promotions", "Newsletters", "Receipts", "categories", "My Trash Can", ""])
def test_is_system_folder_rejects_regular_names(name):
    assert is_system_folder(name) is False


INVALID_ADDRESSES = [
    "-a@b.com", ".a@b.com", "a.@b.com", "a..b@c.com", "*@b.com", "a{b}@c.com", "a|b@c.com",
    "a:b@c.com", "a/b@c.com", "a@b..com", "a@.b.com", "a@-b.com", "a@b-.com", "a@b.c",
    '"x"@b.com', "a\x00@b.com", "a" * 300 + "@b.com",
]


@pytest.mark.parametrize("address", INVALID_ADDRESSES)
def test_invalid_addresses_never_produce_a_candidate(address):
    assert detect_rule_candidates([_move(address)] * 5, [], threshold=3) == []


@pytest.mark.parametrize("address", ["news@shop.com", "first.last+tag@sub.shop.co.uk", "a_b%c@shop-1.com"])
def test_valid_addresses_still_produce_a_candidate(address):
    result = detect_rule_candidates([_move(address)] * 3, [], threshold=3)

    assert result == [RuleCandidate("sender", address.lower(), "Promotions", 3, 3)]


def test_trailing_newline_is_stripped_not_rejected():
    result = detect_rule_candidates([_move("a@b.com" + chr(10))] * 3, [], threshold=3)

    assert result == [RuleCandidate("sender", "a@b.com", "Promotions", 3, 3)]


def test_total_counts_every_non_rule_proposal_of_the_sender_regardless_of_action_or_folder():
    proposals = (
        [_move("a@shop.com", "Promotions")] * 3
        + [_move("a@shop.com", "Updates")] * 1
        + [{"action": "keep", "target_folder": None, "sender": "a@shop.com"}] * 2
        + [{"action": "flag_delete", "target_folder": None, "sender": "a@shop.com"}] * 1
        + [{"action": "create_rule", "target_folder": "Promotions", "sender": "a@shop.com"}] * 4
        + [{"action": "keep", "target_folder": None, "sender": "other@shop.com"}] * 2
    )

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert result == [RuleCandidate("sender", "a@shop.com", "Promotions", 3, 7)]


def test_domain_total_counts_only_uncovered_senders_of_the_domain():
    proposals = (
        [_move("a@shop.com")] * 3  # covered by a sender rule
        + [{"action": "keep", "target_folder": None, "sender": "a@shop.com"}] * 4
        + [_move("b@shop.com"), _move("c@shop.com"), _move("d@shop.com")]
        + [{"action": "keep", "target_folder": None, "sender": "e@shop.com"}] * 2
    )

    result = detect_rule_candidates(proposals, [], threshold=3)

    assert RuleCandidate("domain", "shop.com", "Promotions", 3, 5) in result
    assert RuleCandidate("sender", "a@shop.com", "Promotions", 3, 7) in result


@pytest.mark.parametrize("threshold", [0, -5])
def test_non_positive_threshold_behaves_like_one(threshold):
    proposals = (
        [_move("one@shop.com")]
        + [{"action": "keep", "target_folder": None, "sender": "keep@shop.com"}] * 3
        + [{"action": "move", "target_folder": None, "sender": "nofolder@shop.com"}] * 3
        + [_move("not-an-address")] * 3
    )

    result = detect_rule_candidates(proposals, [], threshold=threshold)

    assert result == [RuleCandidate("sender", "one@shop.com", "Promotions", 1, 1)]
