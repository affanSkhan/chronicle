from app.core.rate_limit import SlidingWindowLimiter


def test_sliding_window_limiter_returns_retry_after_without_consuming_blocked_request():
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    assert limiter.check("client", now=100) == (True, 0)
    assert limiter.check("client", now=101) == (True, 0)
    allowed, retry_after = limiter.check("client", now=102)
    assert allowed is False
    assert retry_after == 58
    assert limiter.check("other-client", now=102) == (True, 0)
    assert limiter.check("client", now=160) == (True, 0)

