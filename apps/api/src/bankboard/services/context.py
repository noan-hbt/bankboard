"""FinancialContext: loads everything the engines need for one user, once per request/job.

Engines stay pure; this module is the only bridge between the database and the engines.
"""

from __future__ import annotations

import statistics
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import polars as pl
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from bankboard.analytics.daily import DailySeries
from bankboard.analytics.frames import load_transactions
from bankboard.core.money import fmt_eur, q
from bankboard.engines.cashflow import average_daily_spend, month_bounds
from bankboard.engines.safe_to_spend import ExpectedItem, GoalCommitment, SafeToSpendInputs
from bankboard.engines.state_score import StateInputs
from bankboard.models import (
    Account,
    Balance,
    BankConnection,
    Category,
    ExpectedTransaction,
    Goal,
    RecurringPattern,
    Transaction,
    User,
    UserPreferences,
)

BALANCE_PREFERENCE = ["ITAV", "CLAV", "ITBD", "CLBD", "XPCD", "OTHR"]
HISTORY_DAYS = 430


@dataclass(frozen=True)
class AccountBalance:
    account_id: uuid.UUID
    name: str
    amount: Decimal
    balance_type: str
    reference_date: date
    includes_pending: bool


@dataclass
class FinancialContext:
    user: User
    today: date
    df: pl.DataFrame
    accounts: list[Account]
    balances: dict[uuid.UUID, AccountBalance]
    expected: list[ExpectedTransaction]
    patterns: list[RecurringPattern]
    goals: list[Goal]
    prefs: UserPreferences | None
    connections: list[BankConnection]
    category_labels: dict[str, str]
    data_confidence: float = 1.0
    _history: dict[date, dict[uuid.UUID, Decimal]] = field(default_factory=dict)
    _series: DailySeries | None = None

    @property
    def series(self) -> DailySeries:
        if self._series is None:
            self._series = DailySeries(self.df, self.today - timedelta(days=HISTORY_DAYS), self.today)
        return self._series

    @property
    def first_transaction_date(self) -> date | None:
        return None if self.df.is_empty() else self.df["booking_date"].min()  # type: ignore[return-value]

    def history_days(self, as_of: date) -> int:
        first = self.first_transaction_date
        return 0 if first is None else (as_of - first).days + 1

    # -- accounts ---------------------------------------------------------
    @property
    def base_accounts(self) -> list[Account]:
        return [a for a in self.accounts if a.is_active and a.currency == self.user.base_currency]

    def balance_of(self, account: Account) -> Decimal:
        b = self.balances.get(account.id)
        return b.amount if b else Decimal(0)

    def spending_cash(self) -> Decimal:
        return q(sum((self.balance_of(a) for a in self.base_accounts if a.is_spending), Decimal(0)))

    def liquid_assets(self) -> Decimal:
        return q(sum((self.balance_of(a) for a in self.base_accounts if a.is_liquid), Decimal(0)))

    def net_worth(self) -> Decimal:
        return q(sum((self.balance_of(a) for a in self.base_accounts), Decimal(0)))

    # -- predictions ------------------------------------------------------
    def spending_account_ids(self) -> set[uuid.UUID]:
        return {a.id for a in self.base_accounts if a.is_spending}

    def expected_items(self, *, spending_only: bool = True) -> list[ExpectedItem]:
        ids = self.spending_account_ids()
        return [
            ExpectedItem(date=e.expected_date, amount=e.expected_amount, label=e.label, kind=e.kind,
                         confidence=e.confidence)
            for e in self.expected
            if not spending_only or e.account_id is None or e.account_id in ids
        ]

    def salary_pattern(self) -> RecurringPattern | None:
        salaries = [p for p in self.patterns if p.is_salary and p.status == "active"]
        return max(salaries, key=lambda p: p.mean_amount) if salaries else None

    def next_income_date(self) -> date | None:
        p = self.salary_pattern()
        return p.next_expected_date if p else None

    def salary_dates(self) -> list[date]:
        p = self.salary_pattern()
        if p is None or self.df.is_empty():
            return []
        sal = self.df.filter((pl.col("kind") == "income") & (pl.col("category_key") == "salary"))
        return sorted(set(sal["booking_date"].to_list()))

    # -- derived inputs ---------------------------------------------------
    def essential_monthly(self, as_of: date | None = None) -> Decimal:
        as_of = as_of or self.today
        days = max(1, min(90, self.history_days(as_of)))
        return q(Decimal(self.series.trailing("essential", as_of, days)) / 100 * Decimal("30.44") / days)

    def default_buffer(self) -> tuple[Decimal, str]:
        if self.prefs and self.prefs.min_buffer is not None:
            return q(self.prefs.min_buffer), "défini par toi"
        essential = self.essential_monthly()
        return q(essential * Decimal("0.5")), f"50 % des dépenses essentielles mensuelles ({fmt_eur(essential)})"

    def safe_to_spend_inputs(self) -> SafeToSpendInputs:
        buffer, detail = self.default_buffer()
        funded_accounts = {p.account_id for p in self.patterns
                           if p.status == "active" and p.direction == "in" and p.kind == "transfer"}
        goals = [
            GoalCommitment(name=g.name, monthly=g.minimum_monthly_contribution)
            for g in self.goals
            if g.status == "active" and g.minimum_monthly_contribution > 0
            and (g.linked_account_id is None or g.linked_account_id not in funded_accounts)
        ]
        cash_lines = [(a.name, self.balance_of(a)) for a in self.base_accounts if a.is_spending]
        return SafeToSpendInputs(
            today=self.today, spending_cash=self.spending_cash(), cash_lines=cash_lines,
            expected=self.expected_items(), buffer=buffer, buffer_detail=detail, goals=goals,
            daily_essential_variable=average_daily_spend(self.df, self.today, 90, essential_only=True),
            next_income_date=self.next_income_date(), data_confidence=self.data_confidence,
        )

    # -- history ----------------------------------------------------------
    def balances_on(self, d: date) -> dict[uuid.UUID, Decimal]:
        """End-of-day balance per base account, reconstructed backwards from the latest known balance."""
        if not self._history:
            self._build_history()
        if d in self._history:
            return self._history[d]
        earliest = min(self._history) if self._history else self.today
        if d < earliest:
            return self._history.get(earliest, {})
        return {a.id: self.balance_of(a) for a in self.base_accounts}

    def _build_history(self) -> None:
        start = self.today - timedelta(days=HISTORY_DAYS)
        daily: dict[str, dict[date, int]] = defaultdict(lambda: defaultdict(int))
        daily_booked: dict[str, dict[date, int]] = defaultdict(lambda: defaultdict(int))
        if not self.df.is_empty():
            for r in self.df.select("account_id", "booking_date", "amount", "status").iter_rows(named=True):
                daily[r["account_id"]][r["booking_date"]] += r["amount"]
                if r["status"] == "booked":
                    daily_booked[r["account_id"]][r["booking_date"]] += r["amount"]
        history: dict[date, dict[uuid.UUID, Decimal]] = defaultdict(dict)
        for a in self.base_accounts:
            b = self.balances.get(a.id)
            anchor_cents = int((b.amount if b else Decimal(0)) * 100)
            anchor_date = b.reference_date if b else self.today
            changes = daily[str(a.id)] if (b is None or b.includes_pending) else daily_booked[str(a.id)]
            # balance at end of anchor_date = anchor; walk backwards
            bal = anchor_cents
            d = max(anchor_date, self.today)
            # roll forward transactions after anchor date (rare)
            for k in range((self.today - anchor_date).days):
                bal += changes.get(anchor_date + timedelta(days=k + 1), 0)
            while d >= start:
                history[d][a.id] = Decimal(bal) / 100
                bal -= changes.get(d, 0)
                d -= timedelta(days=1)
        self._history = dict(history)

    def state_inputs(self, as_of: date) -> StateInputs:
        ser = self.series
        balances = self.balances_on(as_of)
        liquid = sum((balances.get(a.id, Decimal(0)) for a in self.base_accounts if a.is_liquid), Decimal(0))
        history = self.history_days(as_of)
        income90 = ser.trailing("income", as_of, 90)
        exp90 = ser.trailing("spend", as_of, 90)
        sr = (income90 - exp90) / income90 if income90 > 0 and history >= 60 else None
        monthly_incomes = [ser.total("income", *month_window(as_of, i)) for i in range(6)]
        mean_income = statistics.fmean(monthly_incomes)
        cv = (statistics.pstdev(monthly_incomes) / mean_income
              if history >= 180 and mean_income > 0 else None)
        # variable (non-recurring) spending: immune to the calendar position of rent & subscriptions
        last30 = ser.trailing("variable", as_of, 30)
        prev90 = ser.total("variable", as_of - timedelta(days=119), as_of - timedelta(days=30))
        ratio = last30 / (prev90 / 3) if prev90 > 0 and history >= 120 else None
        goals = [g for g in self.goals if g.status == "active"]
        gp = (sum(min(1.0, float(g.current_amount / g.target_amount)) for g in goals) / len(goals)) if goals else None
        months_covered = Decimal(min(90, max(history, 1))) / Decimal("30.44")
        return StateInputs(
            liquid_assets=q(liquid), essential_monthly=self.essential_monthly(as_of),
            total_monthly_expenses=q(Decimal(exp90) / 100 / months_covered) if history else Decimal(0),
            savings_rate_3m=sr, income_cv=cv, spend_ratio=ratio,
            goal_progress=gp, data_confidence=self.data_confidence,
        )


