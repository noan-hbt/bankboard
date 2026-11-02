"""Daily aggregate series with prefix sums: O(1) trailing-window sums for snapshots and scores."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from bankboard.analytics.frames import spend_expr

FIELDS = ("income", "spend", "essential", "variable")


class DailySeries:
    def __init__(self, df: pl.DataFrame, start: date, end: date) -> None:
        self.start, self.end = start, end
        n = (end - start).days + 1
        values = {f: [0] * n for f in FIELDS}
        if not df.is_empty():
            agg = df.filter((pl.col("booking_date") >= start) & (pl.col("booking_date") <= end)).group_by(
                "booking_date").agg(
                pl.when(pl.col("kind") == "income").then(pl.col("amount")).otherwise(0).sum().alias("income"),
                spend_expr().sum().alias("spend"),
                pl.when(pl.col("is_essential")).then(spend_expr()).otherwise(0).sum().alias("essential"),
                pl.when(~pl.col("recurring")).then(spend_expr()).otherwise(0).sum().alias("variable"),
            )
            for r in agg.iter_rows(named=True):
                i = (r["booking_date"] - start).days
                for f in FIELDS:
                    values[f][i] = int(r[f] or 0)
        self._prefix: dict[str, list[int]] = {}
        for f in FIELDS:
            acc, pref = 0, [0]
            for v in values[f]:
                acc += v
                pref.append(acc)
            self._prefix[f] = pref

    def total(self, field: str, start: date, end: date) -> int:
        """Inclusive sum over [start, end] clipped to the series range (cents)."""
        s = max(start, self.start)
        e = min(end, self.end)
        if s > e:
            return 0
        pref = self._prefix[field]
        return pref[(e - self.start).days + 1] - pref[(s - self.start).days]

    def trailing(self, field: str, as_of: date, days: int) -> int:
        return self.total(field, as_of - timedelta(days=days - 1), as_of)
