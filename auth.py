
import os
from datetime import datetime, timedelta, timezone
from typing import Generator, Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, declarative_base, sessionmaker

load_dotenv()

# ============================================================
# CONFIGURATION
# ============================================================

SECRET_KEY = os.getenv("SECRET_KEY")

if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is missing. Add it to your .env file."
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# SQLite par défaut.
# La valeur définie dans .env est prioritaire.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./users.db",
)

connect_args = (
    {"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


# ============================================================
# DATABASE MODEL
# ============================================================

class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    username = Column(
        String,
        unique=True,
        index=True,
        nullable=False,
    )

    email = Column(
        String,
        unique=True,
        index=True,
        nullable=False,
    )

    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)

    disabled = Column(
        Boolean,
        default=False,
        nullable=False,
    )

    role = Column(
        String,
        default="user",
        nullable=False,
    )


# Create the database table if it does not exist.
Base.metadata.create_all(bind=engine)


# ============================================================
# PYDANTIC MODELS
# ============================================================

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None


class User(BaseModel):
    username: str
    email: EmailStr
    full_name: Optional[str] = None
    disabled: bool = False
    role: str = "user"

    model_config = ConfigDict(from_attributes=True)


class UserInDB(User):
    hashed_password: str


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    role: str = "user"


# ============================================================
# DATABASE SESSION
# ============================================================

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


# ============================================================
# PASSWORD UTILITIES
# ============================================================

def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    return pwd_context.verify(
        plain_password,
        hashed_password,
    )


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


# ============================================================
# USER UTILITIES
# ============================================================

def get_user(
    db: Session,
    username: str,
) -> Optional[UserInDB]:
    user = (
        db.query(UserDB)
        .filter(UserDB.username == username)
        .first()
    )

    if user is None:
        return None

    return UserInDB.model_validate(user)


def authenticate_user(
    db: Session,
    username: str,
    password: str,
):
    user = get_user(db, username)

    if user is None:
        return False

    if not verify_password(
        password,
        user.hashed_password,
    ):
        return False

    return user


# ============================================================
# INSERT USER
# ============================================================

def _insert_user(
    db: Session,
    user_data: UserCreate,
    role: str = "user",
):
    hashed_password = get_password_hash(
        user_data.password
    )

    db_user = UserDB(
        username=user_data.username,
        email=str(user_data.email),
        hashed_password=hashed_password,
        full_name=user_data.full_name,
        disabled=False,
        role=role,
    )

    try:
        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        return User.model_validate(db_user)

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered.",
        )


# ============================================================
# CREATE REGULAR USER
# ============================================================

def create_user(
    db: Session,
    user_data: UserCreate,
):
    # Never allow a public signup to assign the admin role.
    return _insert_user(
        db=db,
        user_data=user_data,
        role="user",
    )


# ============================================================
# CREATE ADMIN USER
# Supports both UserCreate and keyword arguments from api.py.
# ============================================================

def create_admin_user(
    db: Session,
    user_data: Optional[UserCreate] = None,
    username: Optional[str] = None,
    email: Optional[str] = None,
    password: Optional[str] = None,
    full_name: Optional[str] = None,
):
    # Build UserCreate when api.py passes individual fields.
    if user_data is None:
        if not username or not email or not password:
            raise ValueError(
                "username, email and password are required "
                "to create an admin."
            )

        user_data = UserCreate(
            username=username,
            email=email,
            password=password,
            full_name=full_name,
        )

    existing_user = (
        db.query(UserDB)
        .filter(
            (UserDB.username == user_data.username)
            | (UserDB.email == str(user_data.email))
        )
        .first()
    )

    if existing_user:
        if existing_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "The configured admin username or email "
                    "belongs to a non-admin account."
                ),
            )

        return User.model_validate(existing_user)

    return _insert_user(
        db=db,
        user_data=user_data,
        role="admin",
    )


# ============================================================
# JWT TOKEN CREATION
# ============================================================

def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta | int] = None,
) -> str:
    payload = data.copy()

    if expires_delta is None:
        expires_delta = timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )

    elif isinstance(expires_delta, int):
        # Integer values are interpreted as minutes.
        expires_delta = timedelta(
            minutes=expires_delta
        )

    expiry = datetime.now(timezone.utc) + expires_delta

    payload["exp"] = expiry

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


# ============================================================
# AUTHENTICATED USER
# ============================================================

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
        )

        username = payload.get("sub")

        if not username:
            raise credentials_exception

        token_data = TokenData(username=username)

    except JWTError:
        raise credentials_exception

    user = get_user(
        db,
        username=token_data.username,
    )

    if user is None:
        raise credentials_exception

    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
):
    if current_user.disabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user.",
        )

    return current_user


# ============================================================
# ROLE-BASED ACCESS CONTROL
# ============================================================

def require_role(required_role: str):
    def role_checker(
        current_user: User = Depends(
            get_current_active_user
        ),
    ):
        if current_user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )

        return current_user

    return role_checker
