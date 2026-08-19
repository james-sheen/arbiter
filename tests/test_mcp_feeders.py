"""The MCP server can fill its own session.

Verified working and permanently empty as shipped: the protocol round-tripped,
all five tools answered, and the session they answered about could never contain
anything. No tool loaded a model, no tool supplied an entity or an observation,
and `main()` took no model path — so every tool returned `no domain model
loaded` forever and a custom launcher was mandatory before the component could
do anything at all.

An agent cannot write a launcher. It has the tools it is given, which is the
premise of the transport, so a read-only surface over an unfillable session is
not a thin server: it is one that cannot reach its own purpose.

The test that matters here is the last class — a whole session driven through
`dispatch` and nothing else, ending in a finding.

Runs against both trees; see this suite's conftest for why that matters.
"""

import pytest

from arbiter_engine.mcp.server import TOOL_SPECS, dispatch, main
from arbiter_engine.api import EngineSession

EXAMPLE = {
    "domain": {
        "id": "fan-tray", "name": "Fan tray",
        "entity_types": ["Fan"], "relationship_types": [],
        "indicators": {"Fan": [
            {"name": "speed_rpm", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
             "lower_critical": 1000, "window": "1h"},
        ]},
    }
}


class TestTheFeedersAreAdvertised:
    def test_all_three_are_on_the_surface(self):
        """An agent selects on the advertised list. A handler routable through
        `dispatch` but absent from `TOOL_SPECS` is a capability the only client
        that matters cannot see."""
        names = {spec["name"] for spec in TOOL_SPECS}
        assert {"load_model", "add_entity", "add_observations"} <= names

    @pytest.mark.parametrize("name", [
        "load_model", "add_entity", "add_observations"])
    def test_each_declares_a_schema_and_a_description(self, name):
        spec = next(s for s in TOOL_SPECS if s["name"] == name)
        assert spec["description"].strip()
        assert spec["inputSchema"]["type"] == "object"

    def test_the_required_arguments_are_declared(self):
        """A client validates against `inputSchema` before calling. A required
        field left out of the schema surfaces as a KeyError inside the handler,
        which the agent sees as a crash rather than as a correctable mistake."""
        by_name = {s["name"]: s for s in TOOL_SPECS}
        assert by_name["add_entity"]["inputSchema"]["required"] == [
            "entity_id", "entity_type"]
        assert by_name["add_observations"]["inputSchema"]["required"] == [
            "entity_id", "property_name", "values"]


class TestLoadModel:
    def test_an_inline_mapping_loads(self):
        session = EngineSession()
        payload = dispatch(session, "load_model", {"model": EXAMPLE})
        assert payload["model"]["domain_id"] == "fan-tray"

    def test_a_file_path_loads(self, tmp_path):
        import yaml
        path = tmp_path / "fan.yaml"
        path.write_text(yaml.safe_dump(EXAMPLE))
        session = EngineSession()
        payload = dispatch(session, "load_model", {"path": str(path)})
        assert payload["model"]["domain_id"] == "fan-tray"

    def test_it_answers_with_the_description_not_an_acknowledgement(self):
        """An agent's next question after loading is always *what is in it*.
        A bare OK makes the useful answer a second round trip — and a load that
        half worked, parsing but declaring no indicators, would look identical
        to one that worked."""
        session = EngineSession()
        payload = dispatch(session, "load_model", {"model": EXAMPLE})
        assert payload["model"]["indicators"]["Fan"][0]["name"] == "speed_rpm"

    def test_neither_argument_is_reported_rather_than_raised(self):
        session = EngineSession()
        payload = dispatch(session, "load_model", {})
        assert payload["meta"]["source"] == "unavailable"
        assert "path" in payload["meta"]["reason"]

    def test_a_bad_source_is_reported_rather_than_raised(self):
        """A transport that raises gives the agent a stack trace it cannot act
        on. The reason belongs in the envelope, which is the channel this
        engine already uses to say why it could not do something."""
        session = EngineSession()
        payload = dispatch(session, "load_model", {"path": "/no/such.yaml"})
        assert payload["meta"]["source"] == "unavailable"
        assert "FileNotFoundError" in payload["meta"]["reason"]

    def test_a_malformed_model_is_reported_rather_than_raised(self):
        session = EngineSession()
        payload = dispatch(session, "load_model",
                           {"model": {"domain": {"entity_types": "Fan"}}})
        assert payload["meta"]["source"] == "unavailable"


