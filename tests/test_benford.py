import numpy as np
import pandas as pd

from audit_analytics.analytics import benford, first_digit


def test_first_digit():
    assert first_digit(pd.Series([12.5, 987.0, 10.0, 5.0, 1_000_000.0])).tolist() == [1, 9, 1, 1]


def test_benford_conforming_data_is_close():
    rng = np.random.default_rng(0)
    amounts = pd.Series(10 ** rng.uniform(1, 6, 50_000))  # log-uniform data follows Benford
    res = benford(amounts)
    assert res.mad < 0.006
    assert res.conclusion == "Close conformity"


def test_benford_flags_uniform_data():
    rng = np.random.default_rng(0)
    res = benford(pd.Series(rng.uniform(1000, 9999, 20_000)))
    assert res.conclusion == "Nonconformity"
    assert res.p_value < 0.001
