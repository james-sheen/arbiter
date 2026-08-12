"""
Observation History Storage.

Provides storage and retrieval of historical observations for
axiom reasoning and statistical detection.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
import threading

from ..interfaces import Observation, ObservationHistory

logger = logging.getLogger(__name__)


class InMemoryObservationHistory(ObservationHistory):
    """
    In-memory implementation of ObservationHistory.

    Suitable for development and single-instance deployments.
    For production, use TimescaleDB or similar time-series database.

    Thread-safe with read-write locks.
    """

    def __init__(
        self,
        max_observations_per_key: int = 10000,
        retention_period: timedelta = timedelta(days=7),
        max_total_observations: int = 5_000_000,  # Global memory bound
        cluster_id: Optional[str] = None,  # (Bucket A)
    ):
        # this history is stored per-cluster in
        # core._observation_histories[cluster_id], so it inherently belongs
        # to one cluster — stamp its production-observation emissions with it
        # (Layer 3). Cross-cluster merge / transient histories construct with
        # cluster_id=None (correctly unstamped).
        self._cluster_id = cluster_id
        self.max_observations = max_observations_per_key
        self.retention_period = retention_period
        self._max_total_observations = max_total_observations  #
        self._total_observation_count = 0  # Running total

        # Storage: (entity_id, property_name) -> [(timestamp, value)]
        self._history: Dict[Tuple[str, str], List[Tuple[datetime, Any]]] = defaultdict(list)

        # Observation counts for readiness tracking
        self._observation_counts: Dict[Tuple[str, str], int] = defaultdict(int)

        # Entity metadata
        self._entity_metadata: Dict[str, Dict[str, Any]] = {}

        # Thread lock
        self._lock = threading.RLock()

        # silent-destructive-eviction archetype family **7th member**
        # (ScenarioStore + PendingRecommendations +
        # EventBuffer + _rollback_history + _snapshots/_change_history
        # + TopologySnapshotStore + _evict_oldest_keys). previously
        # the eviction in `_evict_oldest_keys` dropped (entity_id,
        # property_name) keys silently when the global max was hit; operators
        # diagnosing "axiom readiness dropped suddenly" / "indicator history
        # vanished" had no signal pointing at memory-bound eviction.
        # Heartbeat-paced cadence (add() is
        # called on every metric flush — high frequency).
        self._eviction_wave_count: int = 0
        self._total_observations_evicted: int = 0
        self._total_keys_evicted: int = 0

        # per-key trim visibility. previously the per-key
        # trim at the ``add()`` boundary was silent — operators
        # debugging "why does this property's history look truncated"
        # couldn't tell whether the trim was firing or whether the
        # history simply hadn't accumulated yet. Pre-audit refined
        # the scout's "race" framing: there is no actual race
        # (per-key trim DECREMENTS _total_observation_count so
        # single-key floods are absorbed in-place; global eviction
        # correctly stays silent). The real residual is just
        # visibility — surface the per-key trim counts via lifetime
        # counters + periodic INFO log every 10k trims.
        self._total_per_key_trim_waves: int = 0
        self._total_per_key_observations_trimmed: int = 0

    def add(
        self,
        entity_id: str,
        property_name: str,
        value: Any,
        timestamp: Optional[datetime] = None
    ) -> None:
        """Add an observation to history."""
        timestamp = timestamp or datetime.utcnow()
        key = (entity_id, property_name)

        with self._lock:
            self._history[key].append((timestamp, value))
            self._observation_counts[key] += 1
            self._total_observation_count += 1

            # Enforce per-key max observations
            if len(self._history[key]) > self.max_observations:
                trimmed = len(self._history[key]) - self.max_observations
                self._history[key] = self._history[key][-self.max_observations:]
                self._total_observation_count -= trimmed
                # surface per-key trim activity via lifetime
                # counters + first-occurrence INFO log + heartbeat every
                # 10000 waves (per-key trim is high-frequency on
                # flood-heavy keys; 10k cadence balances visibility vs
                # log volume).
                self._total_per_key_trim_waves += 1
                self._total_per_key_observations_trimmed += trimmed
                first_wave = self._total_per_key_trim_waves == 1
                every_10k = self._total_per_key_trim_waves % 10000 == 0
                if first_wave or every_10k:
                    logger.info(
                        "InMemoryObservationHistory per-key trim "
                        "for %r: trimmed %d observations this wave "
                        "(wave=%d, total_observations_trimmed=%d, "
                        "key now at %d observations). Repeated trims on "
                        "the same key indicate a flood — single-key "
                        "floods are absorbed in-place by per-key trim "
                        "and do NOT trigger global eviction.",
                        key,
                        trimmed,
                        self._total_per_key_trim_waves,
                        self._total_per_key_observations_trimmed,
                        len(self._history[key]),
                    )

            # Enforce global memory bound by evicting oldest keys
            if self._total_observation_count > self._max_total_observations:
                self._evict_oldest_keys()

        # (callsite) — emit per-observation production record
        # for source-health monitoring. `record_observation` internally checks
        # DT_OBSERVATION_PRODUCTION_ENABLED gate (no-op when off) + hybrid
        # emit-policy fires on health-transition OR stale-freshness. Outside
        # _lock to avoid lock-nesting; substrate has its own RLock.
        try:
            from arbiter_engine.history.observation_production import (
                record_observation,
            )
            freshness_age = max(0.0, (datetime.utcnow() - timestamp).total_seconds())
            observation_id = f"{entity_id}:{property_name}:{timestamp.isoformat()}"
            record_observation(
                observation_id=observation_id,
                source_id=entity_id,
                freshness_age_seconds=freshness_age,
                observed_at=timestamp,
                cluster_id=self._cluster_id,  # Layer 3 (per-cluster history)
            )
        except Exception:  # noqa: BLE001 — defensive; substrate-unavailable
            pass

    def add_observation(self, observation: Observation) -> None:
        """Add an Observation object."""
        self.add(
            observation.entity_id,
            observation.property_name,
            observation.value,
            observation.timestamp
        )

    def add_entity_observations(
        self,
        entity_id: str,
        entity_type: str,
        properties: Dict[str, Any],
        timestamp: Optional[datetime] = None
    ) -> None:
        """Add observations for all properties of an entity.

        Filters non-scalar properties (lists, dicts, long strings)
        to prevent false stability oscillation and memory waste.
        """
        timestamp = timestamp or datetime.utcnow()

        def add_props(props: dict, prefix: str = ''):
            for key, value in props.items():
                path = f"{prefix}.{key}" if prefix else key
                if isinstance(value, (int, float)):
                    self.add(entity_id, path, value, timestamp)
                elif isinstance(value, bool):
                    self.add(entity_id, path, str(value), timestamp)
                elif isinstance(value, str) and len(value) < 500:
                    # Skip long strings (serialized dicts/lists)
                    # Increased from 100 to 500 chars to preserve
                    # status descriptions and error messages from unknown domains.
                    self.add(entity_id, path, value, timestamp)
                elif isinstance(value, dict):
                    add_props(value, path)
                elif isinstance(value, list) and len(value) <= 10:
                    # Expand short numeric lists into indexed scalar properties.
                    # Unknown domains with array-valued properties (fan_speeds, multi-sensor
                    # readings) would otherwise lose all observability.
                    numeric_items = [v for v in value if isinstance(v, (int, float))]
                    if len(numeric_items) == len(value) and numeric_items:
                        for idx, item in enumerate(numeric_items):
                            self.add(entity_id, f"{path}[{idx}]", item, timestamp)
                        # Also record aggregates for axiom detection
                        self.add(entity_id, f"{path}._mean", sum(numeric_items) / len(numeric_items), timestamp)
                        self.add(entity_id, f"{path}._min", min(numeric_items), timestamp)
                        self.add(entity_id, f"{path}._max", max(numeric_items), timestamp)
                # Skip: long lists, None, long strings — no detection value

        add_props(properties)

        # Track structured property groups for group-level anomaly detection.
        # When a dict property is flattened (e.g., sensors.temp, sensors.fan),
        # store group membership so axiom checkers can detect "all sensors degrading".
        groups = {}
        for key, value in properties.items():
            if isinstance(value, dict):
                group_keys = []
                for sub_key in value:
                    full_key = f"{key}.{sub_key}"
                    group_keys.append(full_key)
                if group_keys:
                    groups[key] = group_keys

        # Update entity metadata
        with self._lock:
            prev_meta = self._entity_metadata.get(entity_id)
            # (softened): Log type mismatch but preserve observations.
            # Entity IDs are now type-qualified (e.g. "deployment/ns/name"),
            # so cross-type collisions no longer reach here. If they do,
            # observations under different property names don't interfere
            # because axiom checkers only inspect type-specific indicators.
            # Clearing aggressively prevented axiom thresholds from ever
            # accumulating enough samples.
            if prev_meta and prev_meta.get('type') and prev_meta['type'] != entity_type:
                logger.warning(
                    f"Entity {entity_id} type mismatch: "
                    f"recorded={prev_meta['type']} incoming={entity_type}. "
                    f"Preserving observations (property names are type-specific)."
                )

            self._entity_metadata[entity_id] = {
                'type': entity_type,
                'last_observed': timestamp,
            }
            if groups:
                self._entity_metadata[entity_id]['property_groups'] = groups

    def get_values(
        self,
        entity_id: str,
        property_name: str,
        window: timedelta
    ) -> List[Tuple[datetime, float]]:
        """Get numeric values within time window.

        Results sorted by timestamp (not insertion order) to handle
        out-of-order arrivals from batch processing or agent reconnection.
        """
        key = (entity_id, property_name)
        cutoff = datetime.utcnow() - window

        with self._lock:
            observations = self._history.get(key, [])
            result = []
            for ts, value in observations:
                if ts > cutoff:
                    try:
                        result.append((ts, float(value)))
                    except (TypeError, ValueError):
                        pass
            result.sort(key=lambda x: x[0])
            return result

    def get_states(
        self,
        entity_id: str,
        property_name: str,
        window: timedelta
    ) -> List[Tuple[datetime, str]]:
        """Get state values within time window.

        Results sorted by timestamp to handle out-of-order arrivals.
        StabilityChecker checks consecutive values by list index, so correct
        temporal ordering prevents false oscillation detections.
        """
        key = (entity_id, property_name)
        cutoff = datetime.utcnow() - window

        with self._lock:
            observations = self._history.get(key, [])
            result = [
                (ts, str(value))
                for ts, value in observations
                if ts > cutoff
            ]
            result.sort(key=lambda x: x[0])
            return result

    def get_observations(
        self,
        entity_id: str,
        start: datetime,
        end: datetime
    ) -> List[Observation]:
        """Get all observations for entity in time range."""
        observations = []

        with self._lock:
            for (eid, prop), values in self._history.items():
                if eid != entity_id:
                    continue

                for ts, value in values:
                    if start <= ts <= end:
                        # Determine property type
                        if isinstance(value, (int, float)):
                            prop_type = 'numeric'
                        elif isinstance(value, str):
                            prop_type = 'state'
                        else:
                            prop_type = 'unknown'

                        entity_type = self._entity_metadata.get(entity_id, {}).get('type', 'unknown')

                        observations.append(Observation(
                            entity_id=entity_id,
                            entity_type=entity_type,
                            property_name=prop,
                            property_type=prop_type,
                            value=value,
                            timestamp=ts,
                        ))

        return sorted(observations, key=lambda o: o.timestamp)

    def get_all_observations(
        self,
        start: datetime,
        end: datetime
    ) -> List[Observation]:
        """Get all observations in time range."""
        observations = []

        with self._lock:
            for (entity_id, prop), values in self._history.items():
                for ts, value in values:
                    if start <= ts <= end:
                        if isinstance(value, (int, float)):
                            prop_type = 'numeric'
                        elif isinstance(value, str):
                            prop_type = 'state'
                        else:
                            prop_type = 'unknown'

                        entity_type = self._entity_metadata.get(entity_id, {}).get('type', 'unknown')

                        observations.append(Observation(
                            entity_id=entity_id,
                            entity_type=entity_type,
                            property_name=prop,
                            property_type=prop_type,
                            value=value,
                            timestamp=ts,
                        ))

        return sorted(observations, key=lambda o: o.timestamp)

    def get_observation_count(
        self,
        entity_id: str,
        property_name: str
    ) -> int:
        """Get count of observations for a property."""
        key = (entity_id, property_name)
        with self._lock:
            return self._observation_counts.get(key, 0)

    def get_all_numeric_series(
        self,
        window: timedelta = timedelta(days=7),
        entity_filter: Optional[str] = None,
    ) -> Dict[str, List[Tuple[datetime, float]]]:
        """Get all numeric time series.

        ``entity_filter`` (default ``None``) restricts results to a
        single entity. previously a module held from this package
        passed ``entity_filter=entity.id`` to this method, but the signature
        had no such parameter — Python raised ``TypeError`` per call,
        caught upstream as ``Hybrid discovery error:.
        unexpected keyword argument 'entity_filter'``. Correlation
        mining was silently broken for ~6 weeks; wires the
        parameter through so the per-entity-series filter actually works.

        Args:
            window: time window for observations (default 7 days).
            entity_filter: if provided, only return series for this
                entity_id. ``None`` preserves the previously all-entities
                behavior for backward compat.

        Returns:
            Dict mapping ``"{entity_id}.{prop}"`` → list of (ts, value)
            tuples, filtered to entries within ``window`` and (if
            ``entity_filter`` provided) only that entity.
        """
        result = {}
        cutoff = datetime.utcnow() - window

        with self._lock:
            for (entity_id, prop), values in self._history.items():
                # filter by entity_id when caller wants a single-
                # entity slice (relationship_mining.py:222 use case).
                if entity_filter is not None and entity_id != entity_filter:
                    continue
                series = []
                for ts, value in values:
                    if ts > cutoff:
                        try:
                            series.append((ts, float(value)))
                        except (TypeError, ValueError):
                            pass

                if series:
                    key = f"{entity_id}.{prop}"
                    result[key] = series

        return result

    def get_entity_metadata(self) -> Dict[str, Dict]:
        """Get metadata for all entities."""
        with self._lock:
            return dict(self._entity_metadata)

    def prune_old_observations(self) -> int:
        """Remove observations older than retention period."""
        cutoff = datetime.utcnow() - self.retention_period
        pruned = 0

        with self._lock:
            for key in list(self._history.keys()):
                original_len = len(self._history[key])
                self._history[key] = [
                    (ts, v) for ts, v in self._history[key]
                    if ts > cutoff
                ]
                removed = original_len - len(self._history[key])
                pruned += removed
                self._total_observation_count -= removed

                # Remove empty entries
                if not self._history[key]:
                    del self._history[key]

        return pruned

    def _evict_oldest_keys(self) -> None:
        """Evict oldest observation keys when total exceeds global limit.

        Removes keys with the oldest last-observation timestamp until total
        drops below 90% of max. Called within existing lock context.

        surfaces previously-silent destructive eviction via WARNING +
        lifetime counters (silent-destructive-eviction archetype family **7th
        member**). FIRST wave + every 100th wave fires a WARNING naming the
        keys dropped this wave + the lifetime counters; subsequent waves stay
        silent. Cadence matches (heartbeat-paced —
        add() is called on every metric flush).
        """
        target = int(self._max_total_observations * 0.9)
        # Sort keys by last timestamp (oldest first)
        key_last_ts = []
        for key, obs_list in self._history.items():
            last_ts = obs_list[-1][0] if obs_list else datetime.min
            key_last_ts.append((last_ts, key, len(obs_list)))
        key_last_ts.sort()

        # track wave-level metrics for the operator-visible WARN.
        wave_keys_dropped = 0
        wave_observations_dropped = 0
        # Sample of affected (entity_id, property_name) keys included in the
        # WARN message — bounded so the log line stays readable on
        # mass-eviction waves.
        _SAMPLE_CAP = 5
        sample_keys: List[Tuple[str, str]] = []

        for _, key, count in key_last_ts:
            if self._total_observation_count <= target:
                break
            del self._history[key]
            self._observation_counts.pop(key, None)
            self._total_observation_count -= count
            wave_keys_dropped += 1
            wave_observations_dropped += count
            if len(sample_keys) < _SAMPLE_CAP:
                sample_keys.append(key)

        # Clean up _entity_metadata for entities with no remaining observations.
        # Without this, entities whose all observations were evicted retain stale metadata
        # entries indefinitely, causing get_entity_types() to return phantom types.
        remaining_entities = set(k[0] for k in self._history.keys())
        stale_meta = [eid for eid in self._entity_metadata if eid not in remaining_entities]
        for eid in stale_meta:
            del self._entity_metadata[eid]

        # update lifetime counters + emit WARNING on first wave +
        # every 100th wave thereafter. Stay silent when no keys were dropped
        # (e.g. count already below target before loop ran — defensive case).
        if wave_keys_dropped > 0:
            self._eviction_wave_count += 1
            self._total_keys_evicted += wave_keys_dropped
            self._total_observations_evicted += wave_observations_dropped
            if self._eviction_wave_count == 1 or self._eviction_wave_count % 100 == 0:
                sample_str = ", ".join(
                    f"{eid}/{prop}" for eid, prop in sample_keys
                )
                if wave_keys_dropped > _SAMPLE_CAP:
                    sample_str += f" (+{wave_keys_dropped - _SAMPLE_CAP} more)"
                logger.warning(
                    "InMemoryObservationHistory evicted %d oldest key(s) "
                    "(dropped %d observation(s)) to enforce global cap of %d "
                    "(target after eviction: %d). Affected: %s. "
                    "Lifetime: %d wave(s), %d key(s), %d observation(s) evicted; "
                    "%d observation(s) remain in store. Operators seeing axiom "
                    "readiness drops should inspect this surface. Bump "
                    "`max_total_observations` constructor arg if eviction is "
                    "premature for the active workload.",
                    wave_keys_dropped,
                    wave_observations_dropped,
                    self._max_total_observations,
                    target,
                    sample_str or "(none)",
                    self._eviction_wave_count,
                    self._total_keys_evicted,
                    self._total_observations_evicted,
                    self._total_observation_count,
                )

    def get_statistics(self) -> Dict:
        """Get history statistics.

        lifetime eviction counters added so operators querying stats
        see whether `_evict_oldest_keys` has fired and how much history
        was lost. Sibling of the response-channel surface introduced for
        PlaceholderAuditLogger in PlaceholderConfigManager in
        the WARN log channel surface is fixed by the eviction
        WARNING; this dict-channel surface lets operators query the
        truncation magnitude programmatically.
        """
        with self._lock:
            total_observations = sum(len(v) for v in self._history.values())
            return {
                'property_keys': len(self._history),
                'total_observations': total_observations,
                'entity_count': len(self._entity_metadata),
                'max_observations_per_key': self.max_observations,
                # eviction surface counters
                'eviction_wave_count': self._eviction_wave_count,
                'total_observations_evicted': self._total_observations_evicted,
                'total_keys_evicted': self._total_keys_evicted,
                'max_total_observations': self._max_total_observations,
            }

    def get_memory_estimate(self) -> Dict[str, int]:
        """Estimate memory usage."""
        with self._lock:
            total_obs = sum(len(v) for v in self._history.values())
            # Rough estimate: ~100 bytes per observation (timestamp + value + overhead)
            estimated_bytes = total_obs * 100
            return {
                'total_observations': total_obs,
                'property_keys': len(self._history),
                'estimated_bytes': estimated_bytes,
                'estimated_mb': estimated_bytes // (1024 * 1024),
            }

    def clear_entity(self, entity_id: str) -> int:
        """Clear all observation history for a specific entity.

        Called on entity eviction to prevent chimeric history when the entity
        reappears with different properties (e.g., pod recreated with new config).
        """
        removed = 0
        with self._lock:
            keys_to_remove = [k for k in self._history if k[0] == entity_id]
            for k in keys_to_remove:
                removed += len(self._history[k])
                del self._history[k]
                self._observation_counts.pop(k, None)
            self._entity_metadata.pop(entity_id, None)
        return removed

    def clear(self) -> None:
        """Clear all history."""
        with self._lock:
            self._history.clear()
            self._observation_counts.clear()
            self._entity_metadata.clear()
