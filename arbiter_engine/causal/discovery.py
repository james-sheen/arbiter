"""Walk the declared numeric series, test which one precedes which, and report
what was not tested as carefully as what was.

THE DENOMINATOR IS THE POINT OF THIS DISCIPLINE. Every other verb here counts
what it evaluated; discovery must also count what it RAN OUT OF BUDGET FOR,
because the pair space is quadratic and the honest answer to *did you look at
everything* is almost always no. `pairs_untested` is that number, and it is
reported beside a decline naming the budget that stopped the walk -- one
decline carrying the count, rather than thousands carrying one each.

DECLARED PAIRS ARE TESTED FIRST, and the ordering is load-bearing rather than
tidy. A budget spent exploring leaves the thing an author most needs -- whether
the edges they DECLARED are supported by their own data -- untested, and a
discipline that only ever proposes additions can never tell you that something
you already believe is unsupported.

NOTHING HERE PROMOTES ITSELF. A significant undeclared pair becomes a question.
A significant same-entity pair becomes a PROPOSED `IORelationship`, offered on
the payload and adopted only when a caller says so. Granger's test measures
predictive precedence and not causation; two series driven by an undeclared
third will show it, which is why `faithfulness_unverifiable` is declined on
every run rather than assumed away in a comment.
"""

from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..derived.indicator import alignment_evidence
from ..subenvelope import Decline, SubEnvelope
from ..types import Axiom, IndicatorType, IORelationship, Severity
from ..twin.gap import GAP_CONFIDENCE_THRESHOLDS as _GAP_WEIGHT
from ..twin.topology import GapType, TopologyGap, TopologyQuestion
from .leadlag import align, lead_lag, stationary

__all__ = ["run_discovery", "MINIMUM_PAIRED_SAMPLES", "DEFAULT_LAGS",
           "DEFAULT_BUDGET_PAIRS"]

#: Paired observations below which neither the stationarity split nor the
#: regression at the longest lag has anything to say. A floor that makes the
#: engine DECLINE, never one that makes it answer.
MINIMUM_PAIRED_SAMPLES = 120

#: The lag family tested when a caller names none. Every one of them costs a
#: test, and the p-value is corrected for the size of this set -- so widening
#: it is not free and the correction says so.
DEFAULT_LAGS: Tuple[int, ...] = (1, 2, 5, 10)

#: How many pairs one call will test. The space is quadratic in declared
#: series, so this is a stop, not a target; whatever it cuts off is counted.
DEFAULT_BUDGET_PAIRS = 500


def _numeric_series(session) -> List[Tuple[Any, Any]]:
    """Every (entity, declared numeric indicator) this model carries."""
    out = []
    for entity in session.entities.values():
        for spec in session.model.indicators.get(entity.type, []) or []:
            if spec.indicator_type is IndicatorType.NUMERIC:
                out.append((entity, spec))
    return out


def _declared_edge(graph, a_id: str, b_id: str) -> Optional[str]:
    """The relation type declared from `a_id` to `b_id`, or None.

    `get_relationships` returns TARGET IDS, not `(relation, target)` pairs.
    An earlier version of this unpacked them as pairs, which does not raise --
    a two-character id unpacks into two characters -- so every edge in the
    model read as undeclared and the discipline could only ever propose, never
    challenge. Nothing about that failure was visible in a count.
    """
    for relation in graph.get_relationship_types(a_id) or ():
        if b_id in (graph.get_relationships(a_id, relation) or ()):
            return relation
    return None


def _ordered_pairs(session, series) -> List[Tuple[Any, Any, Any, Any, Optional[str]]]:
    """Ordered pairs of series, DECLARED EDGES FIRST, then everything else."""
    declared, other = [], []
    for i, (entity_a, spec_a) in enumerate(series):
        for j, (entity_b, spec_b) in enumerate(series):
            if i == j:
                continue
            if entity_a.id == entity_b.id and j < i:
                continue          # one direction per same-entity property pair
            relation = (_declared_edge(session.graph, entity_a.id, entity_b.id)
                        if entity_a.id != entity_b.id else None)
            row = (entity_a, spec_a, entity_b, spec_b, relation)
            (declared if relation else other).append(row)
    return declared + other


def _question(gap_type, location: str, description: str, text: str):
    return TopologyQuestion(
        gap=TopologyGap(gap_type=gap_type, location=location,
                        description=description),
        question_text=text, priority=_GAP_WEIGHT.get(gap_type, 0.5),
        context_path=[])


