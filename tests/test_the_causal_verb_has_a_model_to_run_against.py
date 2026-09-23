"""`infer` shipped for six releases with nothing to run it on.

The verb takes a causal graph -- edges an author marked
`edge_direction: causal`, with declared noisy-OR strengths -- and eliminates
over it. A census of the shipped examples found that key in NONE of them, so
the one input the verb is about could not be read anywhere in the package. The
same gap that an internal ruling closed for `rollout` and `plan`, one discipline over, and
found the same way: by reading the verb list against the examples directory.

WHAT THE EXAMPLE HAS TO PROVE, and why a load test would not be enough. The
verb's entire claim to exist is that observing a fault and CAUSING one are
different questions. If the example cannot show two different answers for one
node in one state, it documents a filter over `traverse` and the reader learns
the wrong thing. So the figures below are pinned, not merely produced:

    P(sub-1 faulty) feeder UNOBSERVED 0.014182
    P(sub-1 faulty) feeder OBSERVED at 450 A 0.679054
    P(sub-1 faulty) under `do fdr-1=1` 0.05

The middle and the last put the feeder in the same state and differ by a factor
of thirteen. The first sits BELOW the supply's own 0.05 prior, because two
healthy panels are evidence against a fault upstream of both -- nothing was
declared to make that happen and it is the cheapest check that the graph is
really being eliminated over rather than looked up.

These same three numbers are written in the example's header, for a reader who
runs it. That is a second copy, which this project treats as a defect unless
something holds the two together. This file is that something.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

from arbiter_engine.api import EngineSession, check, infer

EXAMPLE = "substation_feeder.yaml"

#: Measured, then written here and in the example header. Both move together
#: or this file goes red.
EXPECTED = {
    "unobserved": 0.014182,
    "observed": 0.679054,
    "intervened": 0.05,
}


def _examples_dir() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate
    raise AssertionError("no examples directory found in this tree")


def _text() -> str:
    return _examples_dir().joinpath(EXAMPLE).read_text(encoding="utf-8")


def _session(feeder_current=None, panel_v=230.0) -> EngineSession:
    session = EngineSession()
    session.load_model(_text())
    session.add_entity("sub-1", "Supply", properties={"voltage_kv": 11.0})
    session.add_entity("fdr-1", "Feeder", properties=(
        {"current_a": feeder_current} if feeder_current is not None else {}))
    session.add_entity("pnl-1", "Panel", properties={"voltage_v": panel_v})
    session.add_entity("pnl-2", "Panel", properties={"voltage_v": panel_v})
    session.add_relationship("sub-1", "powers", "fdr-1")
    session.add_relationship("fdr-1", "powers", "pnl-1")
    session.add_relationship("fdr-1", "powers", "pnl-2")
    check(session)
    return session


def _posterior(session, **kwargs) -> float:
    leg = infer(session, target="sub-1", **kwargs).to_dict()["inference"]
    assert leg["checked"]["answered"] == 1, leg.get("not_checked")
    return leg["checked"]["posterior"]


class TestSomeShippedExampleDeclaresACausalStructure:
    """The census that was empty, now two-sided: it fails if the example is
    deleted AND it fails if the key it turns on is renamed away."""

    def test_at_least_one_example_declares_a_causal_edge(self):
        declaring = [
            path.name for path in sorted(_examples_dir().glob("*.yaml"))
            if any(str(rule.get("edge_direction", "")) == "causal"
                   for rule in (yaml.safe_load(path.read_text(encoding="utf-8"))
                                ["domain"].get("relationship_rules") or ()))]
        assert declaring, (
            "no shipped example declares `edge_direction: causal`, so `infer` "
            "again has no model to run against")

    def test_every_causal_edge_in_it_declares_its_strength(self):
        """A weight nobody supplied makes the engine decline `cpt_missing`.
        An example that declines is a specimen of the refusal, not of the
        verb."""
        rules = yaml.safe_load(_text())["domain"]["relationship_rules"]
        causal = [r for r in rules if str(r.get("edge_direction", "")) == "causal"]
        assert causal
        for rule in causal:
            assert isinstance(rule.get("causal", {}).get("weight"), (int, float)), rule


class TestTheThreeAnswersTheExampleAdvertises:

    def test_with_the_feeder_unobserved(self):
        assert _posterior(_session()) == pytest.approx(EXPECTED["unobserved"])

    def test_with_the_feeder_observed_faulty(self):
        assert _posterior(_session(450.0)) == pytest.approx(EXPECTED["observed"])

    def test_with_the_feeder_intervened_on(self):
        assert _posterior(_session(), do={"fdr-1": 1}) == pytest.approx(
            EXPECTED["intervened"])

    def test_observing_and_intervening_disagree(self):
        """The claim, stated as the thing a reader can check. Not a repeat of
        the three above: those would all still pass if someone retuned the
        weights until the two answers converged, and the example would then
        teach that the distinction does not matter."""
        observed = _posterior(_session(450.0))
        intervened = _posterior(_session(), do={"fdr-1": 1})
        assert observed > intervened * 5, (
            f"observing gave {observed} and intervening {intervened}; the "
            f"example no longer shows why this verb exists")

    def test_the_headers_figures_are_these_figures(self):
        """The second copy, held. A reader runs what the header says."""
        header = re.split(r"^domain:", _text(), maxsplit=1,
                          flags=re.MULTILINE)[0]
        for label, value in EXPECTED.items():
            assert re.search(rf"(?<![\d.]){value}(?![\d])", header), (
                f"the header does not state the {label} figure {value}")


class TestTheSeverityHalfOfTheEvidenceRule:
    """Documented in `infer` this round, and pinned here because it is the
    part that reads like a broken model when nobody writes it down: only a
    HIGH or CRITICAL finding makes an entity faulty evidence.

    Both panels move, and the question stays on the supply. Breaching the
    TARGET proves nothing -- `infer` drops the target's own observation before
    it answers, correctly, and the first version of this pair did exactly that
    and reported no movement from a critical fault. The rule is about what the
    OTHER nodes contribute."""

    def test_a_warning_level_breach_leaves_the_answer_where_it_was(self):
        warned = _session(panel_v=212.0)
        kinds = [str(f.get("problem_type")) for f in check(warned).to_dict()["findings"]]
        assert kinds and all("warning" in k for k in kinds), kinds
        assert _posterior(warned) == pytest.approx(EXPECTED["unobserved"]), (
            "a warning-level breach changed the posterior, so the rule this "
            "pins is not the rule the engine has")

    def test_a_critical_breach_does_move_it(self):
        """Two-sided: a rule that never fires is not a rule."""
        breached = _session(panel_v=200.0)
        kinds = [str(f.get("problem_type")) for f in check(breached).to_dict()["findings"]]
        assert any("critical" in k for k in kinds), kinds
        moved = _posterior(breached)
        assert moved != pytest.approx(EXPECTED["unobserved"])
        assert moved > EXPECTED["unobserved"], (
            f"two panels failing made an upstream fault LESS likely: {moved}")
