from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, hash_password, issue_access_token, verify_password
from app.models.entities import User
from app.schemas.auth import TokenResponse, UserLogin, UserPublic, UserRegister

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: UserRegister, db: Session = Depends(get_db)) -> dict:
    existing = db.scalar(select(User.id).where(func.lower(User.email) == payload.email))
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user = User(email=payload.email, password_hash=hash_password(payload.password), is_active=True)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc
    db.refresh(user)
    token, expires_in = issue_access_token(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": UserPublic.model_validate(user),
    }


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.", headers={"WWW-Authenticate": "Bearer"})

    token, expires_in = issue_access_token(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": UserPublic.model_validate(user),
    }


@router.get("/me", response_model=UserPublic)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user
