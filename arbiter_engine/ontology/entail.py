"""Derivation over the typed graph: a conjunctive rule, evaluated once, with
every refusal named.

WHAT A RULE MAY BE, AND WHY THE LIMIT IS A COMPLEXITY LIMIT

    rules:
      - name: exposed_to
        head: exposed_to(A, C)
        body: [holds(A, B), clears_at(B, C)]

Three atoms at most, the head predicate may not appear in the body, and no
CYCLE among the declared rules. Those bounds are one bound: a non-recursive
conjunctive query over `n` facts evaluates by nested-loop join in O(n^k) for
`k` body atoms, so capping `k` caps the cost as a polynomial, and forbidding
recursion stops the join being iterated to a fixed point whose depth is not
bounded by the rule.

THE THIRD BOUND WAS MISSING AND THE FIRST TWO COULD NOT SUPPLY IT. A head in
its own body is recursion visible in ONE rule, which is the only kind a
per-rule check can see. Two rules close a loop while neither is recursive
alone, and because `adopt` writes derived edges back into the graph, the next
call joins against them: measured before this bound existed, the derived count
over six adopting passes ran 1, 2, 3, 4, 5 with no decline, stopping only when
the chain ran out of entities. `predicate_cycles` below is the same check at
the level the defect lives at. An ACYCLIC chain of rules is a finite
unrolling, bounded by the rule count rather than the graph, and stays legal --
a finite union of conjunctive queries is still in P.

The project rule this satisfies is stated as *verification stays in P*, and
`first-order` is its shorthand. A body DOES quantify its join variable -- `B`
above is existential -- and that is allowed precisely because the bounds above
keep evaluation polynomial. What stays forbidden is what leaves P: recursion,
an unbounded body, and a constraint whose subject is another constraint.

WHY ABSENCE IS NOT EVIDENCE

A graph holds the edges someone fed it. A rule that finds no binding may be
false, or may be a rule nobody supplied the facts for, and those are different
answers. The author closes a predicate by naming it in `closure:`; for
everything else, an entity that could have bound the first atom and has no
fact under it produces `open_world_undecidable` rather than silence.

WHAT DERIVATION IS FOR

The derived facts, written back to the graph, are the point: a CONNECTIVITY
indicator can then count a `exposed_to` that nobody fed in. Every derived edge
carries the rule and the facts that produced it, so a finding resting on one
can be traced back to the declarations it came from rather than appearing as
an edge with no author.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ..subenvelope import Decline, SubEnvelope
from ..twin.gap import GAP_CONFIDENCE_THRESHOLDS as _GAP_WEIGHT
from ..twin.topology import GapType, TopologyGap, TopologyQuestion
from ..types import Axiom, Severity

__all__ = ["Atom", "Rule", "parse_atom", "parse_rule", "entail",
           "MAX_BODY_ATOMS", "BINDING_BUDGET"]

#: The atom limit, and the reason evaluation stays polynomial. Raising it
#: raises the exponent of the join, which is why it is a constant here and not
#: a parameter a caller can pass.
MAX_BODY_ATOMS = 3

#: How many bindings one rule may produce before the walk stops and says so.
#: The atom cap above makes the worst case a POLYNOMIAL; it does not make it
#: small. Three atoms sharing no variables over 196 facts produce 7.5 million
#: bindings, and over ten thousand facts the figure is not reachable at all.
#: A rule like that is a modelling error, and the useful answer is the refusal
#: naming it rather than a call that does not return.
BINDING_BUDGET = 50_000

_ATOM = re.compile(r"^\s*(\w+)\s*\(\s*([A-Za-z_]\w*)\s*,\s*([A-Za-z_]\w*)\s*\)\s*$")


@dataclass(frozen=True)
class Atom:
    """`pred(Left, Right)`. Binary, because the graph's edges are."""

    pred: str
    left: str
    right: str

    @property
    def variables(self) -> Tuple[str, str]:
        return (self.left, self.right)

    def __str__(self) -> str:
        return f"{self.pred}({self.left}, {self.right})"


@dataclass(frozen=True)
class Rule:
    name: str
    head: Atom
    body: Tuple[Atom, ...]


def parse_atom(text: Any) -> Optional[Atom]:
    """`holds(A, B)` -> Atom, or None when it is not one.

    Returns None rather than raising: a malformed rule is a DECLINE naming the
    rule, not a model that refuses to load. The author's other rules still run.
    """
    match = _ATOM.match(str(text or ""))
    if match is None:
        return None
    return Atom(match.group(1), match.group(2), match.group(3))


