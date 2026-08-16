from datetime import datetime, timedelta, timezone

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

import jwt
from jwt import InvalidTokenError

from passlib.context import CryptContext

from sqlalchemy.orm import Session

from app.database import get_db

from app.models.user import User

from app.config import settings
from app.schemas.platform_audit import RegisterRequest
from app.services.platform_audit import (
    PlatformAuditIntent,
    record_failed_platform_event,
    record_platform_event,
)



router = APIRouter(prefix="/api/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")





def create_access_token(data: dict):

    to_encode = data.copy()

    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)

    to_encode.update({"exp": expire})

    return jwt.encode(
        to_encode,
        settings.resolved_secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )





def get_current_user(

    token: str = Depends(oauth2_scheme),

    db: Session = Depends(get_db),

) -> User:

    try:

        payload = jwt.decode(
            token,
            settings.resolved_secret_key.get_secret_value(),
            algorithms=[settings.algorithm],
        )

        user_id = payload.get("sub")
        if not isinstance(user_id, str):
            raise ValueError("JWT subject must be a UUID string")
        user_id = uuid.UUID(user_id)

    except (InvalidTokenError, TypeError, ValueError, AttributeError):

        raise HTTPException(401, "Invalid token")

    user = db.query(User).filter(User.id == user_id).first()

    if user is None:

        raise HTTPException(401, "User not found")

    return user





@router.post("/login")
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):

    user = db.query(User).filter(User.username == form.username).first()

    if not user or not pwd_context.verify(form.password, user.password_hash):
        record_platform_event(
            db,
            actor=None,
            request=request,
            intent=PlatformAuditIntent(
                action="auth.login.failed",
                resource_type="user",
                changes={"username": form.username},
            ),
            result="failed",
            error_code="INVALID_CREDENTIALS",
        )
        db.commit()
        raise HTTPException(401, "Invalid credentials")

    token = create_access_token({"sub": str(user.id)})
    record_platform_event(
        db,
        actor=user,
        request=request,
        intent=PlatformAuditIntent(
            action="auth.login.success",
            resource_type="user",
            resource_id=str(user.id),
            changes={"username": user.username},
        ),
        result="success",
    )
    db.commit()

    return {"access_token": token, "token_type": "bearer", "user_id": str(user.id), "role": user.role}





@router.post("/register")
def register(
    data: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.username == data.username).first()

    if existing:
        record_failed_platform_event(
            db,
            actor=None,
            request=request,
            intent=PlatformAuditIntent(
                action="auth.register.failed",
                resource_type="user",
                changes={"username": data.username},
            ),
            error_code="USERNAME_EXISTS",
        )
        raise HTTPException(400, {"code": "USERNAME_EXISTS"})

    user = User(
        username=data.username,
        password_hash=pwd_context.hash(data.password),
        role="engineer",
    )

    db.add(user)
    db.flush()
    record_platform_event(
        db,
        actor=user,
        request=request,
        intent=PlatformAuditIntent(
            action="auth.register",
            resource_type="user",
            resource_id=str(user.id),
            changes={"username": user.username},
        ),
        result="success",
    )
    db.commit()

    return {"message": "User created", "user_id": str(user.id)}




@router.get("/me")
def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    return {
        "id": str(current_user.id),
        "username": current_user.username,
        "role": current_user.role,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }


@router.put("/change-password")
def change_password(
    old_password: str = Body(...),
    new_password: str = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not pwd_context.verify(old_password, current_user.password_hash):
        raise HTTPException(400, "??????")
    current_user.password_hash = pwd_context.hash(new_password)
    db.commit()
    return {"message": "??????"}
