"""
ori_commercial_v0/connectors/interfaces.py
──────────────────────────────────────────
Abstract connector interfaces.  Implementations are future phases.

Each connector:
- Accepts connection credentials / config at __init__ time (never hardcoded).
- Returns canonical domain objects — no raw external data leaks downstream.
- Is responsible for translating external schemas to the canonical domain.
- Must NOT contain business logic.

IMPORTANT: Do NOT import from agents/, core/, or pages/.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ori_commercial_v0.domain.models import Account, Client, Holding


# ---------------------------------------------------------------------------
# CRMConnector
# ---------------------------------------------------------------------------

class CRMConnector(ABC):
    """
    Interface for pulling client and account metadata from a CRM system
    (e.g. Salesforce, Redtail, Wealthbox).

    Implementations must translate CRM-specific field names and types into
    canonical Client and Account domain objects.
    """

    @abstractmethod
    def get_client(self, client_id: str) -> Client:
        """Fetch a single client by CRM ID."""
        ...

    @abstractmethod
    def list_clients(
        self,
        advisor_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Client]:
        """
        List clients, optionally filtered by advisor.
        Implementations must support pagination.
        """
        ...

    @abstractmethod
    def get_accounts(self, client_id: str) -> list[Account]:
        """Return all accounts associated with a client."""
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the CRM connection is healthy."""
        ...


# ---------------------------------------------------------------------------
# CustodianConnector
# ---------------------------------------------------------------------------

class CustodianConnector(ABC):
    """
    Interface for pulling holdings and position data from a custodian
    (e.g. TD Wealth, National Bank, DTCC, CSV export).

    Implementations must:
    - Translate custodian-specific field names to canonical Holding objects.
    - Handle date formats, currency, and quantity conventions.
    - Return only holdings that belong to the requested account.
    """

    @abstractmethod
    def get_holdings(self, account_id: str, as_of_date: Optional[str] = None) -> list[Holding]:
        """
        Return holdings for a single account.

        Parameters
        ----------
        account_id : str
            The custodian's internal account identifier.
        as_of_date : str, optional
            ISO date string (YYYY-MM-DD).  If None, returns latest available.
        """
        ...

    @abstractmethod
    def list_accounts(self, client_id: str) -> list[Account]:
        """Return all accounts the custodian holds for a client."""
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the custodian connection is healthy."""
        ...


# ---------------------------------------------------------------------------
# DocumentConnector
# ---------------------------------------------------------------------------

class DocumentConnector(ABC):
    """
    Interface for ingesting and extracting structured data from client
    documents (IPS PDFs, KYC forms, account opening agreements).

    Implementations will likely use an LLM or OCR pipeline, but this
    interface enforces that only structured domain objects are returned —
    never raw document text.

    GOVERNANCE: Any LLM used internally must be governed (no raw PII sent
    to cloud without explicit client opt-in and audit log entry).
    """

    @abstractmethod
    def extract_ips(self, document_path: str) -> dict:
        """
        Extract IPS parameters from a PDF or structured document.

        Returns a dict compatible with the IPS domain model.
        Caller is responsible for constructing the IPS object from the dict.
        """
        ...

    @abstractmethod
    def extract_kyc(self, document_path: str) -> dict:
        """
        Extract KYC fields from a client document.

        Returns a dict compatible with the Client domain model.
        """
        ...

    @abstractmethod
    def supported_formats(self) -> list[str]:
        """Return a list of supported file extensions, e.g. ['.pdf', '.docx']."""
        ...
