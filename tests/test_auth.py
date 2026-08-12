import pytest

from gtd.auth import (
    MIN_PASSWORD_LENGTH,
    LoginRateLimiter,
    hash_password,
    verify_password,
)


def test_hash_verify_round_trip():
    h = hash_password("correct horse battery staple")
    assert verify_password(h, "correct horse battery staple")


def test_wrong_password_rejected():
    h = hash_password("correct horse battery staple")
    assert not verify_password(h, "Correct horse battery staple")
    assert not verify_password(h, "")


def test_hash_is_salted_so_same_password_differs():
    a = hash_password("same password here")
    b = hash_password("same password here")
    assert a != b
    assert verify_password(a, "same password here")
    assert verify_password(b, "same password here")


def test_hash_is_argon2id():
    assert hash_password("a long enough password").startswith("$argon2id$")


def test_short_password_refused():
    with pytest.raises(ValueError, match="at least"):
        hash_password("x" * (MIN_PASSWORD_LENGTH - 1))


def test_garbage_hash_does_not_raise():
    # A corrupted stored hash must read as "no", not crash the login route.
    assert not verify_password("not-a-real-hash", "anything at all")


# ── Rate limiting ────────────────────────────────────────────────────────────

def test_lockout_after_max_attempts():
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=900)
    assert not limiter.is_locked("1.2.3.4")

    for _ in range(3):
        limiter.record_failure("1.2.3.4")
    assert limiter.is_locked("1.2.3.4")
    assert limiter.seconds_remaining("1.2.3.4") > 0


def test_lockout_is_per_client():
    limiter = LoginRateLimiter(max_attempts=2)
    limiter.record_failure("1.1.1.1")
    limiter.record_failure("1.1.1.1")
    assert limiter.is_locked("1.1.1.1")
    assert not limiter.is_locked("2.2.2.2")


def test_successful_login_clears_the_record():
    limiter = LoginRateLimiter(max_attempts=2)
    limiter.record_failure("1.1.1.1")
    limiter.reset("1.1.1.1")
    limiter.record_failure("1.1.1.1")
    assert not limiter.is_locked("1.1.1.1")


def test_attempts_expire_out_of_the_window():
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=0)
    limiter.record_failure("1.1.1.1")
    limiter.record_failure("1.1.1.1")
    assert not limiter.is_locked("1.1.1.1")   # window already elapsed
