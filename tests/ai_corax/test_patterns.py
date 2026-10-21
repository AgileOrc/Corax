import pytest
from patterns import Predicate, candidates, predicates_for, sample_pairs

HEAD = "position_head_of_program"

STRUCTURE = {
    "budi": {"holds": [HEAD], "member_of": ["IF"], "teaches": ["IF201"], "advises": ["ani"]},
    "andi": {"holds": ["position_lecturer"], "member_of": ["IF"], "teaches": ["IF202"]},
    "rina": {"holds": ["position_lecturer"], "member_of": ["IF"]},
    "sari": {"holds": [HEAD], "member_of": ["SI"], "teaches": ["SI101"]},
    "tono": {"holds": ["position_lecturer"], "member_of": ["SI"]},
    "ani": {"member_of": ["IF"], "enrolled_in": ["IF201"]},
    "candra": {"member_of": ["IF"], "enrolled_in": ["IF201", "IF202"]},
    "fajar": {"member_of": ["IF"], "enrolled_in": ["IF202"]},
    "dewi": {"member_of": ["SI"], "enrolled_in": ["SI101"]},
    "eko": {"member_of": ["SI"], "enrolled_in": ["SI101"]},
    "gita": {"member_of": ["SI"], "enrolled_in": ["SI102"]},
}
LECTURERS = ["budi", "andi", "rina", "sari", "tono"]
STUDENTS = ["ani", "candra", "fajar", "dewi", "eko", "gita"]
ACCESS = {
    "budi": frozenset({"ani", "candra"}),
    "andi": frozenset({"candra", "fajar"}),
    "sari": frozenset({"dewi", "eko"}),
}
APPEAL = ("budi", "fajar")

SAME_PROGRAM = Predicate("shared", "member_of", "member_of")
IS_HEAD = Predicate("user_has", "holds", HEAD)


def ladder(found):
    return [(c.text(), c.users, c.pairs) for c in found]


def test_vocabulary_lists_every_true_predicate():
    assert predicates_for(STRUCTURE, "budi", "candra") == sorted(
        [
            Predicate("object_has", "enrolled_in", "IF201"),
            Predicate("object_has", "enrolled_in", "IF202"),
            Predicate("object_has", "member_of", "IF"),
            Predicate("shared", "member_of", "member_of"),
            Predicate("shared", "teaches", "enrolled_in"),
            Predicate("user_has", "advises", "ani"),
            Predicate("user_has", "holds", HEAD),
            Predicate("user_has", "member_of", "IF"),
            Predicate("user_has", "teaches", "IF201"),
        ]
    )


def test_predicates_naming_a_person_can_be_skipped():
    people = frozenset(LECTURERS + STUDENTS)

    found = predicates_for(STRUCTURE, "budi", "candra", identities=people)

    assert Predicate("user_has", "advises", "ani") not in found


def test_direct_relation_is_found():
    found = predicates_for(STRUCTURE, "budi", "ani", identities=frozenset(STUDENTS))

    assert Predicate("direct", "advises") in found


def test_predicates_read_like_the_rule():
    assert IS_HEAD.text() == "user holds position_head_of_program"
    assert SAME_PROGRAM.text() == "user.member_of = object.member_of"
    assert Predicate("direct", "advises").text() == "user advises object"


def test_candidates_go_from_narrowest_to_broadest():
    found = candidates(STRUCTURE, ACCESS, APPEAL, LECTURERS, STUDENTS)

    assert ladder(found) == [
        ("user.member_of = object.member_of AND user holds " + HEAD, 1, 1),
        ("user teaches IF201", 1, 3),
        ("user.member_of = object.member_of AND user member_of IF", 2, 4),
        ("user holds " + HEAD, 2, 7),
        ("user.member_of = object.member_of", 4, 8),
        ("user member_of IF", 3, 13),
    ]


def test_head_of_program_candidate_opens_the_right_pair():
    found = candidates(STRUCTURE, ACCESS, APPEAL, LECTURERS, STUDENTS)

    head_rule = next(c for c in found if c.predicates == (SAME_PROGRAM, IS_HEAD))
    assert head_rule.examples == (("sari", "gita"),)
    assert not head_rule.estimated


