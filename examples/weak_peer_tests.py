from cost_estimator import estimate_monthly_cost
import pytest


def test_returns_total():
    assert "total" in estimate_monthly_cost({})

def test_ec2():
    assert estimate_monthly_cost({"instances": [{"type": "t3.micro"}]})["total"] == pytest.approx(7.59, abs=0.01)

def test_ebs():
    assert estimate_monthly_cost({"ebs_gb": 100})["total"] == pytest.approx(8.0)

def test_s3():
    assert estimate_monthly_cost({"s3_gb": 1000})["total"] == pytest.approx(23.0)

def test_unknown():
    with pytest.raises(ValueError):
        estimate_monthly_cost({"instances": [{"type": "nope"}]})

def test_data_small():
    assert estimate_monthly_cost({"data_out_gb": 50})["total"] == 0

def test_db():
    assert estimate_monthly_cost({"database": {"type": "db.t3.micro"}})["total"] == pytest.approx(13.14)

def test_line_items_keys():
    assert set(estimate_monthly_cost({})["line_items"]) >= {"ec2", "rds", "ebs"}