def _pearson(x, y) -> float:
    try:
        return float(statistics.correlation(list(x), list(y)))
    except (statistics.StatisticsError, ValueError, ZeroDivisionError):
        return 0.0


def run_discovery(session, alpha: Optional[float] = None,
                  lags: Sequence[int] = DEFAULT_LAGS,
                  budget_pairs: int = DEFAULT_BUDGET_PAIRS,
                  window=None) -> Tuple[SubEnvelope, List[IORelationship]]:
    """Test lead-lag across declared numeric series.

    Returns the sub-envelope AND the `IORelationship` records it PROPOSES.
    They are returned rather than applied: a proposal is not a declaration, and
    the only thing that changes what gets checked is a caller adopting them.
    """
    checked = {"pairs_seen": 0, "pairs_tested": 0, "pairs_untested": 0,
               "tests_run": 0}
    findings: List[Any] = []
    declines: List[Decline] = []
    questions: List[Any] = []
    proposals: List[IORelationship] = []

    if session.model is None:
        return SubEnvelope("discovery", {"pairs_seen": 0}, source="unavailable",
                           reason="no domain model loaded"), []

    series = _numeric_series(session)
    results = []
    # Same clock for both legs of every pair -- see `reading_history`.
    history = session.reading_history()
    for entity_a, spec_a, entity_b, spec_b, relation in _ordered_pairs(session, series):
        checked["pairs_seen"] += 1
        pair_name = (f"{entity_a.id}.{spec_a.property_name}"
                     f"->{entity_b.id}.{spec_b.property_name}")
        scope = {"pair": pair_name}

        if checked["pairs_tested"] >= budget_pairs:
            checked["pairs_untested"] += 1
            continue

        span = window or spec_a.lookback or spec_a.time_window
        if span is None:
            checked["pairs_untested"] += 1
            continue
        xa, xb = align(
            history.get_values(entity_a.id, spec_a.property_name, span),
            history.get_values(entity_b.id, spec_b.property_name, span))
        if len(xa) < MINIMUM_PAIRED_SAMPLES:
            # PER SIDE, because a pair has two series and either can be the
            # derived one that failed to join. One merged figure would say a
            # join went empty without saying whose.
            evidence: Dict[str, Any] = {"paired": int(len(xa)),
                                        "required": MINIMUM_PAIRED_SAMPLES}
            for side, entity, spec in (("a", entity_a, spec_a),
                                       ("b", entity_b, spec_b)):
                figures = alignment_evidence(
                    history, entity.id, spec.property_name, span)
                if figures:
                    evidence[f"alignment_{side}"] = figures
            declines.append(Decline("insufficient_samples", scope,
                                    evidence=evidence))
            continue

        ok_a, ev_a = stationary(list(xa))
        ok_b, ev_b = stationary(list(xb))
        if not (ok_a and ok_b):
            declines.append(Decline(
                "nonstationary_series", scope,
                detail="difference or window the series; the tests are invalid as-is",
                evidence={"left": ev_a, "right": ev_b}))
            continue

        checked["pairs_tested"] += 1
        forward = lead_lag(xa, xb, lags)
        reverse = lead_lag(xb, xa, lags)
        checked["tests_run"] += len(forward["per_lag"]) + len(reverse["per_lag"])
        results.append((entity_a, spec_a, entity_b, spec_b, relation,
                        forward, reverse, scope, pair_name, xa, xb))

    if alpha is None:
        # THE SAME RULE `project` FOLLOWS. The tests ran and their p-values are
        # reported; what is missing is the level at which one counts, which is
        # a statement about how much a false edge costs here. The engine will
        # not choose it and call the result a finding.
        declines.append(Decline(
            "no_significance_level", {"scope": "all"},
            detail="pass `alpha` to say which corrected p-value counts as support",
            evidence={"pairs_with_results": len(results),
                      "corrected_p": sorted(round(r[5]["p_corrected"], 6)
                                            for r in results)[:20]}))
        if results:
            questions.append(_question(
                GapType.MISSING_THRESHOLD, "discovery",
                "no significance level declared for lead-lag support",
                "At what corrected p-value does a lead-lag result count as "
                "support? Pass `alpha` to `discover`."))
    else:
        for (ea, sa, eb, sb, relation, fwd, rev, scope, pair_name,
             xa, xb) in results:
            fwd_sig = fwd["p_corrected"] < alpha
            rev_sig = rev["p_corrected"] < alpha
            if fwd_sig and rev_sig:
                declines.append(Decline(
                    "orientation_undetermined", scope,
                    detail="both directions are supported; the data does not orient this pair",
                    evidence={"p_forward": fwd["p_corrected"],
                              "p_reverse": rev["p_corrected"], "alpha": alpha}))
                continue
            if relation and not fwd_sig:
                findings.append(_unsupported(ea, sa, eb, sb, relation, fwd, alpha))
            elif not relation and fwd_sig:
                if ea.id == eb.id:
                    proposals.append(_io_relationship(ea, sa, sb, fwd, xa, xb))
                    questions.append(_question(
                        GapType.MISSING_PROPERTY, pair_name,
                        "an untested lead-lag between two properties of one entity",
                        f"Does {ea.id}.{sa.property_name} lead "
                        f"{sb.property_name} by {fwd['lag']} samples?"))
                else:
                    questions.append(_question(
                        GapType.MISSING_EDGE, f"{ea.id}->{eb.id}",
                        "proposed by a lead-lag test, not declared",
                        f"Does {ea.id}.{sa.property_name} drive "
                        f"{eb.id}.{sb.property_name}?"))

    if checked["pairs_untested"]:
        declines.append(Decline(
            "untested_pair", {"scope": "all"},
            detail=f"the budget of {budget_pairs} tested pairs stopped the walk",
            evidence={"untested": checked["pairs_untested"],
                      "seen": checked["pairs_seen"],
                      "budget_pairs": budget_pairs}))

    # DECLINED ON EVERY RUN, and deliberately not conditional. Faithfulness --
    # that the data's independences are the model's independences -- is what
    # licenses reading any of this as structure, and it cannot be tested from
    # observational data. A discipline that assumed it silently would be
    # asserting its own precondition.
    declines.append(Decline(
        "faithfulness_unverifiable", {"scope": "all"},
        detail=("assumed, and not testable from observational data; a pair "
                "driven by an undeclared third series shows the same result")))
    declines.extend(_confounding_warnings(results, alpha))

    return SubEnvelope("discovery", checked, findings, declines, questions), proposals


