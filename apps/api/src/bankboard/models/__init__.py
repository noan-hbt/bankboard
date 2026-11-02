"""SQLAlchemy models — mirror of migrations/sql/0001_initial.sql."""

from bankboard.models.banking import (
    Account,
    Balance,
    BankAuthRequest,
    BankConnection,
    BankSession,
    SyncJob,
)
from bankboard.models.base import Base
from bankboard.models.identity import AuditLog, User, UserPreferences, UserSession
from bankboard.models.ledger import Tag, Transaction, TransactionRaw, TransactionTag
from bankboard.models.prediction import ExpectedTransaction, Goal, RecurringPattern
from bankboard.models.reference import Category, ClassificationRule, Merchant, MerchantAlias
from bankboard.models.state import (
    AdvisorConversation,
    AdvisorMessage,
    DashboardLayout,
    DomainEvent,
    FeedItem,
    FinancialSnapshot,
    Insight,
)

__all__ = [
    "Account", "AdvisorConversation", "AdvisorMessage", "AuditLog", "Balance", "BankAuthRequest",
    "BankConnection", "BankSession", "Base", "Category", "ClassificationRule", "DashboardLayout",
    "DomainEvent", "ExpectedTransaction", "FeedItem", "FinancialSnapshot", "Goal", "Insight",
    "Merchant", "MerchantAlias", "RecurringPattern", "SyncJob", "Tag", "Transaction",
    "TransactionRaw", "TransactionTag", "User", "UserPreferences", "UserSession",
]
