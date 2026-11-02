"""Transfers, income, refunds, categories, investments and manual-priority rules."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from bankboard.models import User
from bankboard.pipeline.runner import run_pipeline
from bankboard.pipeline.text import normalize_label
from factories import add_tx, make_account

D = date(2026, 10, 10)
OWN_SAVINGS_IBAN = "FR7630004000039876543210987"
OWN_CURRENT_IBAN = "FR7630004000031234567890143"


def test_normalize_label() -> None:
    assert normalize_label("Paiement par carte AMZN Mktp FR*AB123 12/10") == "AMZN MKTP FR"
    assert normalize_label("PRLV SEPA Netflix.com") == "NETFLIX COM"
    assert normalize_label(None) == ""


def test_internal_transfer_pair_is_neither_income_nor_expense(db: Session, user: User) -> None:
    cur = make_account(db, user, name="Courant", iban=OWN_CURRENT_IBAN)
    sav = make_account(db, user, name="Épargne", iban=OWN_SAVINGS_IBAN, account_type="savings", spending=False)
    out = add_tx(db, cur, D, "-250", "To Coffre", counterparty="ALEX MARTIN", counterparty_iban=OWN_SAVINGS_IBAN)
    inn = add_tx(db, sav, D + timedelta(days=1), "250", "From Courant", counterparty="ALEX MARTIN",
                 counterparty_iban=OWN_CURRENT_IBAN)
    run_pipeline(db, user.id, today=D)
    assert out.kind == inn.kind == "transfer"
    assert out.transfer_group_id is not None and out.transfer_group_id == inn.transfer_group_id
    assert out.category_key == "internal_transfer"


def test_same_amount_coincidence_is_not_a_transfer(db: Session, user: User) -> None:
    a = make_account(db, user, name="A")
    b = make_account(db, user, name="B")
    x = add_tx(db, a, D, "-50", "CARREFOUR", counterparty="CARREFOUR", mcc="5411")
    y = add_tx(db, b, D, "50", "VIREMENT ANNA", counterparty="ANNA DUPONT")
    run_pipeline(db, user.id, today=D)
    assert x.kind == "consumption" and x.category_key == "groceries"
    assert y.kind == "income" and x.transfer_group_id is None


def test_single_leg_to_own_unconnected_account(db: Session, user: User) -> None:
    cur = make_account(db, user, name="Courant", iban=OWN_CURRENT_IBAN)
    other_own = make_account(db, user, name="Autre banque", iban=OWN_SAVINGS_IBAN)
    t = add_tx(db, cur, D, "-100", "VIR", counterparty="ALEX MARTIN", counterparty_iban=OWN_SAVINGS_IBAN)
    run_pipeline(db, user.id, today=D)
    assert other_own is not None and t.kind == "transfer"


def test_salary_refund_fee_investment_and_merchants(db: Session, user: User) -> None:
    acc = make_account(db, user)
    salary = add_tx(db, acc, D, "2450", "SALAIRE OCTOBRE", counterparty="ACME SAS")
    refund = add_tx(db, acc, D, "45", "AMAZON REMBOURSEMENT", counterparty="AMAZON")
    amazon = add_tx(db, acc, D, "-30", "AMZN Mktp FR*AB123", counterparty="AMAZON", mcc="5399")
    fee = add_tx(db, acc, D, "-2.50", "FRAIS RETRAIT HORS FORFAIT", counterparty="REVOLUT")
    etf = add_tx(db, acc, D, "-200", "ETF PEA versement", counterparty="TRADE REPUBLIC")
    coffee = add_tx(db, acc, D, "-4.20", "STARBUCKS COFFEE", counterparty="STARBUCKS", mcc="5814")
    resto = add_tx(db, acc, D, "-31", "BISTROT VALOIS", counterparty="BISTROT VALOIS", mcc="5812")
    unknown_in = add_tx(db, acc, D, "80", "VIR ANNA", counterparty="ANNA")
    run_pipeline(db, user.id, today=D)
    assert (salary.kind, salary.category_key) == ("income", "salary")
    assert (refund.kind, refund.category_key) == ("refund", "online_shopping")  # reduces that category
    assert (amazon.kind, amazon.category_key) == ("consumption", "online_shopping")
    assert amazon.merchant_id == refund.merchant_id
    assert (fee.kind, fee.category_key) == ("fee", "fees")
    assert (etf.kind, etf.category_key) == ("investment", "investment")
    assert coffee.category_key == "coffee"  # "FEE" rule must not match "COFFEE"
    assert resto.category_key == "restaurants" and resto.category_source == "rule"
    assert (unknown_in.kind, unknown_in.category_key) == ("income", "other_income")
    for t in (salary, amazon, fee, etf):
        assert 0 < float(t.category_confidence) <= 1


def test_manual_correction_survives_replay_and_teaches_merchant(db: Session, user: User) -> None:
    acc = make_account(db, user)
    t1 = add_tx(db, acc, D, "-12", "LE PETIT ATELIER", counterparty="LE PETIT ATELIER")
    t2 = add_tx(db, acc, D + timedelta(days=3), "-15", "LE PETIT ATELIER", counterparty="LE PETIT ATELIER")
    run_pipeline(db, user.id, today=D)
    assert t1.category_key == "uncategorized"
    t1.category_key, t1.category_source = "gifts", "manual"
    run_pipeline(db, user.id, today=D)
    run_pipeline(db, user.id, today=D)
    assert (t1.category_key, t1.category_source) == ("gifts", "manual")
    assert (t2.category_key, t2.category_source) == ("gifts", "historical")