def parse_rule(raw: Dict[str, Any]) -> Tuple[Optional[Rule], Optional[str]]:
    """Returns `(rule, None)` or `(None, why it did not parse)`."""
    name = str(raw.get("name") or "")
    if not name:
        return None, "the rule declares no `name`"
    head = parse_atom(raw.get("head"))
    if head is None:
        return None, f"`head` is {raw.get('head')!r}, not `pred(A, B)`"
    body_raw = raw.get("body")
    if not isinstance(body_raw, (list, tuple)) or not body_raw:
        return None, "`body` must be a non-empty list of atoms"
    body = []
    for entry in body_raw:
        atom = parse_atom(entry)
        if atom is None:
            return None, f"body atom {entry!r} is not `pred(A, B)`"
        body.append(atom)
    return Rule(name=name, head=head, body=tuple(body)), None


#: -- the keys a `transitive:` shorthand takes, and nothing else.
_SHORTHAND_KEYS = frozenset({"name", "transitive", "max_hops"})


def expand_rules(raw_rules: Any) -> Tuple[List[Any], List[Decline]]:
    """The declared rules with every `transitive:` shorthand unrolled.

    A ROLL-UP -- *everything within N hops upstream of this* -- is the
    one thing an author reaches for recursion to say, and recursion is what
    keeps this evaluator in P only by its absence. So the shorthand compiles to
    what the author could have written by hand: `{name: upstream_of,
    transitive: feeds, max_hops: 3}` becomes one rule per hop count, each body
    a chain of the BASE predicate alone -- `feeds(X0, X1), feeds(X1, X2)` for
    two hops -- under the head `upstream_of(X0, X2)`. No compiled body names
    the head, so the evaluator never joins against its own output, in one pass
    or in the next after `adopt` writes the derived edges back. A hop count
    whose body passes the atom cap is declined `depth_exceeded` by the same
    rule every other rule meets; a shorthand that cannot be read is
    `malformed_rule`, naming it.
    """
    out: List[Any] = []
    declines: List[Decline] = []
    for raw in raw_rules or ():
        if not isinstance(raw, dict) or "transitive" not in raw:
            out.append(raw)
            continue
        name = raw.get("name")
        base = raw.get("transitive")
        hops = raw.get("max_hops")
        why = ""
        if set(raw) - _SHORTHAND_KEYS:
            why = (f"a `transitive:` rule takes {sorted(_SHORTHAND_KEYS)} and "
                   f"nothing else; got {sorted(set(raw) - _SHORTHAND_KEYS)}")
        elif not isinstance(name, str) or not re.fullmatch(r"\w+", name or ""):
            why = f"`name` is {name!r}; it is the derived predicate, one word"
        elif not isinstance(base, str) or not re.fullmatch(r"\w+", base or ""):
            why = f"`transitive` is {base!r}; it names the predicate to chain"
        elif isinstance(hops, bool) or not isinstance(hops, int) or hops < 1:
            why = (f"`max_hops` is {hops!r}; it is how many edges a derived "
                   f"pair may span, a whole number of at least 1")
        if why:
            declines.append(Decline("malformed_rule", {"rule": str(name or raw)},
                                    detail=why))
            continue
        for k in range(1, hops + 1):
            variables = [f"X{i}" for i in range(k + 1)]
            out.append({
                "name": f"{name}/{k}",
                "head": f"{name}({variables[0]}, {variables[k]})",
                "body": [f"{base}({variables[i]}, {variables[i + 1]})"
                         for i in range(k)],
            })
    return out, declines


