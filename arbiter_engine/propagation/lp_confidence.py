"""
LP Relaxation for Root Cause Confidence Scores — Strategy 3.

Formulates root cause identification as an Integer Linear Program (ILP),
relaxes to LP, and uses fractional solution values as calibrated confidence
scores. The LP optimal provides a tighter bound than greedy alone.

Uses scipy.optimize.linprog (interior-point method).
"""

import logging
from typing import Any, Dict, List, Optional, Set

from scipy.optimize import linprog
import numpy as np

logger = logging.getLogger(__name__)


def compute_lp_confidence(
    candidate_ids: List[str],
    anomalies: Set[str],
    footprints: Dict[str, Set[str]],
    max_roots: int,
    propagation_probs: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """Compute LP-relaxation confidence scores for root cause candidates.

    The LP relaxation of the set cover ILP provides fractional values
    x_i in [0, 1] for each candidate. These fractional values serve as
    calibrated confidence scores: x_i = 0.83 means "83% confidence that
    entity i is a root cause."

    Parameters
    ----------
    candidate_ids:
        Ordered list of candidate root entity IDs.
    anomalies:
        Set of anomalous entity IDs to explain.
    footprints:
        Mapping of candidate_id → set of anomaly IDs it covers.
    max_roots:
        Maximum number of root causes allowed.
    propagation_probs:
        Optional mapping of candidate_id → propagation probability.
        Used as secondary objective for tiebreaking degenerate LPs.

    Returns
    -------
    Dict mapping candidate_id → confidence score in [0, 1].
    """
    if not candidate_ids or not anomalies:
        return {}

    # Filter to candidates that actually cover something.
    active_candidates = [c for c in candidate_ids if c in footprints and footprints[c]]
    if not active_candidates:
        return {}

    anomaly_list = sorted(anomalies)
    K = len(active_candidates)
    N = len(anomaly_list)

    # Variable layout: [x_0..x_{K-1}, y_0..y_{N-1}]
    # x_i = candidate selection, y_j = anomaly explanation
    num_vars = K + N

    # Objective: maximize Σ y_j + ε·Σ prob_i·x_i
    # linprog minimizes, so negate.
    c = np.zeros(num_vars)
    # Primary: maximize anomaly coverage
    for j in range(N):
        c[K + j] = -1.0
    # Secondary tiebreak: prefer higher probability candidates
    eps = 1e-4
    probs = propagation_probs or {}
    for i, cid in enumerate(active_candidates):
        c[i] = -eps * probs.get(cid, 0.0)

    # Constraints: y_j ≤ Σ_{i: j ∈ footprint(i)} x_i
    # Rewrite as: y_j - Σ x_i ≤ 0
    anomaly_idx = {a: j for j, a in enumerate(anomaly_list)}
    A_ub_rows = []
    b_ub_vals = []

    for j, anomaly_id in enumerate(anomaly_list):
        row = np.zeros(num_vars)
        row[K + j] = 1.0  # y_j
        for i, cid in enumerate(active_candidates):
            if anomaly_id in footprints.get(cid, set()):
                row[i] = -1.0  # -x_i
        A_ub_rows.append(row)
        b_ub_vals.append(0.0)

    # Constraint: Σ x_i ≤ max_roots
    root_row = np.zeros(num_vars)
    for i in range(K):
        root_row[i] = 1.0
    A_ub_rows.append(root_row)
    b_ub_vals.append(float(max_roots))

    A_ub = np.array(A_ub_rows)
    b_ub = np.array(b_ub_vals)

    # Bounds: 0 ≤ x_i ≤ 1, 0 ≤ y_j ≤ 1
    bounds = [(0.0, 1.0)] * num_vars

    try:
        result = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method='highs')
    except Exception as e:
        logger.warning("LP solver failed: %s", e)
        return {}

    if not result.success:
        logger.warning("LP solver did not converge: %s", result.message)
        return {}

    # Extract candidate confidence scores (x_i values).
    confidences: Dict[str, float] = {}
    for i, cid in enumerate(active_candidates):
        confidences[cid] = round(float(result.x[i]), 4)

    return confidences
