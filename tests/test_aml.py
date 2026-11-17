from pathlib import Path

import pytest

from audit_analytics.aml import apply_rules, evaluate, load_ibm

FIXTURE = Path(__file__).parent / "fixtures" / "aml_sample.csv"


@pytest.fixture(scope="module")
def tx():
    return load_ibm(FIXTURE)


@pytest.fixture(scope="module")
def flags(tx):
    return apply_rules(tx)


def _accts(tx, mask, col="from_acct"):
    return sorted(tx.loc[mask, col].str.split("|").str[1].unique())


def test_structuring_flags_three_in_window_only(tx, flags):
    hit = tx[flags.R1]
    assert len(hit) == 3
    assert set(hit.amount) == {9500, 9200, 9900}  # the 9,100 two days later is outside the window


def test_fan_out_and_fan_in(tx, flags):
    assert _accts(tx, flags.R2) == ["F1"]
    assert _accts(tx, flags.R3, "to_acct") == ["G1"]


def test_pass_through_flags_outgoing_leg_within_24h(tx, flags):
    hit = tx[flags.R4]
    assert hit.amount.tolist() == [48000]


def test_large_cash(tx, flags):
    assert tx.loc[flags.R5, "amount"].tolist() == [15000]


def test_evaluation_metrics(tx, flags):
    res = evaluate(tx, flags).set_index("rule")
    assert res.loc["R1", "precision"] == 1.0
    assert res.loc["ANY", "true_positives"] == 4
    assert res.loc["ANY", "recall"] == pytest.approx(4 / 5)
    assert res.attrs["n_laundering"] == 5
