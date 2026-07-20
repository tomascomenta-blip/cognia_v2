def running_mean(values):
    """Return list of running means (cumulative average at each index)."""
    result = []
    total = 0
    for i, v in enumerate(values):
        total += v
        result.append(total / (i + 1))  # BUG: should be (i+1), divides by zero at i=0
    return result

def variance(values):
    """Population variance."""
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return sum((x - mean) ** 2 for x in values) / len(values)
