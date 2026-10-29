import demo_office
import make_office as office


def test_the_sign_in_accounts_are_the_people_of_the_cases(tmp_path):
    office.write(tmp_path, *office.build(7))
    cases = office.build(7)[3]
    structure, _ = office.read_graph(tmp_path)

    accounts = demo_office.accounts(cases, structure)["accounts"]

    people = {c["user"] for c in cases["cases"] if c.get("user")} | {c["witness"]["user"] for c in cases["cases"] if "witness" in c}
    assert {a["username"] for a in accounts[:-1]} == {p.split("_", 1)[1].lower() for p in people}
    assert accounts[-1] == {"username": "admin_01", "label": "Corax admin"}
    # role and department only: nothing says which path a person takes
    assert all(", " in a["label"] and "case" not in a["label"].lower() for a in accounts[:-1])
