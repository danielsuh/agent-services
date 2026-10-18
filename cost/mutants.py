"""Deliberately broken copies of the estimator, used to grade tests written by another agent.

Each mutant is one small text patch on the reference source. The patch must apply exactly once,
so a refactor of estimator.py that breaks a patch is caught by this repository's own tests.
These stay private: the request post describes the spec, never this list.
"""
from pathlib import Path

REFERENCE_PATH = Path(__file__).with_name("estimator.py")

MUTANTS = [
    ("no_free_tier", "Data transfer forgets the first 100 GB free",
     '"data_out_tiers": [(100, 0.0), (10240, 0.09)', '"data_out_tiers": [(10240, 0.09)'),
    ("tb_as_1000_gb", "10 TB tier boundary uses 10,000 GB instead of 10,240 GB",
     "(10240, 0.09)", "(10000, 0.09)"),
    ("hours_720", "Default month is 720 hours instead of 730",
     "HOURS_PER_MONTH = 730", "HOURS_PER_MONTH = 720"),
    ("ignores_count", "EC2 cost ignores instance count",
     "compute += rate * count * hours", "compute += rate * hours"),
    ("get_put_swapped", "S3 GET and PUT prices swapped",
     '_num(workload, "s3_get_requests") / 1000 * PRICES["s3_get_per_1000"]',
     '_num(workload, "s3_get_requests") / 1000 * PRICES["s3_put_per_1000"]'),
    ("accepts_negative", "Negative quantities are not rejected",
     "isinstance(value, bool) or value < 0:", "isinstance(value, bool):"),
    ("rounds_items_first", "Total is summed from rounded line items instead of exact values",
     "total = round(sum(items.values()), 2)", "total = round(sum(round(v, 2) for v in items.values()), 2)"),
    ("no_rds_storage", "RDS storage is not charged",
     ' + _num(db, "storage_gb") * PRICES["rds_storage_gb_month"]', ""),
]


def reference_source():
    return REFERENCE_PATH.read_text()


def mutant_sources():
    """Return [(name, description, source)]; raises if any patch does not apply exactly once."""
    ref = reference_source()
    out = []
    for name, desc, old, new in MUTANTS:
        if ref.count(old) != 1:
            raise RuntimeError("mutant %s patch does not apply exactly once" % name)
        out.append((name, desc, ref.replace(old, new)))
    return out
