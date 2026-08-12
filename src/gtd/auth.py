"""Password hashing, session helpers, and login rate limiting.

Argon2id via argon2-cffi. The hash lives in the `users` table rather than an env
var so the password can be changed without editing config, and so multi-user
stays possible later without a migration.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()

SESSION_USER_KEY = "user"

MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Constant-time-ish verification. Any argon2 failure means 'no' — never
    leak which part failed."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


@dataclass
class LoginRateLimiter:
    """In-memory login throttle, keyed by client IP.

    In-memory is adequate: this is a single-process, single-user app, and a
    restart clearing the counter is not a meaningful bypass for an attacker who
    cannot restart the process. Swap for a shared store only if this ever runs
    multi-process.
    """

    max_attempts: int = 5
    window_seconds: int = 15 * 60
    _attempts: dict[str, list[float]] = field(default_factory=dict)

    def _prune(self, key: str, now: float) -> list[float]:
        recent = [t for t in self._attempts.get(key, []) if now - t < self.window_seconds]
        if recent:
            self._attempts[key] = recent
        else:
            self._attempts.pop(key, None)
        return recent

    def is_locked(self, key: str) -> bool:
        return len(self._prune(key, time.time())) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        now = time.time()
        self._prune(key, now)
        self._attempts.setdefault(key, []).append(now)

    def reset(self, key: str) -> None:
        """Called on success — a good login clears the record."""
        self._attempts.pop(key, None)

    def seconds_remaining(self, key: str) -> int:
        attempts = self._prune(key, time.time())
        if len(attempts) < self.max_attempts:
            return 0
        return max(0, int(self.window_seconds - (time.time() - min(attempts))))
