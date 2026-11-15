"""
Shared authentication/authorization utilities.

- Passwords are hashed with bcrypt (never stored/compared in plaintext) and
  must meet a minimum strength bar (see `validate_password_strength`).
- Login issues a JWT containing the user's id, username, name, and role,
  plus a unique `jti` and an `iss`/`aud` pair so tokens can't be replayed
  against a different service.
- Repeated failed logins for a username are throttled with an increasing
  lockout window (see `LoginThrottle`) to blunt brute-force/credential
  stuffing attempts.
- `get_current_user` decodes and validates the token on any protected route.
- `require_roles(...)` builds a dependency that additionally checks the
  token's role is in an allowed set (e.g. only "admin" for uploads).
"""
import os
import re
import time
import uuid
from collections import defaultdict
from threading import Lock
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    # Fail loudly rather than silently running with a guessable dev secret.
    raise RuntimeError(
        "JWT_SECRET is not set. Add a long random value to your .env, e.g.\n"
        "  python3 -c \"import secrets; print(secrets.token_hex(32))\"\n"
        "and set JWT_SECRET=<that value> before starting the backend."
    )
if len(JWT_SECRET) < 32:
    # A short secret is brute-forceable offline; fail loudly rather than
    # silently issuing tokens that can be forged.
    raise RuntimeError(
        "JWT_SECRET is too short (needs 32+ chars). Generate a strong one with:\n"
        "  python3 -c \"import secrets; print(secrets.token_hex(32))\""
    )

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = int(os.getenv("JWT_EXPIRY_SECONDS", 60 * 60 * 12))  # 12h default
JWT_ISSUER = os.getenv("JWT_ISSUER", "nmit-gpt-backend")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "nmit-gpt-frontend")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


# ---------------------------------------------------------------------------
# Password hashing & strength
# ---------------------------------------------------------------------------

# Minimum bar: 8+ chars, at least one letter and one digit. Keeps the UX
# reasonable for a college app while ruling out trivially weak passwords
# like "123456" or "password".
_PASSWORD_MIN_LEN = 8
_HAS_LETTER = re.compile(r"[A-Za-z]")
_HAS_DIGIT = re.compile(r"\d")
_COMMON_WEAK_PASSWORDS = {
    "password", "12345678", "qwerty123", "letmein", "admin123",
    "password1", "11111111", "abc12345", "iloveyou", "welcome1",
}


def validate_password_strength(password: str) -> Optional[str]:
    """Returns an error message if the password is too weak, else None."""
    if len(password) < _PASSWORD_MIN_LEN:
        return f"Password must be at least {_PASSWORD_MIN_LEN} characters long."
    if not _HAS_LETTER.search(password) or not _HAS_DIGIT.search(password):
        return "Password must contain at least one letter and one number."
    if password.lower() in _COMMON_WEAK_PASSWORDS:
        return "That password is too common — please choose a stronger one."
    return None


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode(), password_hash.encode())
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Login throttling (brute-force / credential-stuffing protection)
# ---------------------------------------------------------------------------

class LoginThrottle:
    """In-memory throttle keyed by (username, client IP).

    After too many failed attempts, further attempts are rejected for a
    cooldown window that grows with repeated abuse. This is intentionally
    simple (no extra infra dependency) — for a multi-process deployment,
    swap the in-memory dict for Redis, but the interface stays the same.
    """

    MAX_ATTEMPTS = 5
    BASE_LOCKOUT_SECONDS = 60  # 1 min after the first lockout
    MAX_LOCKOUT_SECONDS = 15 * 60  # cap growth at 15 min

    def __init__(self):
        self._lock = Lock()
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._locked_until: dict[str, float] = {}

    @staticmethod
    def _key(username: str, ip: str) -> str:
        return f"{(username or '').strip().lower()}::{ip}"

    def check(self, username: str, ip: str) -> None:
        """Raises HTTPException(429) if this identity is currently locked out."""
        key = self._key(username, ip)
        with self._lock:
            locked_until = self._locked_until.get(key)
            if locked_until and time.time() < locked_until:
                retry_after = int(locked_until - time.time())
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many failed attempts. Try again in {retry_after}s.",
                    headers={"Retry-After": str(retry_after)},
                )

    def record_failure(self, username: str, ip: str) -> None:
        key = self._key(username, ip)
        with self._lock:
            now = time.time()
            attempts = [t for t in self._failures[key] if now - t < 15 * 60]
            attempts.append(now)
            self._failures[key] = attempts
            if len(attempts) >= self.MAX_ATTEMPTS:
                # Grow the lockout with repeated offences, capped.
                prior_lockouts = max(0, len(attempts) - self.MAX_ATTEMPTS)
                lockout = min(
                    self.BASE_LOCKOUT_SECONDS * (2 ** prior_lockouts),
                    self.MAX_LOCKOUT_SECONDS,
                )
                self._locked_until[key] = now + lockout

    def record_success(self, username: str, ip: str) -> None:
        key = self._key(username, ip)
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)


login_throttle = LoginThrottle()


def client_ip(request: Request) -> str:
    # Respect a proxy header if present (e.g. behind nginx/Render/Railway),
    # falling back to the direct connection.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

class CurrentUser(BaseModel):
    id: int
    username: str
    name: str
    role: str  # "student" | "faculty" | "admin"


def create_access_token(user: CurrentUser) -> str:
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "name": user.name,
        "role": user.role,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRY_SECONDS,
        "jti": uuid.uuid4().hex,  # unique per token, useful if you add revocation later
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> CurrentUser:
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],  # explicit allow-list — never trust the token's own "alg"
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired, please sign in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")

    try:
        return CurrentUser(
            id=int(payload["sub"]),
            username=payload["username"],
            name=payload["name"],
            role=payload["role"],
        )
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid authentication token.")


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    """Any authenticated user — student, faculty, or admin. Use this to
    protect the chat endpoint (logged-in users only, any role)."""
    return decode_access_token(token)


def require_roles(*allowed_roles: str):
    """Dependency factory: only lets through users whose role is in
    `allowed_roles`. Use require_roles("admin") to gate admin-only routes."""

    def verify(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"This action requires one of these roles: {', '.join(allowed_roles)}.",
            )
        return user

    return Depends(verify)


def require_admin():
    return require_roles("admin")
