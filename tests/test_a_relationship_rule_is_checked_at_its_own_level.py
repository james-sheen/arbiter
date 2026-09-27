"""A relationship rule's own keys, and its `causal:` block, were checked against nothing.

An internal ruling compared the blocks INSIDE a rule -- `temporal:` and
`transition:` -- against the keys the builder reads, and checked their
one closed value. The rule's own level, and the `causal:` block beside those
two, were compared against nothing. Measured on one causal rule declaring
`weight: 0.7` and `leak: 0.02`, with `unread_fields` empty every time and the
key named nowhere in `model_describe`:

  - `source:` -- the word a `transition:` block and an action template both
    read for provenance -- was ignored;
  - `lek: 0.5` left the leak at the engine's 0.01, so an observed posterior
    read 0.04465 where the declaration gives 0.5175;
  - `latent_confounder` inside `causal:`, WHERE THE GUIDE'S OWN EXAMPLE PUT IT,
    was ignored, so `do()` answered 0.706 for a query the confounder makes
    unidentifiable;
  - `edge_direction: casual` left the edge structural, and `infer` asked the
    author to declare the very thing they had declared.

`match`, `source_property` and `target_property` pass BY NAME. They belong to
another reader -- the orchestrator's edge derivation -- and 53 of the 58 rules
measured beside this engine carry them, so reporting each would bury every row
above under 107 that are valid in the schema their authors wrote.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest
import yaml

from arbiter_engine.api import (EngineSession, check, infer,
                                            model_describe)
from arbiter_engine.ontology.domain_loader import (
    _KNOWN_RULE_CAUSAL_KEYS, _KNOWN_RULE_KEYS, _NON_ENGINE_RULE_KEYS,
    is_domain_model, load_domain)
from arbiter_engine.twin.topology import EdgeDirection, FlowType

RULE = {"type": "serves", "source_type": "Feed", "target_type": "Strategy",
        "edge_direction": "causal", "causal": {"weight": 0.7, "leak": 0.02}}


def _session(rules):
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Feed", "Strategy"],
        "relationship_types": ["serves"], "indicators": {},
        "relationship_rules": list(rules)}})
    session.add_entity("feed1", "Feed")
    session.add_entity("strat1", "Strategy")
    session.add_relationship("feed1", "serves", "strat1")
    return session


def _rule(**changes):
    rule = {k: (dict(v) if isinstance(v, dict) else v) for k, v in RULE.items()}
    for key, value in changes.items():
        if value is None:
            rule.pop(key, None)
        else:
            rule[key] = value
    return rule


def _rows(rules, reason=None):
    rows = model_describe(_session(rules)).to_dict()["model"]["unread_fields"]
    return [r for r in rows if reason is None or r["reason"] == reason]


def _named(rules, reason=None):
    return {r["field"]: r.get("did_you_mean") for r in _rows(rules, reason)}


class TestTheRuleItselfIsChecked:

    def test_a_misspelled_key_is_caught_with_a_suggestion(self):
        rule = _rule(edge_direction=None, edge_directon="causal")
        assert _named([rule]) == {"edge_directon": "edge_direction"}

    def test_a_provenance_word_is_reported_without_a_guess(self):
        """The instance that found this: `source:` on a causal rule. No block
        the rule declares reads it, so it is not sent anywhere."""
        row, = _rows([_rule(source="runbook p.4")])
        assert (row["field"], row["reason"], row["did_you_mean"]) == (
            "source", "unknown_key", None)
        assert row["rule"] == "Feed-serves->Strategy"

    def test_another_readers_keys_pass_by_name(self):
        rule = _rule(match="property", source_property="feed_id",
                     target_property="id")
        assert _named([rule]) == {}

    def test_a_misspelling_of_another_readers_key_is_still_caught(self):
        assert _named([_rule(source_proprety="feed_id")]) == {
            "source_proprety": "source_property"}


class TestTheCausalBlockIsChecked:

    def test_a_misspelled_leak_is_caught(self):
        """The one that moved a posterior by an order of magnitude."""
        rule = _rule(causal={"weight": 0.7, "lek": 0.5})
        assert _named([rule]) == {"causal.lek": "leak"}

    def test_a_misspelled_weight_is_caught(self):
        rule = _rule(causal={"wieght": 0.7, "leak": 0.02})
        assert _named([rule]) == {"causal.wieght": "weight"}

    def test_a_declared_block_reports_nothing(self):
        assert _named([_rule()]) == {}


class TestAKeyAtTheWrongLevelIsToldWhereItIsRead:

    def test_the_confounder_inside_causal_is_sent_to_the_rule(self):
        rule = _rule(causal={"weight": 0.7, "leak": 0.02,
                             "latent_confounder": "ClearingHouse"})
        row, = _rows([rule])
        assert (row["field"], row["did_you_mean"]) == (
            "causal.latent_confounder", "latent_confounder")
        assert "move it" in row["remedy"]

    def test_where_it_is_sent_is_where_it_is_read(self):
        """The suggestion is only worth giving if following it works: on the
        rule itself the confounder reports nothing and blocks the
        intervention."""
        session = _session([_rule(latent_confounder="ClearingHouse")])
        assert model_describe(session).to_dict()["model"]["unread_fields"] == []
        payload = infer(session, "strat1", do={"feed1": 1}).to_dict()
        reasons = {d["reason"] for d in payload["inference"]["not_checked"]}
        assert "not_identifiable" in reasons

    def test_a_weight_on_the_rule_is_sent_into_causal(self):
        assert _named([_rule(weight=0.7)]) == {"weight": "causal.weight"}

    def test_a_block_the_rule_does_not_declare_is_never_suggested(self):
        assert _named([_rule(causal=None, weight=0.7)]) == {"weight": None}


class TestAClosedValueIsCheckedAsTheReadersReadIt:

    def test_a_misspelled_direction_is_reported_and_dropped(self):
        rule = _rule(edge_direction="casual")
        assert _named([rule], "unknown_value") == {"edge_direction": "causal"}
        dropped = check(_session([rule])).to_dict()["dropped_declarations"]
        assert [(r["field"], r["value"]) for r in dropped] == [
            ("edge_direction", "casual")]

    def test_a_capitalised_direction_is_reported_because_it_is_not_applied(self):
        """The check is exactly as strict as the readers. `Causal` makes no
        causal edge, so passing it here would report a clean model that
        inference then ignores."""
        rule = _rule(edge_direction="Causal")
        assert _named([rule], "unknown_value") == {"edge_direction": "causal"}
        payload = infer(_session([rule]), "strat1").to_dict()
        assert payload["inference"]["checked"]["causal_edges"] == 0

    def test_a_misspelled_flow_type_is_reported(self):
        assert _named([_rule(flow_type="masss")], "unknown_value") == {
            "flow_type": "mass"}

    @pytest.mark.parametrize("key, value", [
        *(("edge_direction", member.value) for member in EdgeDirection),
        *(("flow_type", member.value) for member in FlowType),
    ])
    def test_every_member_passes(self, key, value):
        assert _named([_rule(**{key: value})], "unknown_value") == {}


class TestARuleThatIsNotAMappingIsReported:

    def test_a_bare_word_is_reported_and_the_rest_still_load(self):
        rows = _rows(["serves", _rule()], "unknown_value")
        assert [(r["field"], r["value"]) for r in rows] == [
            ("relationship_rules[0]", "serves")]
        payload = infer(_session(["serves", _rule()]), "strat1").to_dict()
        assert payload["inference"]["checked"]["causal_edges"] == 1

    def test_an_empty_entry_says_so(self):
        row, = _rows([None, _rule()], "unknown_value")
        assert row["field"] == "relationship_rules[0]"
        assert "empty" in row["remedy"]


class TestAListOfTransitionsIsCheckedLikeOne:
    """The builder takes a list of `transition:` blocks, one per property a
    relationship drives, and only the single mapping was ever checked."""

    def test_a_misspelled_spread_inside_a_list_is_caught(self):
        good = {"from": "speed_rpm", "to": "level_pct", "gain": 0.02,
                "source": "datasheet"}
        model = load_domain({"domain": {
            "id": "t", "name": "t", "entity_types": ["Pump", "Tank"],
            "relationship_types": ["feeds"],
            "indicators": {
                "Pump": [{"name": "speed_rpm", "type": "NUMERIC",
                          "axioms": ["BOUNDEDNESS"], "critical": 9e9}],
                "Tank": [{"name": "level_pct", "type": "NUMERIC",
                          "axioms": ["BOUNDEDNESS"], "critical": 95}]},
            "relationship_rules": [{
                "type": "feeds", "source_type": "Pump", "target_type": "Tank",
                "transition": [dict(good, gain_sgima=0.002), dict(good)]}],
        }})
        assert {r["field"]: r["did_you_mean"] for r in model.unread_fields()} == {
            "transition[0].gain_sgima": "gain_sigma"}


def _literals_read_off(module, varname):
    """Literal keys read off `varname` in `module`, by `.get()` or subscript.

    The imports above are DOTTED absolute imports, which is what lets one file
    run against both package roots this suite is derived into.
    """
    tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == varname
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            found.add(node.args[0].value)
        if (isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == varname
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            found.add(node.slice.value)
    return found


class TestTheKeySetsAreWhatTheReadersRead:
    """Derived, in both directions. A key a reader takes and the set lacks is
    reported as unread; a key in the set that no reader takes is the silence
    this check exists to end."""

    def test_the_rule_level_set_is_what_the_five_readers_read(self):
        from arbiter_engine import api, surprises
        from arbiter_engine.inference import causal
        from arbiter_engine.temporal import temporal_edge
        from arbiter_engine.twin import builder
        read = set()
        for module in (builder, causal, temporal_edge, surprises, api):
            read |= _literals_read_off(module, "rule")
        assert read == set(_KNOWN_RULE_KEYS)

    def test_the_causal_set_is_what_inference_reads(self):
        from arbiter_engine.inference import causal
        assert _literals_read_off(causal, "causal") == set(
            _KNOWN_RULE_CAUSAL_KEYS)

    def test_a_key_let_through_by_name_is_read_by_no_engine_reader(self):
        assert not _KNOWN_RULE_KEYS & _NON_ENGINE_RULE_KEYS


def _model_files():
    here = pathlib.Path(__file__).resolve()
    found = []
    for directory in (here.parents[1] / "examples", here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example",
                      here.parents[2] / "domains"):
        if directory.is_dir():
            found += sorted(directory.glob("*.yaml"))
    found += sorted((here.parents[2] / "docs" / "publication").glob(
        "appendix-*.yaml"))
    return found


def _guide():
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "MODELING.md",
                      here.parents[2] / "docs" / "publication"
                      / "domain-model-spec.md"):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError("no modelling guide found to check against")


#: A commented-out key in a guide example -- how the guide shows an OPTIONAL one.
_COMMENTED_KEY = re.compile(r"^(\s*)#\s?([a-z_]+:(?:\s.*)?)$")


def _rule_rows(model):
    return [r for r in model.unread_fields()
            if r.get("rule") or r["field"].startswith("relationship_rules[")]


class TestWhatShipsIsQuiet:

    def test_every_model_beside_this_engine_reports_no_rule_row(self):
        checked = 0
        for path in _model_files():
            if not is_domain_model(path):
                continue
            model = load_domain(path)
            assert _rule_rows(model) == [], path.name
            checked += len(model.relationship_rules)
        assert checked >= 5, "no example rule was found to check"

    def test_the_guide_teaches_every_rule_key_where_it_is_read(self):
        """With its commented options switched ON, because that is how the
        guide shows an optional key -- and how it showed `latent_confounder`
        one level too deep, where a check of names and uncommented lines
        could not see it."""
        rules = []
        for block in re.findall(r"```yaml\n(.*?)```", _guide(), re.S):
            if "relationship_rules:" not in block:
                continue
            live = "\n".join(_COMMENTED_KEY.sub(r"\1\2", line)
                             for line in block.split("\n"))
            doc = yaml.safe_load(live)
            holder = doc.get("domain", doc) if isinstance(doc, dict) else {}
            rules += list(holder.get("relationship_rules") or [])
        assert any("latent_confounder" in rule for rule in rules)
        types = sorted({rule[k] for rule in rules
                        for k in ("source_type", "target_type")})
        model = load_domain({"domain": {
            "id": "guide", "name": "guide", "entity_types": types,
            "relationship_types": sorted({rule["type"] for rule in rules}),
            "relationship_rules": rules}})
        assert _rule_rows(model) == []