def predicate_cycles(rules: Sequence[Rule]) -> List[Tuple[str, ...]]:
    """Predicate cycles across the declared rule SET, shortest first.

    THE PER-RULE CHECK IS THIS CHECK ON A ONE-NODE GRAPH. Refusing a head that
    appears in its own body catches a rule that is recursive BY ITSELF, which
    is the only shape a rule can have when you look at one rule at a time. Two
    rules can be mutually recursive while neither is recursive alone:

        p(A, C) :- q(A, B), link(B, C)
        q(A, C) :- p(A, B), link(B, C)

    Neither head is in its own body, both bodies are inside the atom cap, and
    every static check passes. `entail(adopt=True)` writes derived edges into
    the graph, so the NEXT call joins against them -- and the derived count
    measured over six passes on a seven-entity chain went 1, 2, 3, 4, 5 with
    no decline at all. That is a fixed point whose depth is bounded by the
    DATA rather than by the rules, which is the precise thing the atom cap and
    the recursion refusal exist together to prevent. The single-call guarantee
    was never wrong; it just was not the guarantee anybody needed.

    An acyclic chain is NOT a cycle and stays legal: a rule consuming an
    earlier rule's head is a finite unrolling, its depth bounded by the number
    of rules, and a finite union of conjunctive queries is still in P. Only a
    cycle can iterate, so only a cycle is refused.
    """
    edges: Dict[str, Set[str]] = {}
    for rule in rules:
        for atom in rule.body:
            edges.setdefault(atom.pred, set()).add(rule.head.pred)
        edges.setdefault(rule.head.pred, set())

    found: List[Tuple[str, ...]] = []
    seen: Set[frozenset] = set()
    # Depth-first over a graph whose node count is the number of distinct
    # predicates a model declares -- tens, not thousands. Reporting the PATH
    # rather than a boolean, because *these two rules close a loop* is the
    # only form of this finding an author can act on.
    def walk(node: str, path: List[str], on_path: Set[str]) -> None:
        for nxt in sorted(edges.get(node, ())):
            if nxt in on_path:
                cycle = tuple(path[path.index(nxt):])
                key = frozenset(cycle)
                if key not in seen:
                    seen.add(key)
                    found.append(cycle)
                continue
            walk(nxt, path + [nxt], on_path | {nxt})

    for start in sorted(edges):
        walk(start, [start], {start})
    return sorted(found, key=lambda c: (len(c), c))


def _facts(graph) -> Set[Tuple[str, str, str]]:
    """Every declared edge, as `(predicate, source, target)`."""
    out: Set[Tuple[str, str, str]] = set()
    for source in list(getattr(graph, "edges", {}) or {}):
        for relation in graph.get_relationship_types(source) or ():
            for target in graph.get_relationships(source, relation) or ():
                out.add((str(relation), str(source), str(target)))
    return out


def _join(body: Sequence[Atom], facts: Set[Tuple[str, str, str]],
          budget: int) -> Tuple[List[Dict[str, Any]], bool]:
    """Every binding satisfying every atom. One pass, no fixed point.

    INDEXED ON THE BOUND VARIABLE, which is the difference between a rule that
    runs and one that only finishes in theory. Scanning every fact of a
    predicate at every atom made even a CHAIN -- where each atom shares a
    variable with the last and can only match a handful of facts -- grow
    fourfold when the fact count doubled. Measured: 1.23s over 4,800 facts,
    where the same query indexed is a lookup per step.

    Returns the bindings and whether the BUDGET stopped the walk. The cap on
    body atoms keeps the worst case polynomial -- three atoms sharing no
    variables is O(n^3) -- and polynomial is not the same as affordable: that
    shape produced 7.5 million bindings from 196 facts. A rule nobody can
    afford to evaluate must say so rather than not return.
    """
    by_pred: Dict[str, List[Tuple[str, str, str]]] = {}
    by_left: Dict[Tuple[str, str], List[Tuple[str, str, str]]] = {}
    by_right: Dict[Tuple[str, str], List[Tuple[str, str, str]]] = {}
    for fact in facts:
        pred, source, target = fact
        by_pred.setdefault(pred, []).append(fact)
        by_left.setdefault((pred, source), []).append(fact)
        by_right.setdefault((pred, target), []).append(fact)

    out: List[Dict[str, Any]] = []
    exhausted = False

    def candidates(atom: Atom, binding: Dict[str, Any]):
        left, right = binding.get(atom.left), binding.get(atom.right)
        if left is not None:
            return by_left.get((atom.pred, left), ())
        if right is not None:
            return by_right.get((atom.pred, right), ())
        return by_pred.get(atom.pred, ())

    def walk(index: int, binding: Dict[str, Any], used: Tuple) -> None:
        nonlocal exhausted
        if exhausted:
            return
        if index == len(body):
            if len(out) >= budget:
                exhausted = True
                return
            result = dict(binding)
            result["__used__"] = used
            out.append(result)
            return
        atom = body[index]
        for fact in candidates(atom, binding):
            _, source, target = fact
            extended = dict(binding)
            ok = True
            for variable, value in ((atom.left, source), (atom.right, target)):
                if extended.get(variable, value) != value:
                    ok = False
                    break
                extended[variable] = value
            if ok:
                walk(index + 1, extended, used + (fact,))
            if exhausted:
                return

    walk(0, {}, ())
    return out, exhausted


