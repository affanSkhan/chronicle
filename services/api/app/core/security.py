from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models.entities import User

password_hasher = PasswordHasher()
bearer_scheme = HTTPBearer(auto_error=False)
JWT_ISSUER = "chronicle"


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        return password_hasher.verify(encoded_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def issue_access_token(user: User) -> tuple[str, int]:
    settings = get_settings()
    ttl_seconds = max(300, settings.jwt_access_token_expire_minutes * 60)
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": user.id,
            "email": user.email,
            "iss": JWT_ISSUER,
            "iat": now,
            "exp": now + timedelta(seconds=ttl_seconds),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )
    return token, ttl_seconds


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Sign in to access this resource.", headers={"WWW-Authenticate": "Bearer"})

    settings = get_settings()
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=["HS256"],
            issuer=JWT_ISSUER,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Your session is invalid or expired. Sign in again.", headers={"WWW-Authenticate": "Bearer"}) from exc

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Your session is invalid. Sign in again.", headers={"WWW-Authenticate": "Bearer"})

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="This account is unavailable. Sign in again.", headers={"WWW-Authenticate": "Bearer"})
    return user