def test_existing_access_and_the_appeal_are_never_counted():
    for candidate in candidates(STRUCTURE, ACCESS, APPEAL, LECTURERS, STUDENTS):
        for user, obj in candidate.examples:
            assert obj not in ACCESS.get(user, ())
            assert (user, obj) != APPEAL


def test_candidates_opening_the_same_pairs_are_listed_once():
    texts = [c.text() for c in candidates(STRUCTURE, ACCESS, APPEAL, LECTURERS, STUDENTS)]

    assert "user holds " + HEAD + " AND user member_of IF" not in texts
    assert len(texts) == len(set(texts))


def test_object_values_are_off_by_default():
    default = candidates(STRUCTURE, ACCESS, APPEAL, LECTURERS, STUDENTS)
    with_values = candidates(STRUCTURE, ACCESS, APPEAL, LECTURERS, STUDENTS, object_values=True)

    assert not any(p.kind == "object_has" for c in default for p in c.predicates)
    assert any(p.kind == "object_has" for c in with_values for p in c.predicates)


def test_knn_neighbours_are_shown_as_support():
    neighbours = [("sari", "gita"), ("rina", "ani"), ("tono", "gita"), ("andi", "dewi")]

    found = candidates(STRUCTURE, ACCESS, APPEAL, LECTURERS, STUDENTS, neighbours=neighbours)

    by_text = {c.text(): c.support for c in found}
    assert by_text["user.member_of = object.member_of"] == 0.75
    assert by_text["user.member_of = object.member_of AND user holds " + HEAD] == 0.25


def test_relational_scope_is_estimated_on_very_large_graphs():
    found = candidates(
        STRUCTURE, ACCESS, APPEAL, LECTURERS, STUDENTS, exact_limit=1, sample_size=20_000
    )

    by_text = {c.text(): c for c in found}
    same_program = by_text["user.member_of = object.member_of"]
    assert same_program.estimated and same_program.users is None
    assert same_program.pairs == pytest.approx(8, abs=1)
    head = by_text["user holds " + HEAD]
    assert not head.estimated
    assert (head.users, head.pairs) == (2, 7)


def test_object_is_names_the_appealed_object():
    found = predicates_for(STRUCTURE, "budi", "fajar", object_identity=True)

    assert Predicate("object_is", "", "fajar") in found
    assert Predicate("object_is", "", "fajar").text() == "object is fajar"
    assert Predicate("object_is", "", "fajar").holds(STRUCTURE, "rina", "fajar")
    assert not Predicate("object_is", "", "fajar").holds(STRUCTURE, "rina", "ani")


def test_role_and_object_candidate_for_permission_groups():
    found = candidates(STRUCTURE, ACCESS, APPEAL, LECTURERS, STUDENTS, object_identity=True)

    by_text = {c.text(): c for c in found}
    role_rule = by_text["object is fajar AND user member_of IF"]
    assert (role_rule.users, role_rule.pairs) == (1, 1)
    assert role_rule.examples == (("rina", "fajar"),)
    assert not role_rule.estimated


def test_separable_scope_is_exact_on_very_large_graphs():
    small = candidates(STRUCTURE, ACCESS, APPEAL, LECTURERS, STUDENTS, object_identity=True)
    large = candidates(
        STRUCTURE, ACCESS, APPEAL, LECTURERS, STUDENTS, object_identity=True, exact_limit=1
    )

    def separable(found):
        return [
            (c.text(), c.users, c.pairs)
            for c in found
            if all(p.kind in {"user_has", "object_is"} for p in c.predicates)
        ]

    assert separable(small) == separable(large)


def test_random_pairs_skip_existing_access_and_are_reproducible():
    access = {("budi", "ani"), ("sari", "dewi")}

    first = sample_pairs(LECTURERS, STUDENTS, lambda u, o: (u, o) in access, n=200, seed=1)
    second = sample_pairs(LECTURERS, STUDENTS, lambda u, o: (u, o) in access, n=200, seed=1)

    assert first == second
    assert len(first) == 200
    assert not access & set(first)