def month_window(as_of: date, months_back: int) -> tuple[date, date]:
    """Rolling 30-day windows ending at as_of (0), as_of-30 (1), ..."""
    end = as_of - timedelta(days=30 * months_back)
    return end - timedelta(days=29), end


def _latest_balances(session: Session, accounts: list[Account]) -> dict[uuid.UUID, AccountBalance]:
    out: dict[uuid.UUID, AccountBalance] = {}
    if not accounts:
        return out
    rows = session.scalars(select(Balance).where(Balance.account_id.in_([a.id for a in accounts]))
                           .order_by(Balance.reference_date.desc()))
    names = {a.id: a.name for a in accounts}
    best: dict[uuid.UUID, tuple[date, int, Balance]] = {}
    for b in rows:
        rank = BALANCE_PREFERENCE.index(b.balance_type) if b.balance_type in BALANCE_PREFERENCE else 99
        cur = best.get(b.account_id)
        if cur is None or (b.reference_date, -rank) > (cur[0], -cur[1]):
            best[b.account_id] = (b.reference_date, rank, b)
    for acc_id, (_, _, b) in best.items():
        out[acc_id] = AccountBalance(account_id=acc_id, name=names[acc_id], amount=b.amount,
                                     balance_type=b.balance_type, reference_date=b.reference_date,
                                     includes_pending=b.balance_type.endswith("AV"))
    return out


