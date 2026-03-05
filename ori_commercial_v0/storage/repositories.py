"""
ori_commercial_v0/storage/repositories.py
──────────────────────────────────────────
Repository interfaces for ORI Commercial.

Follows the repository pattern: business logic never talks to the database
directly.  Instead it calls a repository interface, and the concrete
implementation (SQLite, PostgreSQL, etc.) is injected at runtime.

This keeps the domain and service layers storage-agnostic and testable
with in-memory fakes.

IMPORTANT: Do NOT import from agents/, core/, or pages/.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ori_commercial_v0.domain.models import (
    Account,
    Client,
    IPS,
    PortfolioSnapshot,
    RiskProfile,
)


class ClientRepository(ABC):

    @abstractmethod
    def get(self, client_id: str) -> Optional[Client]:
        ...

    @abstractmethod
    def list(self, advisor_id: Optional[str] = None) -> list[Client]:
        ...

    @abstractmethod
    def save(self, client: Client) -> None:
        ...


class AccountRepository(ABC):

    @abstractmethod
    def get(self, account_id: str) -> Optional[Account]:
        ...

    @abstractmethod
    def list_for_client(self, client_id: str) -> list[Account]:
        ...

    @abstractmethod
    def save(self, account: Account) -> None:
        ...


class SnapshotRepository(ABC):

    @abstractmethod
    def save(self, snapshot: PortfolioSnapshot) -> None:
        """Write an immutable snapshot.  Must not allow overwrite by snapshot_id."""
        ...

    @abstractmethod
    def get(self, snapshot_id: str) -> Optional[PortfolioSnapshot]:
        ...

    @abstractmethod
    def latest_for_client(self, client_id: str) -> Optional[PortfolioSnapshot]:
        ...

    @abstractmethod
    def list_for_client(
        self,
        client_id: str,
        limit: int = 10,
    ) -> list[PortfolioSnapshot]:
        ...


class IPSRepository(ABC):

    @abstractmethod
    def get(self, ips_id: str) -> Optional[IPS]:
        ...

    @abstractmethod
    def current_for_client(self, client_id: str) -> Optional[IPS]:
        """Return the currently active IPS for a client."""
        ...

    @abstractmethod
    def save(self, ips: IPS) -> None:
        ...


class AuditRepository(ABC):
    """
    Append-only log of all governed actions (LLM calls, snapshot writes,
    IPS changes).  Must never allow record deletion or mutation.
    """

    @abstractmethod
    def log(self, record: dict) -> str:
        """
        Append an audit record and return a unique audit_entry_id.

        record must include: action_type, actor_id, timestamp, and any
        action-specific fields (client_id, prompt_hash, etc.).
        """
        ...

    @abstractmethod
    def get(self, audit_entry_id: str) -> Optional[dict]:
        ...
