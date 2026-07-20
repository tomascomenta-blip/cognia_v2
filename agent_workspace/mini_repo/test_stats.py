from stats import running_mean, variance

def test_running_mean_single():
    assert running_mean([5]) == [5.0]

def test_running_mean_multi():
    result = running_mean([1, 2, 3])
    assert result == [1.0, 1.5, 2.0]

def test_variance_basic():
    assert variance([2, 4, 4, 4, 5, 5, 7, 9]) == 4.0

def test_variance_empty():
    assert variance([]) == 0.0
