"""An unrecognised `response_model:` was swallowed, and a capitalised one was wrong.

`ResponseModel` is a closed enum of four members and three call sites
parsed it as `ResponseModel(raw)` inside a `try/except ValueError` that fell
back to exponential and said nothing. So a value this engine does not know was
not refused, not declined, and not reported.

MEASURED on the shipped `pump_tank_planning` model, one edge's `response_model`
varied and everything else held:

    exponential 8.667
    linear 7.333
    LINEAR 8.667 <- a member of the vocabulary, capitalised
    Linear 8.667
    lienar 8.667
    sigmoid 8.667 (no decline on any of the last four)

The capitalised rows are the sharp ones: `LINEAR` is the author naming a model
this engine HAS, and it came back with a different number than they asked for.
The engine already resolves case across its other closed vocabularies and
already reports an unrecognised value on an indicator; a coupling block simply
had neither.

TWO REPAIRS, NOT ONE, and the tests keep them apart:

  *case is RESOLVED -- `LINEAR` is `linear`, as `_resolve_indicator_type`
    already treats `NUMERIC`;
  *anything else still falls back, because a whole domain failing to load
    over one word is what this loader exists to avoid -- but the fallback is
    now REPORTED, with the accepted set and a did-you-mean.

ABSENT IS NOT UNRESOLVED. An omitted key legitimately defaults and must not be
reported, which is the distinction the indicator-level resolvers already draw.
"""

import pathlib

import pytest

from arbiter_engine import api
from arbiter_engine.temporal.temporal_edge import (
    RESPONSE_MODEL_NAMES,
    ResponseModel,
    TemporalAnnotationStore,
    resolve_response_model,
)
from arbiter_engine.twin.builder import TopologyBuilder

def _example(name: str) -> pathlib.Path:
    """Whichever copy this tree has.

    The built package ships `examples/` at its root and again under
    the package; the tree this is maintained in has it under a publication
    directory, and the suite itself sits one level DEEPER here than it does
    there. Counting parents answers the question in one tree and not the
    other -- caught by the ship leg, which is the lane that runs the published
    layout, with eighteen failures this file could not produce locally.
    Walking for it asks the question that matters in both.
    """
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if (candidate / name).is_file():
            return candidate / name
    raise AssertionError(f"no examples directory in this tree carries {name}")


EXAMPLE = _example("pump_tank_planning.yaml")


def _rule(value=None):
    temporal = {"propagation_delay_s": 60, "time_constant_s": 300}
    if value is not None:
        temporal["response_model"] = value
    return {"type": "drains", "source_type": "Valve", "target_type": "Tank",
            "temporal": temporal}


class TestTheResolverItself:
    """The one place the vocabulary lives, so the three sites cannot disagree."""

    def test_the_accepted_set_is_the_enum(self):
        assert set(RESPONSE_MODEL_NAMES) == {m.value for m in ResponseModel}

    @pytest.mark.parametrize("raw", ["linear", "LINEAR", "Linear", " linear "])
    def test_case_and_surrounding_space_resolve(self, raw):
        model, unresolved = resolve_response_model(raw)
        assert model is ResponseModel.LINEAR
        assert unresolved is None

    @pytest.mark.parametrize("raw", ["lienar", "sigmoid", "exponentail"])
    def test_anything_else_falls_back_and_is_returned_for_reporting(self, raw):
        model, unresolved = resolve_response_model(raw)
        assert model is ResponseModel.EXPONENTIAL
        assert unresolved == raw

    @pytest.mark.parametrize("raw", [None, ""])
    def test_absent_is_not_unresolved(self, raw):
        """Conflating the two would report every edge that never declared one."""
        model, unresolved = resolve_response_model(raw)
        assert model is ResponseModel.EXPONENTIAL
        assert unresolved is None


class TestSiteOneTheTemporalStore:
    """`TemporalAnnotationStore.from_yaml`."""

    def _edge(self, value):
        store = TemporalAnnotationStore.from_yaml([_rule(value)])
        return store.get("Valve", "Tank", "drains")

    def test_a_capitalised_member_is_honoured(self):
        assert self._edge("LINEAR").response_model is ResponseModel.LINEAR

    def test_an_unknown_value_falls_back_rather_than_raising(self):
        assert self._edge("lienar").response_model is ResponseModel.EXPONENTIAL

    def test_an_absent_key_still_defaults(self):
        assert self._edge(None).response_model is ResponseModel.EXPONENTIAL


