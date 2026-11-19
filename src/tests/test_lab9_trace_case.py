"""Regression test from docs/trace_case.md: seeded_regression C-014@11 (FM-05 pre_deducted).

The shape subtracted the 30.000đ already refunded on O-515 before calling the host, the host
subtracted it again, and the ledger ended at 90.000đ instead of 120.000đ while the reply said
120.000đ. Lab 8's grader only said `proposal_mismatch`; these assertions pin the first wrong step.
"""
import pytest

pytestmark = pytest.mark.student
CLAIM, SEED = "C-014", 11


def _grade(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext
    from lab9.graders import RefundAmountCorrect, ReplyAmountMatchesLedger

    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                           duration=0.0, _span_tree=None, attributes={}, metrics={})
    return RefundAmountCorrect().evaluate(ctx).value, ReplyAmountMatchesLedger().evaluate(ctx).value


def _kinds(trial):
    return [e.get("kind") for e in trial["events"]]


def test_pre_deducted_c014_is_caught():
    from lab9.trace_case import investigate

    case = investigate("seeded_regression", CLAIM, SEED)
    t, label = case["trial"], case["label"]
    # First wrong step: a `proposal` below the quote, right after reading the refund history.
    kinds = _kinds(t)
    i = kinds.index("proposal")
    assert kinds[i - 1] == "refund_history"
    quote = next(e["payload"]["amount_vnd"] for e in t["events"] if e["kind"] == "quote")
    assert t["events"][i]["payload"]["amount_vnd"] < quote
    assert t["snapshot"]["refund_vnd"] == 90000 != label["refund_vnd"] == 120000
    assert _grade(t, label) == (False, False)


def test_fixed_c014_passes_with_full_quote():
    from lab9.trace_case import investigate

    case = investigate("fixed", CLAIM, SEED)
    t, label = case["trial"], case["label"]
    assert "proposal" not in _kinds(t)          # the full quote goes to the host, which deducts once
    assert t["snapshot"]["refund_vnd"] == label["refund_vnd"] == 120000
    assert _grade(t, label) == (True, True)
