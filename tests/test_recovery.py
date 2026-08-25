from core.recovery import classify_exception, ErrorCategory


def test_classify_timeout():
    e = Exception("Navigation timeout of 30000 ms exceeded")
    cat = classify_exception(e)
    assert cat == ErrorCategory.NAVIGATION_TIMEOUT


def test_classify_not_found():
    e = Exception("element not found")
    cat = classify_exception(e)
    assert cat == ErrorCategory.ELEMENT_NOT_FOUND