class TestSiteTwoApplyDeclaredRule:
    """`TwinBuilder._apply_declared_rule`, which overlays a rule onto an edge."""

    def _edge(self, value):
        from arbiter_engine.twin.topology import TwinEdge
        edge = TwinEdge(source_id="valve1", target_id="tank1",
                        relation_type="drains")
        TopologyBuilder._apply_declared_rule(TopologyBuilder(), edge, _rule(value))
        return edge

    def test_a_capitalised_member_is_honoured(self):
        assert self._edge("LINEAR").response_model is ResponseModel.LINEAR

    def test_an_unknown_value_falls_back(self):
        assert self._edge("lienar").response_model is ResponseModel.EXPONENTIAL

    def test_an_absent_key_leaves_what_the_edge_already_carried(self):
        """The one behaviour that differs from site one: this path OVERLAYS,
        so an absent key must not overwrite a model the edge already has."""
        from arbiter_engine.twin.topology import TwinEdge
        edge = TwinEdge(source_id="valve1", target_id="tank1",
                        relation_type="drains")
        edge.response_model = ResponseModel.STEP
        TopologyBuilder._apply_declared_rule(TopologyBuilder(), edge, _rule(None))
        assert edge.response_model is ResponseModel.STEP


class TestSiteThreeTheWholeModelThroughTheVerb:
    """`TwinBuilder._build_edge`, reached the way a caller reaches it."""

    def _objective(self, value, tmp_path):
        path = tmp_path / "m.yaml"
        path.write_text(EXAMPLE.read_text().replace(
            "response_model: exponential", f"response_model: {value}", 1))
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("pump1", "Pump", {"speed_rpm": 3700.0})
        session.add_entity("tank1", "Tank", {"level_pct": 88.0})
        session.add_entity("valve1", "Valve", {"open_pct": 0.0})
        session.add_relationship("pump1", "feeds", "tank1")
        session.add_relationship("valve1", "drains", "tank1")
        plan = api.plan(session, horizon_s=1800.0, step_s=60.0).to_dict()["plan"]
        return plan["candidates"][0]["objective"]

    def test_the_two_members_answer_differently(self, tmp_path):
        """The premise. Without this the rest measures nothing."""
        assert self._objective("exponential", tmp_path) != pytest.approx(
            self._objective("linear", tmp_path))

    @pytest.mark.parametrize("raw", ["LINEAR", "Linear"])
    def test_a_capitalised_member_now_answers_as_that_member(self, raw, tmp_path):
        assert self._objective(raw, tmp_path) == pytest.approx(
            self._objective("linear", tmp_path))


class TestTheFallbackIsReported:
    """The half that makes the remaining fallback honest."""

    def _rows(self, value, tmp_path):
        path = tmp_path / "m.yaml"
        path.write_text(EXAMPLE.read_text().replace(
            "response_model: exponential", f"response_model: {value}", 1))
        session = api.EngineSession()
        session.load_model(str(path))
        payload = api.model_describe(session).to_dict()["model"]
        return [row for row in payload["unread_fields"]
                if row.get("field") == "temporal.response_model"]

    def test_an_unknown_value_is_reported_with_the_accepted_set(self, tmp_path):
        rows = self._rows("sigmoid", tmp_path)
        assert len(rows) == 1
        row = rows[0]
        assert row["reason"] == "unknown_value"
        assert row["value"] == "sigmoid"
        for name in RESPONSE_MODEL_NAMES:
            assert name in row["remedy"], (
                "the remedy must name the accepted set, not just the refusal")

    def test_a_near_miss_gets_a_did_you_mean(self, tmp_path):
        row = self._rows("lienar", tmp_path)[0]
        assert row["did_you_mean"] == "linear"
        assert "did you mean" in row["remedy"]

    def test_a_distant_value_gets_no_suggestion_rather_than_a_bad_one(self, tmp_path):
        assert self._rows("sigmoid", tmp_path)[0]["did_you_mean"] is None

    @pytest.mark.parametrize("raw", ["linear", "LINEAR", "exponential"])
    def test_a_value_the_engine_understands_is_not_reported(self, raw, tmp_path):
        assert self._rows(raw, tmp_path) == [], (
            "resolving a value and then reporting it would make every "
            "capitalised declaration look like a defect")

    def test_the_shipped_example_reports_nothing(self, tmp_path):
        session = api.EngineSession()
        session.load_model(str(EXAMPLE))
        payload = api.model_describe(session).to_dict()["model"]
        assert not [r for r in payload["unread_fields"]
                    if r.get("field") == "temporal.response_model"]
