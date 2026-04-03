import hashlib
import hmac as _hmac
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from app.jwt_utils import JWTError, encode as jwt_encode, decode as jwt_decode
from sqlalchemy.orm import Session

from app.database import get_db
from app import models

SECRET_KEY = os.environ.get("CAAMS_SECRET_KEY", "")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("CAAMS_ACCESS_TOKEN_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.environ.get("CAAMS_REFRESH_TOKEN_DAYS", "7"))

# PBKDF2-HMAC-SHA256 password hashing (pure Python, no C extensions needed)
# 600,000 iterations per OWASP 2023 recommendation for PBKDF2-HMAC-SHA256
_ITERATIONS = 600_000
_HASH_ALG = "sha256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


# ── Password helpers ─────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(_HASH_ALG, password.encode(), salt.encode(), _ITERATIONS)
    return f"pbkdf2:{_ITERATIONS}:{salt}:{dk.hex()}"


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _, iters, salt, stored_hex = hashed.split(":")
        dk = hashlib.pbkdf2_hmac(_HASH_ALG, plain.encode(), salt.encode(), int(iters))
        return _hmac.compare_digest(dk.hex(), stored_hex)
    except Exception:
        return False


# ── JWT helpers ──────────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    to_encode["type"] = "access"
    delta = expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = time.time() + delta.total_seconds()
    # tv (token_version) allows instant revocation by bumping user.token_version
    to_encode.setdefault("tv", 0)
    return jwt_encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_mfa_token(user_id: int) -> str:
    """Short-lived (5 min) token issued after password auth when MFA is enabled.
    Must be exchanged for a real access token via POST /auth/mfa/verify-login."""
    payload = {"sub": str(user_id), "type": "mfa_pending", "exp": time.time() + 300}
    return jwt_encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_mfa_token(token: str) -> int:
    """Validate an mfa_pending token and return the user_id it encodes."""
    try:
        payload = decode_token(token)
        if payload.get("type") != "mfa_pending":
            raise JWTError("not an mfa token")
        return int(payload["sub"])
    except (JWTError, ValueError, KeyError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired MFA session")


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    to_encode["type"] = "refresh"
    to_encode["exp"] = time.time() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS).total_seconds()
    to_encode.setdefault("tv", 0)
    return jwt_encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt_decode(token, SECRET_KEY, algorithms=[ALGORITHM])


# ── API token helpers ────────────────────────────────────────────────────────

def generate_api_token() -> tuple[str, str, str]:
    """Returns (plaintext_token, prefix, hashed_token)."""
    raw = secrets.token_urlsafe(32)
    prefix = raw[:8]
    hashed = _hmac.new(SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return raw, prefix, hashed


def hash_api_token(raw: str) -> str:
    return _hmac.new(SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()


# ── Current-user resolution ──────────────────────────────────────────────────

async def _resolve_user(
    credentials: Optional[HTTPAuthorizationCredentials],
    db: Session,
) -> models.User:
    """Resolve a user from a Bearer JWT or an API token."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Not authenticated")

    token = credentials.credentials

    # Try API token first (they are longer and URL-safe; JWTs contain dots)
    if "." not in token:
        token_hash = hash_api_token(token)
        api_tok = (
            db.query(models.APIToken)
            .filter(
                models.APIToken.token_hash == token_hash,
                models.APIToken.is_active.is_(True),
            )
            .first()
        )
        if not api_tok:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Invalid API token")
        if api_tok.expires_at and api_tok.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="API token expired")
        # Update last used
        api_tok.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        user = db.query(models.User).filter(models.User.id == api_tok.user_id).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Token owner inactive")
        return user

    # JWT path
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise JWTError("invalid token type — only access tokens are accepted here")
        username: str = payload.get("sub")
        if not username:
            raise JWTError("no sub")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token")

    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="User not found or inactive")
    # Token version check — if an admin bumps token_version, all prior JWTs are
    # immediately rejected even if they haven't expired yet.
    if payload.get("tv", 0) != (user.token_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Session revoked — please log in again")
    return user


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    return await _resolve_user(credentials, db)


async def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Admin role required")
    return user


async def require_contributor(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role not in ("admin", "contributor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Contributor role or higher required")
    return user


async def require_viewer(user: models.User = Depends(get_current_user)) -> models.User:
    # admin, contributor, viewer, auditor all pass
    return user


