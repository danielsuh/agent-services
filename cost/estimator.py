"""Toy AWS monthly cost estimator (reference implementation).

Prices are a pinned snapshot of public on-demand list prices for us-east-1, used only
for a teaching model. This is not a quote and not financial advice.
"""

HOURS_PER_MONTH = 730

PRICES = {
    "ec2_hourly": {"t3.micro": 0.0104, "t3.medium": 0.0416, "m5.large": 0.096,
                   "m5.xlarge": 0.192, "c5.large": 0.085},
    "rds_hourly": {"db.t3.micro": 0.018, "db.t3.medium": 0.072, "db.m5.large": 0.178},
    "rds_storage_gb_month": 0.115,
    "ebs_gb_month": 0.08,
    "s3_gb_month": 0.023,
    "s3_get_per_1000": 0.0004,
    "s3_put_per_1000": 0.005,
    # data transfer out to the internet: (tier size in GB, price per GB); None = no upper limit
    "data_out_tiers": [(100, 0.0), (10240, 0.09), (40960, 0.085), (None, 0.07)],
}


def _num(workload, key, default=0):
    value = workload.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ValueError("%s must be a non-negative number" % key)
    return value


def _data_out_cost(gb):
    cost, remaining = 0.0, gb
    for size, price in PRICES["data_out_tiers"]:
        used = remaining if size is None else min(remaining, size)
        cost += used * price
        remaining -= used
        if remaining <= 0:
            break
    return cost


def estimate_monthly_cost(workload):
    """Return {"line_items": {name: dollars}, "total": dollars} for one month."""
    items = {}
    compute = 0.0
    for inst in workload.get("instances", []):
        rate = PRICES["ec2_hourly"].get(inst.get("type"))
        if rate is None:
            raise ValueError("unknown instance type: %r" % inst.get("type"))
        count, hours = _num(inst, "count", 1), inst.get("hours", HOURS_PER_MONTH)
        if not isinstance(hours, (int, float)) or hours < 0 or hours > HOURS_PER_MONTH:
            raise ValueError("hours must be between 0 and %d" % HOURS_PER_MONTH)
        compute += rate * count * hours
    items["ec2"] = compute

    db = workload.get("database")
    if db:
        rate = PRICES["rds_hourly"].get(db.get("type"))
        if rate is None:
            raise ValueError("unknown database type: %r" % db.get("type"))
        hours = db.get("hours", HOURS_PER_MONTH)
        items["rds"] = rate * hours + _num(db, "storage_gb") * PRICES["rds_storage_gb_month"]
    else:
        items["rds"] = 0.0

    items["ebs"] = _num(workload, "ebs_gb") * PRICES["ebs_gb_month"]
    items["s3_storage"] = _num(workload, "s3_gb") * PRICES["s3_gb_month"]
    items["s3_requests"] = (_num(workload, "s3_get_requests") / 1000 * PRICES["s3_get_per_1000"]
                            + _num(workload, "s3_put_requests") / 1000 * PRICES["s3_put_per_1000"])
    items["data_transfer"] = _data_out_cost(_num(workload, "data_out_gb"))

    total = round(sum(items.values()), 2)
    return {"line_items": {k: round(v, 2) for k, v in items.items()}, "total": total}
