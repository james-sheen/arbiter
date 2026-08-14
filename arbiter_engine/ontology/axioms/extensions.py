"""
Domain-Specific Axiom Extensions.

Provides a plugin pattern for domain-specific axiom checks.
The base HomeostasisChecker and ResponsivenessChecker contain
domain-agnostic checks (z-score, I/O correlation, etc.).
Domain-specific checks (e.g., K8s replica mismatch, health probes)
are registered as extensions and called by the axiom checkers.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from ...interfaces import Entity, Problem, ObservationHistory

logger = logging.getLogger(__name__)


class AxiomExtension(ABC):
    """Base class for domain-specific axiom checks."""

    @property
    @abstractmethod
    def domain_id(self) -> str:
        """Domain identifier."""

    def get_homeostasis_checks(self) -> List[Callable]:
        """Return domain-specific homeostasis check functions.

        Each function signature: (entity, history) -> List[Problem]
        """
        return []

    def get_responsiveness_checks(self) -> List[Callable]:
        """Return domain-specific responsiveness check functions.

        Each function signature: (entity, history) -> List[Problem]
        """
        return []


class AxiomExtensionRegistry:
    """Registry of domain axiom extensions."""

    def __init__(self):
        self._extensions: Dict[str, AxiomExtension] = {}

    def register(self, extension: AxiomExtension):
        """Register a domain axiom extension."""
        self._extensions[extension.domain_id] = extension
        logger.info(f"Registered axiom extension for domain: {extension.domain_id}")

    def unregister(self, domain_id: str):
        """Unregister a domain axiom extension."""
        self._extensions.pop(domain_id, None)

    def get_homeostasis_checks(self, domain_id: str = "") -> List[Callable]:
        """Get registered homeostasis checks, optionally filtered by domain."""
        # `if domain_id and...` skipped the filter entirely when
        # `domain_id` was empty, so an entity with **no domain stamp** received
        # EVERY registered domain's checks. That is verbatim the failure the
        # comment above says this filter prevents ("K8s checks on BMC
        # entities"), left open for the one case that cannot defend itself.
        #
        # Same shape as an internal ruling, which closed it in the built-in K8s tail:
        # an absent domain was read as "match everything" rather than "match
        # nothing". Absent means absent, here too.
        #
        # Verified before changing: both call sites pass a per-entity
        # `domain_id` from metadata; none passes "" meaning "all".
        if not domain_id:
            return []
        checks = []
        for ext in self._extensions.values():
            if ext.domain_id != domain_id:
                continue
            checks.extend(ext.get_homeostasis_checks())
        return checks

    def get_responsiveness_checks(self, domain_id: str = "") -> List[Callable]:
        """Get registered responsiveness checks, optionally filtered by domain."""
        # see `get_homeostasis_checks`: an empty `domain_id` used to
        # disable the filter and run every domain's checks on an unstamped
        # entity.
        if not domain_id:
            return []
        checks = []
        for ext in self._extensions.values():
            if ext.domain_id != domain_id:
                continue
            checks.extend(ext.get_responsiveness_checks())
        return checks

    def get_extension(self, domain_id: str) -> Optional[AxiomExtension]:
        """Get extension by domain ID."""
        return self._extensions.get(domain_id)

    @property
    def domains(self) -> List[str]:
        """List registered domain IDs."""
        return list(self._extensions.keys())


# Global registry instance
extension_registry = AxiomExtensionRegistry()