def _confounding_warnings(results, alpha) -> List[Decline]:
    """A pair is flagged when some third series precedes BOTH of its ends.

    Not proof of confounding -- nothing observational is -- but it is the one
    case the run has already measured and can name, and it is the difference
    between an author reading a proposal as a finding and reading it as a lead.
    """
    if alpha is None:
        return []
    leads = {}
    for ea, sa, eb, sb, _rel, fwd, _rev, _scope, _name, _xa, _xb in results:
        if fwd["p_corrected"] < alpha:
            leads.setdefault((ea.id, sa.property_name), set()).add(
                (eb.id, sb.property_name))
    out = []
    for ea, sa, eb, sb, _rel, fwd, _rev, scope, _name, _xa, _xb in results:
        if fwd["p_corrected"] >= alpha:
            continue
        left, right = (ea.id, sa.property_name), (eb.id, sb.property_name)
        common = [src for src, targets in leads.items()
                  if src not in (left, right)
                  and left in targets and right in targets]
        if common:
            out.append(Decline(
                "latent_confounding_possible", scope,
                detail="a third series precedes both ends of this pair",
                evidence={"common_antecedents": [f"{e}.{p}" for e, p in common]}))
    return out


def _unsupported(ea, sa, eb, sb, relation, fwd, alpha):
    from ..interfaces import Problem
    return Problem.from_entity(
        eb, problem_type=f"declared_edge_unsupported:{relation}",
        severity=Severity.MEDIUM,
        reason=(f"{ea.id} {relation} {eb.id} is declared; "
                f"{sa.property_name} shows no lead over {sb.property_name} "
                f"(corrected p = {fwd['p_corrected']:.3f})"),
        axiom=Axiom.CONNECTIVITY,
        evidence={"relation": relation, "source": ea.id,
                  "p_corrected": fwd["p_corrected"], "p_raw": fwd["p_raw"],
                  "alpha": alpha, "lag": fwd["lag"], "n": fwd["n"],
                  "lags_tested": fwd["lags_tested"]})


def _io_relationship(entity, spec_in, spec_out, fwd, xa, xb) -> IORelationship:
    return IORelationship(
        input_entity_type=entity.type, output_entity_type=entity.type,
        input_property=spec_in.property_name,
        output_property=spec_out.property_name,
        correlation=_pearson(xa, xb),
        lag_seconds=float(fwd["lag"]),
        granger_p_value=fwd["p_corrected"],
        confidence=1.0 - fwd["p_corrected"],
        llm_validated=False,
        validation_reason="proposed by a lead-lag test; not adopted")