def build_context(session: Session, user_id: uuid.UUID, today: date) -> FinancialContext:
    user = session.get(User, user_id)
    if user is None:
        raise LookupError("user")
    accounts = list(session.scalars(select(Account).where(Account.user_id == user_id)))
    df = load_transactions(session, user_id, today - timedelta(days=HISTORY_DAYS), today,
                           currency=user.base_currency)
    expected = list(session.scalars(
        select(ExpectedTransaction).where(ExpectedTransaction.user_id == user_id,
                                          ExpectedTransaction.status == "pending",
                                          ExpectedTransaction.expected_date >= today)
        .order_by(ExpectedTransaction.expected_date)))
    patterns = list(session.scalars(select(RecurringPattern).where(RecurringPattern.user_id == user_id)))
    goals = list(session.scalars(select(Goal).where(Goal.user_id == user_id)))
    prefs = session.get(UserPreferences, user_id)
    connections = list(session.scalars(select(BankConnection).where(BankConnection.user_id == user_id)))
    labels: dict[str, str] = {}
    for c in session.scalars(select(Category).where(or_(Category.user_id.is_(None), Category.user_id == user_id))):
        if c.user_id is not None or c.key not in labels:
            labels[c.key] = c.name
    ctx = FinancialContext(user=user, today=today, df=df, accounts=accounts,
                           balances=_latest_balances(session, accounts), expected=expected, patterns=patterns,
                           goals=goals, prefs=prefs, connections=connections, category_labels=labels)
    from bankboard.services.data_health import compute_data_health

    ctx.data_confidence = compute_data_health(session, ctx).confidence
    return ctx


__all__ = [
    "AccountBalance",
    "FinancialContext",
    "Transaction",
    "build_context",
    "month_bounds",
    "month_window",
]
