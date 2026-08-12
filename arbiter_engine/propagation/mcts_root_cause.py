"""
Monte Carlo Tree Search for Root Cause Identification — Strategy 5.

Explores the decision tree of "which root to add next" using UCB1
selection, random expansion, greedy rollout, and backpropagation.
Finds beyond-greedy solutions by considering correlated root combinations.

The greedy rollout policy ensures MCTS is at least as good as greedy.
Time-bounded (500ms default) for production use.
"""

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class MCTSNode:
    """A node in the MCTS search tree."""
    selected: Tuple[str, ...]
    uncovered: FrozenSet[str]
    parent: Optional["MCTSNode"] = None
    children: Dict[str, "MCTSNode"] = field(default_factory=dict)
    visits: int = 0
    total_reward: float = 0.0
    untried_actions: Optional[List[str]] = None

    @property
    def is_terminal(self) -> bool:
        return len(self.uncovered) == 0

    @property
    def avg_reward(self) -> float:
        return self.total_reward / self.visits if self.visits > 0 else 0.0


class MCTSRootCause:
    """Monte Carlo Tree Search for root cause set optimization.

    Parameters
    ----------
    exploration_constant:
        UCB1 exploration parameter (default √2).
    max_iterations:
        Maximum MCTS iterations before returning best result.
    max_time_ms:
        Hard time limit in milliseconds.
    """

    def __init__(
        self,
        exploration_constant: float = 1.41,
        max_iterations: int = 1000,
        max_time_ms: float = 500.0,
    ) -> None:
        self.exploration_constant = exploration_constant
        self.max_iterations = max_iterations
        self.max_time_ms = max_time_ms

    def search(
        self,
        anomalies: Set[str],
        footprints: Dict[str, Set[str]],
        max_roots: int = 10,
    ) -> List[str]:
        """Find optimal root cause set via MCTS.

        Parameters
        ----------
        anomalies:
            Set of anomalous entity IDs.
        footprints:
            Mapping candidate_id → set of anomaly IDs it covers.
        max_roots:
            Maximum number of roots to select.

        Returns
        -------
        Ordered list of root entity IDs.
        """
        if not anomalies or not footprints:
            return []

        self._anomalies = frozenset(anomalies)
        self._footprints = footprints
        self._max_roots = max_roots
        self._total_anomalies = len(anomalies)
        self._candidate_list = sorted(footprints.keys())

        root = MCTSNode(
            selected=(),
            uncovered=self._anomalies,
        )

        start_time = time.monotonic()
        deadline_s = self.max_time_ms / 1000.0

        for iteration in range(self.max_iterations):
            if time.monotonic() - start_time >= deadline_s:
                break

            # 1. Selection: UCB1 to find most promising node
            node = self._select(root)

            # 2. Expansion: add one child
            if not node.is_terminal and len(node.selected) < self._max_roots:
                node = self._expand(node)

            # 3. Rollout: simulate to terminal state using greedy policy
            reward = self._rollout(node)

            # 4. Backpropagation: update visit counts and rewards
            self._backpropagate(node, reward)

        # Return best path from root to best terminal
        return self._best_path(root)

    def _select(self, node: MCTSNode) -> MCTSNode:
        """UCB1 tree policy: descend to most promising unexpanded node."""
        while node.children and not node.is_terminal:
            # If there are untried actions, return this node for expansion
            if node.untried_actions is None:
                node.untried_actions = self._get_actions(node)
            if node.untried_actions:
                return node
            # All children expanded: select by UCB1
            node = self._best_ucb1_child(node)
        return node

    def _expand(self, node: MCTSNode) -> MCTSNode:
        """Expand one untried action from the node."""
        if node.untried_actions is None:
            node.untried_actions = self._get_actions(node)

        if not node.untried_actions:
            return node

        action = node.untried_actions.pop()
        new_uncovered = node.uncovered - self._footprints.get(action, set())
        child = MCTSNode(
            selected=node.selected + (action,),
            uncovered=frozenset(new_uncovered),
            parent=node,
        )
        node.children[action] = child
        return child

    def _rollout(self, node: MCTSNode) -> float:
        """Simulate from node to terminal using greedy policy."""
        uncovered = set(node.uncovered)
        selected = list(node.selected)
        used = set(selected)

        while uncovered and len(selected) < self._max_roots:
            best_action = None
            best_new = 0

            for cid in self._candidate_list:
                if cid in used:
                    continue
                new_cov = len(self._footprints.get(cid, set()) & uncovered)
                if new_cov > best_new:
                    best_new = new_cov
                    best_action = cid

            if best_action is None or best_new == 0:
                break

            used.add(best_action)
            selected.append(best_action)
            uncovered -= self._footprints.get(best_action, set())

        return self._reward(len(selected), len(uncovered))

    def _backpropagate(self, node: MCTSNode, reward: float) -> None:
        """Update statistics from node back to root."""
        current: Optional[MCTSNode] = node
        while current is not None:
            current.visits += 1
            current.total_reward += reward
            current = current.parent

    def _best_ucb1_child(self, node: MCTSNode) -> MCTSNode:
        """Select child with highest UCB1 value.

        tuple-key tiebreaker for deterministic + algorithmically-
        sound selection when UCB1 values tie. previously the loop used
        ``if value > best_value:`` (strict greater-than) which kept the
        FIRST-seen child on ties — technically deterministic by dict-
        insertion order but algorithmically arbitrary (a tied child with
        more visits or better reward was passed over for the older
        sibling). Same tied-result-no-tiebreaker archetype as
        (PendingRecommendations.add eviction), (ActionRisk
        priority_score), (Severity.priority_score) — surface
        the tie-resolution semantics in the comparison key.

        Tiebreak order:
          1. UCB1 value (primary objective).
          2. ``child.visits`` — more-explored siblings win (estimate
             confidence; MCTS-standard secondary).
          3. ``child.avg_reward`` — better-performing on tie of visits.
          4. ``child.selected`` tuple — deterministic across runs even
             when all three above tie (rare).
        """
        # Unvisited children: return first one (preserves pre-fix
        # behavior — algorithmically standard "expand untried").
        for child in node.children.values():
            if child.visits == 0:
                return child

        if not node.children:
            return node

        log_parent = math.log(node.visits) if node.visits > 0 else 0.0

        def _ucb1(child: MCTSNode) -> float:
            exploitation = child.total_reward / child.visits
            exploration = self.exploration_constant * math.sqrt(
                log_parent / child.visits
            )
            return exploitation + exploration

        return max(
            node.children.values(),
            key=lambda c: (_ucb1(c), c.visits, c.avg_reward, c.selected),
        )

    def _best_path(self, root: MCTSNode) -> List[str]:
        """Extract best solution by following highest-avg-reward children."""
        node = root
        path: List[str] = []

        while node.children:
            best_child = max(
                node.children.values(),
                key=lambda c: c.avg_reward if c.visits > 0 else -1.0,
            )
            if best_child.visits == 0:
                break
            # Find the action that led to this child
            for action, child in node.children.items():
                if child is best_child:
                    path.append(action)
                    break
            node = best_child

        return path

    def _get_actions(self, node: MCTSNode) -> List[str]:
        """Get available actions (candidates not yet selected)."""
        used = set(node.selected)
        actions = [
            cid for cid in self._candidate_list
            if cid not in used and self._footprints.get(cid, set()) & node.uncovered
        ]
        return actions

    def _reward(self, num_selected: int, num_uncovered: int) -> float:
        """Compute reward: coverage + parsimony."""
        coverage = 1.0 - num_uncovered / self._total_anomalies
        parsimony = 1.0 - num_selected / self._max_roots
        return 0.7 * coverage + 0.3 * parsimony
