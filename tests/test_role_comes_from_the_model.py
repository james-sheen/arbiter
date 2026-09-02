"""A role is an interpretation fact, so it comes from the model or from nowhere.

Two indicators identical in every declared respect and given identical values
were treated differently because of what they were called: one had a role
inferred from a substring of its name and its rule applied, the other declined
for a missing role. Nothing on any queryable surface said which had happened, so
the only visible difference between them was the name.

The published guide refuses this move in as many words -- deriving a
relationship from names is a guess wearing the costume of a derivation -- and
the project rules list property-name normalisation among the hardcoded domain
patterns a domain-agnostic component must not contain. The same shape was
removed from CONSERVATION, which had been rewriting a property name to find the
other half of a balance.

THE COROLLARY IS WORSE THAN THE DEFECT and is what a bridge author needed: the
ABSENCE of a missing-role decline was not evidence that a role was supplied. It
was evidence about the property's name.

SCOPE, STATED BECAUSE IT IS NOT THE WHOLE SYMPTOM. These assert the INDICATOR
path. A separate path walks raw entity properties and still classifies them by
name token, so the reported demonstration still reproduces end to end through
that one.

 NARROWED THAT, and this paragraph said otherwise for a day. The raw walk
was also judging keys that ARE declared indicators, which put a finding and a
`missing_role` decline on one cell. It now skips keys the declared path already
judged, so envelope-level parity DOES hold for an indicator declaring
CONSISTENCY -- pinned in `test_no_cell_is_judged_twice_cd1770.py`. What survives
is the undeclared population, which is and still open.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from arbiter_engine.api import EngineSession, check
from arbiter_engine.ontology.axioms import roles

HEAD = ("domain:\n  id: r\n  name: R\n  entity_types: [Unit]\n"
        "  relationship_types: [feeds]\n  indicators:\n")

#: Names that used to carry a role, paired with names that never did. Same
#: quantity, same value, different word. The axiom travels with the role
#: because a role belongs to ONE of them -- `latency` is RESPONSIVENESS's and
#: declaring it under CONSISTENCY evaluates nothing, correctly.
#: The VALUE travels too, and it has to actually violate the role's rule. A
#: latency of -5 is a fast response, not a fault; asserting `evaluated` on an
#: input that does not violate tests the fixture rather than the engine.
PAIRS = [("error_count", "errors", "count", "CONSISTENCY", -3.0),
         ("failure_pct", "failures", "percentage", "CONSISTENCY", 150.0),
         ("hit_ratio", "hits", "ratio", "CONSISTENCY", 9.9),
         ("response_time_ms", "elapsed", "latency", "RESPONSIVENESS", 500.0)]


def _spec(name, role=None):
    return type("I", (), {"name": name, "role": role})()


@pytest.mark.parametrize("matching,plain,role,axiom,bad", PAIRS)
def test_neither_name_carries_a_role(matching, plain, role, axiom, bad):
    """The parity property, at the level the fix reaches."""
    assert roles.roles_for(_spec(matching)) == roles.roles_for(_spec(plain)) \
        == (frozenset(), "none"), (
        f"{matching!r} and {plain!r} are the same declaration and must resolve "
        f"the same way; a difference here is a fact read out of a name")


@pytest.mark.parametrize("matching,plain,role,axiom,bad", PAIRS)
def test_declaring_the_role_works_for_either_name(matching, plain, role, axiom, bad):
    """The remedy is the declaration, and it must not depend on the name."""
    for name in (matching, plain):
        got, source = roles.roles_for(_spec(name, role))
        assert (got, source) == (frozenset({role}), "declared"), name


def test_roles_for_reports_two_sources_not_three():
    assert {roles.roles_for(_spec(n))[1] for n, _, _, _, _ in PAIRS} == {"none"}
    assert {roles.roles_for(_spec(n, r))[1] for n, _, r, _, _ in PAIRS} == {"declared"}


def test_the_module_holds_no_name_tables():
    """The tables moved to their one remaining consumer. If they come back here
    the inference has come back with them."""
    leaked = [n for n in dir(roles)
              if n.endswith(("_TOKENS", "_SUBSTRINGS")) or n == "name_word_tokens"]
    assert not leaked, f"name-matching tables are back in roles.py: {leaked}"


class TestThroughTheFrontDoor:
    def _run(self, name, axiom, bad, role=None):
        body = (f"    Unit:\n      - name: {name}\n        type: numeric\n"
                + (f"        role: {role}\n" if role else "")
                + f"        warning: 1\n        critical: 2\n"
                + f"        axioms: [{axiom}]\n")
        path = pathlib.Path(tempfile.mktemp(suffix=".yaml"))
        path.write_text(HEAD + body)
        session = EngineSession()
        session.load_model(str(path))
        session.add_entity("u", "Unit", {name: bad})
        return check(session).to_dict()

    @pytest.mark.parametrize("matching,plain,role,axiom,bad", PAIRS)
    def test_an_undeclared_indicator_declines_whatever_it_is_called(
            self, matching, plain, role, axiom, bad):
        for name in (matching, plain):
            reasons = {d["reason"] for d in self._run(name, axiom, bad)["not_checked"]}
            assert "missing_role" in reasons, (
                f"{name!r} was evaluated without the model declaring a role")

    @pytest.mark.parametrize("matching,plain,role,axiom,bad", PAIRS)
    def test_a_declared_indicator_is_evaluated_whatever_it_is_called(
            self, matching, plain, role, axiom, bad):
        for name in (matching, plain):
            out = self._run(name, axiom, bad, role)
            assert out["findings"], f"{name!r} with role {role!r} evaluated nothing"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