def _question(gap_type, location: str, description: str, text: str):
    return TopologyQuestion(
        gap=TopologyGap(gap_type=gap_type, location=location,
                        description=description),
        question_text=text, priority=_GAP_WEIGHT.get(gap_type, 0.5),
        context_path=[])


def entail(model, graph, entities) -> Tuple[SubEnvelope, List[Tuple[str, str, str]]]:
    """Evaluate every declared rule. Returns the sub-envelope and the derived
    facts, which the caller writes back -- deriving and ADOPTING are separate,
    as everywhere else here."""
    checked = {"rules_declared": 0, "rules_evaluated": 0,
               "bindings_attempted": 0, "facts_derived": 0}
    declines: List[Decline] = []
    questions: List[Any] = []
    findings: List[Any] = []
    derived: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    facts = _facts(graph)
    declared_predicates = set(model.relationship_types or ())
    closed = set(model.closure or ())
    rules, shorthand_declines = expand_rules(model.rules)
    declines.extend(shorthand_declines)
    checked["rules_declared"] += len(shorthand_declines)

    # THE RULE SET IS THE SUBJECT, not the rule. Built from the rules that
    # would actually RUN -- one that fails to parse or busts the atom cap is
    # refused below and cannot close a loop it never joins. Computed before
    # the loop because a cycle is not a property any single pass through it
    # can see.
    runnable: List[Rule] = []
    for raw in rules:
        candidate, _why = parse_rule(raw)
        if candidate is not None and len(candidate.body) <= MAX_BODY_ATOMS:
            runnable.append(candidate)
    cycles = predicate_cycles(runnable)
    cyclic = {pred for cycle in cycles for pred in cycle}

    for raw in rules:
        checked["rules_declared"] += 1
        rule, why = parse_rule(raw)
        if rule is None:
            declines.append(Decline(
                "malformed_rule", {"rule": str(raw.get("name") or raw)},
                detail=why))
            continue
        if len(rule.body) > MAX_BODY_ATOMS:
            declines.append(Decline(
                "depth_exceeded", {"rule": rule.name},
                detail=(f"{len(rule.body)} body atoms; the limit is "
                        f"{MAX_BODY_ATOMS}, and it is what keeps evaluation "
                        f"polynomial rather than a matter of taste"),
                evidence={"atoms": len(rule.body), "limit": MAX_BODY_ATOMS}))
            continue
        if rule.head.pred in {atom.pred for atom in rule.body}:
            declines.append(Decline(
                "recursion_unsupported", {"rule": rule.name},
                detail=("the head predicate appears in its own body; this "
                        "evaluator runs one pass and does not iterate to a "
                        "fixed point")))
            continue
        if rule.head.pred in cyclic:
            # SAME REASON, wider subject. A consumer matching on the name
            # keeps matching; what changed is that the name now covers the
            # shape rather than the one instance of it that fits in a single
            # rule. Reported with the cycle, because *these predicates close
            # a loop* is the only form of this an author can act on.
            loop = next(c for c in cycles if rule.head.pred in c)
            declines.append(Decline(
                "recursion_unsupported", {"rule": rule.name},
                detail=(f"this rule is part of a predicate cycle "
                        f"{' -> '.join(loop + (loop[0],))}; no rule in it has "
                        f"its head in its own body, but together they derive "
                        f"from their own output. One pass hides that -- "
                        f"`adopt` writes the derived edges back, so the next "
                        f"call joins against them and the depth becomes a "
                        f"property of the data rather than of the rules. An "
                        f"acyclic chain is a finite unrolling and stays "
                        f"legal; a cycle is not"),
                evidence={"cycle": list(loop)}))
            continue
        missing = sorted({atom.pred for atom in rule.body
                          if atom.pred not in declared_predicates})
        if missing:
            declines.append(Decline(
                "rule_unreachable", {"rule": rule.name},
                detail=f"body predicate(s) not declared: {missing}",
                evidence={"missing": missing,
                          "declared": sorted(declared_predicates)}))
            continue

        checked["rules_evaluated"] += 1
        bindings, exhausted = _join(rule.body, facts, BINDING_BUDGET)
        if exhausted:
            declines.append(Decline(
                "binding_budget_exhausted", {"rule": rule.name},
                detail=(f"stopped after {BINDING_BUDGET} bindings; a body whose "
                        f"atoms share no variables is cubic in the facts, and "
                        f"the atom cap bounds that as a polynomial without "
                        f"making it affordable"),
                evidence={"budget": BINDING_BUDGET, "facts": len(facts),
                          "atoms": len(rule.body)}))
        for binding in bindings:
            checked["bindings_attempted"] += 1
            fact = (rule.head.pred,
                    binding.get(rule.head.left), binding.get(rule.head.right))
            if None in fact:
                continue
            derived.setdefault(fact, {
                "rule": rule.name,
                "from": [list(f) for f in binding.get("__used__", ())]})

        # OPEN WORLD. An entity that could have bound the first atom and has no
        # fact under its predicate is not a counterexample -- it is a gap in
        # what was fed in, and only the author can say which.
        first = rule.body[0]
        if first.pred not in closed:
            bound = {source for pred, source, _ in facts if pred == first.pred}
            for entity in entities.values():
                if entity.id not in bound:
                    declines.append(Decline(
                        "open_world_undecidable",
                        {"rule": rule.name, "entity_id": entity.id},
                        detail=(f"no `{first.pred}` fact for this entity, and "
                                f"`{first.pred}` is not in `closure:` -- under "
                                f"an open world that is unknown, not false"),
                        evidence={"predicate": first.pred}))

        if rule.head.pred not in declared_predicates:
            questions.append(_question(
                GapType.MISSING_DECLARATION, rule.head.pred,
                "a rule derives a predicate the model does not declare",
                f"Declare `{rule.head.pred}` in `relationship_types:` so a "
                f"check can read what `{rule.name}` derives."))

    # -- a structural refusal the loader found, reported where the
    # model's structure is: each inherited band a subtype turned into a
    # contradiction. The loader kept the merged indicator, so BOUNDEDNESS
    # declines on it at every check; this names why the band is what it is.
    for conflict in getattr(model, "inheritance_conflicts", None) or ():
        declines.append(Decline(
            "inheritance_conflict",
            {"entity_type": conflict["entity_type"],
             "indicator": conflict["indicator"]},
            detail=conflict["detail"],
            evidence={"extends": conflict["extends"]}))

    checked["facts_derived"] = len(derived)
    findings.extend(_cardinality_contradictions(model, graph, entities, derived))
    return (SubEnvelope("entailment", checked, findings, declines, questions),
            [(fact, meta) for fact, meta in derived.items()])


