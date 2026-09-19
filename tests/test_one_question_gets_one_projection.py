"""The two projection paths answer the same question the same way.

THIS PACKAGE HAD A VERB THAT REFUSED TO GUESS AND A PATH THAT GUESSED
SILENTLY, FOR THE SAME QUESTION.

`projection/runner.py` reads `dynamics:` off an indicator and declines
`model_missing` when there is none -- *no `dynamics` declared, so there is no
model to fit; the engine will not choose one on the author's behalf*. That is
the rule this package states about itself, in `projector.py`'s own opening:
a curve fit is deliberately NOT the default, because *an extrapolated straight
line reports a confident number for a series that is not going anywhere*.

`TopologyTraverser.project_values` did the opposite. It fitted a trend curve
to any series with three readings, whatever the model said. Measured on a
120-sample random walk with nothing declared: `project` declined, and the
traverser returned 2683.89 against a last reading of 2522.40 -- a confident
extrapolation of +161 on a series going nowhere.

WHAT MADE IT URGENT rather than untidy: `rollout(seed_mode="projected")` runs
the traverser's path, and a rollout now FILES its values as predictions. The
engine was scoring itself on numbers nobody had declared a model for, through
a method its own other path argues against.

Both paths now read the one declaration and run the one projector. The design
note asked for this before the traverser's PROJECTED mode could be trusted as
a rollout input; it is now true.
"""
from __future__ import annotations

import random
from datetime import timedelta

import pytest

from arbiter_engine import api

MODEL = """
domain:
  id: onequestion
  name: One declared model, two paths
  entity_types: [Pump]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         window: 2h, horizon: 30m, lookback: 24h%(dynamics)s}
"""

LAST_SEED = 11


def _session(tmp_path, name, dynamics=""):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL % {"dynamics": dynamics})
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": 2000.0})
    rng = random.Random(LAST_SEED)
    now, value = api.now_utc(), 2000.0
    for k in range(120):
        value += rng.gauss(0.0, 20.0)          # a pure random walk
        session.add_observations(
            "pump1", "speed_rpm",
            [(now - timedelta(seconds=60 * (120 - k)), value)])
    return session, value


def _project_verb_median(session):
    api.project(session, horizon_s=1800.0)
    filed = [r for r in session.ledger._records
             if r.kind == "distribution" and r.entity_id == "pump1"
             and not str(r.model_id).startswith("baseline")]
    return filed[-1].quantiles.get("q50") if filed else None


def _traverser_seed(session):
    simulation = api.rollout(session, horizon_s=1800.0, step_s=60.0,
                             seed_mode="projected").to_dict()["simulation"]
    if not simulation["per_step"]:
        return None
    return simulation["per_step"][0]["values"]["pump1"]["speed_rpm"]


def _reasons(session):
    return {d["reason"] for d in api.rollout(
        session, horizon_s=1800.0, step_s=60.0, seed_mode="projected"
    ).to_dict()["simulation"]["not_checked"]}


class TestNeitherPathChoosesAModelForYou:

    def test_the_traverser_refuses_what_the_verb_refuses(self, tmp_path):
        session, _ = _session(tmp_path, "undeclared")
        assert "model_missing" in _reasons(session)

    def test_it_projects_nothing_rather_than_a_curve(self, tmp_path):
        session, last = _session(tmp_path, "nocurve")
        assert _traverser_seed(session) is None, (
            f"a series with no declared model was extrapolated anyway; the "
            f"last reading was {last:.2f}")

    def test_the_refusal_names_the_declaration_not_the_data(self, tmp_path):
        """A remedy saying *collect more data* cannot work here."""
        session, _ = _session(tmp_path, "remedy")
        detail = [d["detail"] for d in api.rollout(
            session, horizon_s=1800.0, step_s=60.0, seed_mode="projected"
        ).to_dict()["simulation"]["not_checked"]
            if d["reason"] == "model_missing"]
        assert detail and "dynamics" in detail[0]


class TestADeclaredModelGivesOneAnswer:

    @pytest.mark.parametrize("model", ["random_walk", "trend"])
    def test_both_paths_return_the_same_number(self, tmp_path, model):
        session, _ = _session(tmp_path, f"agree_{model}",
                              dynamics=f",\n         dynamics: {{model: {model}}}")
        verb = _project_verb_median(session)
        seed = _traverser_seed(session)
        assert verb is not None and seed is not None
        assert seed == pytest.approx(verb, rel=1e-9), (
            f"the `project` verb says {verb} and the rollout seed says "
            f"{seed} for one declared {model} model on one series")

    def test_the_declared_model_is_the_one_that_ran(self, tmp_path):
        """A random walk projects the last reading; a trend does not.

        If the traverser were still curve-fitting regardless, these two
        declarations would return the same number and this would pass
        vacuously — so the test asserts they DIFFER as well as agreeing
        across paths.
        """
        walk_session, last = _session(
            tmp_path, "walkmodel", dynamics=",\n         dynamics: {model: random_walk}")
        trend_session, _ = _session(
            tmp_path, "trendmodel", dynamics=",\n         dynamics: {model: trend}")
        walk = _traverser_seed(walk_session)
        trend = _traverser_seed(trend_session)
        assert walk == pytest.approx(last, rel=1e-6), (
            "a random walk projects the last reading forward")
        assert trend != pytest.approx(walk), (
            "both declarations produced the same number, so the declaration "
            "is not what chose the model")


class TestAFitThatRefusesSaysWhichRefusalItWas:
    """A declared model whose fit refused and an undeclared model are not the
    same fact, and their remedies point in opposite directions."""

    def test_the_projectors_own_reason_is_carried(self, tmp_path):
        # `local_level` has two variance terms that do not separate from a
        # plain random walk; it declines `unidentifiable_parameter`.
        session, _ = _session(tmp_path, "unidentifiable",
                              dynamics=",\n         dynamics: {model: local_level}")
        reasons = _reasons(session)
        assert "unidentifiable_parameter" in reasons
        assert "model_missing" not in reasons, (
            "a model IS declared here; telling the author to declare one "
            "sends them to something already in the file")

    def test_an_unimplemented_model_is_named(self, tmp_path):
        session, _ = _session(tmp_path, "unknownmodel",
                              dynamics=",\n         dynamics: {model: kalman_9000}")
        detail = [d["detail"] for d in api.rollout(
            session, horizon_s=1800.0, step_s=60.0, seed_mode="projected"
        ).to_dict()["simulation"]["not_checked"]
            if d["reason"] == "model_missing"]
        assert detail and "kalman_9000" in detail[0]