class TestAddObservations:
    def test_timestamped_pairs_survive_json(self):
        """JSON has no tuples, so a pair arrives as a two-element list. The
        session's shape test accepts that already — asserted here because it is
        the transport that makes it load-bearing, and a conversion added
        'helpfully' at this boundary would be the thing that breaks it."""
        session = EngineSession()
        dispatch(session, "load_model", {"model": EXAMPLE})
        dispatch(session, "add_entity",
                 {"entity_id": "fan/1", "entity_type": "Fan"})
        dispatch(session, "add_observations", {
            "entity_id": "fan/1", "property_name": "speed_rpm",
            "values": [[1755604800.0, 3000.0], [1755604860.0, 2900.0]],
        })
        assert session.history.get_observation_count("fan/1", "speed_rpm") == 2

    def test_it_answers_with_gaps_so_an_unread_series_surfaces_at_once(self):
        """`gaps` rather than a count, because it is the tool that reports
        `unconsumed_observations`. A typo'd property name shows up in the reply
        to the call that fed it, instead of waiting for someone to ask."""
        session = EngineSession()
        dispatch(session, "load_model", {"model": EXAMPLE})
        dispatch(session, "add_entity",
                 {"entity_id": "fan/1", "entity_type": "Fan"})
        payload = dispatch(session, "add_observations", {
            "entity_id": "fan/1", "property_name": "speed_rpmm",
            "values": [3000.0, 2900.0],
        })
        unread = payload["unconsumed_observations"]
        assert [r["property"] for r in unread] == ["speed_rpmm"]


class TestTheLauncherArgument:
    def test_a_bad_model_path_refuses_instead_of_serving_an_empty_session(self):
        """A launcher is the one place a failure cannot be reported through the
        envelope, so it fails loudly. Starting a server whose every tool
        answers `no domain model loaded` is exactly the silence this engine
        exists to refuse."""
        assert main(["--model", "/no/such/model.yaml"]) == 2

    def test_the_flag_is_declared(self):
        """`--model` is what a client config names once. Asserted through the
        parser rather than by reading the source, so a rename breaks this."""
        import inspect
        assert '"--model"' in inspect.getsource(main)


class TestAWholeSessionThroughTheTransportAlone:
    """The claim, end to end: no launcher, no direct `EngineSession` calls
    beyond constructing an empty one, ending in a finding."""

    def test_load_feed_and_check(self):
        session = EngineSession()

        described = dispatch(session, "load_model", {"model": EXAMPLE})
        assert described["model"]["entity_types"] == ["Fan"]

        dispatch(session, "add_entity", {
            "entity_id": "fan/1", "entity_type": "Fan",
            "properties": {"speed_rpm": 400.0},
        })
        dispatch(session, "add_observations", {
            "entity_id": "fan/1", "property_name": "speed_rpm",
            "values": [3000.0, 2400.0, 1700.0, 900.0, 400.0],
        })

        result = dispatch(session, "check", {})
        assert [f["problem_type"] for f in result["findings"]] == [
            "below_critical_threshold:speed_rpm"]
        assert result["checked"]["entities"] == 1

    def test_before_the_feeders_this_was_the_only_reachable_answer(self):
        """The defect, pinned as the state a fresh server starts in. Every read
        tool over an unfed session says the same thing, which is correct and
        was previously permanent."""
        session = EngineSession()
        for name in ("model_describe", "check"):
            payload = dispatch(session, name, {})
            assert payload["meta"]["source"] == "unavailable"