def _cardinality_contradictions(model, graph, entities, derived) -> List[Any]:
    """Where the rules and the bounds, both declared by the same author, disagree.

    A CONNECTIVITY indicator declaring `max_cardinality` on a relation says how
    many of that edge an entity may have. If the rules DERIVE enough of them to
    pass that number, two declarations in one file contradict each other, and
    the author is the only one who can say which they meant.
    """
    from ..interfaces import Problem
    from ..types import IndicatorType

    bounds: Dict[str, int] = {}
    for specs in (model.indicators or {}).values():
        for spec in specs:
            if (spec.indicator_type is IndicatorType.RELATIONSHIP
                    and spec.relation_type and spec.max_cardinality is not None):
                bounds[spec.relation_type] = min(
                    bounds.get(spec.relation_type, spec.max_cardinality),
                    spec.max_cardinality)
    if not bounds:
        return []

    counts: Dict[Tuple[str, str], int] = {}
    for relation, source, _target in _facts(graph):
        if relation in bounds:
            counts[(source, relation)] = counts.get((source, relation), 0) + 1
    for (relation, source, _target), _meta in derived.items():
        if relation in bounds:
            counts[(source, relation)] = counts.get((source, relation), 0) + 1

    out = []
    for (source, relation), total in sorted(counts.items()):
        limit = bounds[relation]
        if total <= limit:
            continue
        entity = entities.get(source)
        if entity is None:
            continue
        out.append(Problem.from_entity(
            entity, problem_type=f"derived_exceeds_cardinality:{relation}",
            severity=Severity.MEDIUM,
            reason=(f"the rules derive {total} `{relation}` edges from "
                    f"{source}, and an indicator declares at most {limit}"),
            axiom=Axiom.CONNECTIVITY,
            evidence={"relation": relation, "total": total,
                      "max_cardinality": limit,
                      "derived": sum(1 for f in derived if f[0] == relation
                                     and f[1] == source)}))
    return out
