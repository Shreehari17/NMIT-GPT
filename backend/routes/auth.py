import re

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field, field_validator

from RAG_ENGINE.src.db import get_supabase_client
from backend.auth_utils import (
    hash_password,
    verify_password,
    create_access_token,
    validate_password_strength,
    login_throttle,
    client_ip,
    CurrentUser,
    get_current_user,
)

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.]{3,32}$")

router = APIRouter(prefix="/auth", tags=["Auth"])
supabase = get_supabase_client()

# Roles that can be self-assigned via /auth/register. "admin" is
# deliberately excluded — admin accounts are created directly in the
# database (see data_pipeline/supabase/users_table.sql) so that nobody can
# grant themselves admin/upload access through the public API.
SELF_SIGNUP_ROLES = ("student", "faculty")


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    username: str
    password: str
    role: str  # "student" or "faculty"

    @field_validator("username")
    @classmethod
    def _username_shape(cls, v: str) -> str:
        v = v.strip()
        if not _USERNAME_RE.match(v):
            raise ValueError(
                "Username must be 3-32 characters and contain only letters, numbers, '.' or '_'."
            )
        return v

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        error = validate_password_strength(v)
        if error:
            raise ValueError(error)
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/register")
def register(request: RegisterRequest):
    if request.role not in SELF_SIGNUP_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"role must be one of: {', '.join(SELF_SIGNUP_ROLES)}",
        )

    existing = (
        supabase.table("users")
        .select("id")
        .eq("username", request.username)
        .execute()
        .data
    )
    if existing:
        # Deliberately vague to avoid confirming/denying account existence
        # any more than strictly necessary for a signup flow.
        raise HTTPException(status_code=409, detail="That username is already taken.")

    row = {
        "name": request.name.strip(),
        "username": request.username,  # already normalized by the validator
        "password_hash": hash_password(request.password),
        "role": request.role,
    }
    inserted = supabase.table("users").insert(row).execute().data[0]

    user = CurrentUser(id=inserted["id"], username=inserted["username"], name=inserted["name"], role=inserted["role"])
    token = create_access_token(user)
    return {"access_token": token, "token_type": "bearer", "role": user.role, "name": user.name}


@router.post("/login")
def login(request: LoginRequest, http_request: Request):
    ip = client_ip(http_request)
    username = request.username.strip()

    # Reject up front if this username/IP pair is currently locked out from
    # too many recent failures — avoids even touching the DB or bcrypt.
    login_throttle.check(username, ip)

    rows = (
        supabase.table("users")
        .select("id, name, username, password_hash, role")
        .eq("username", username)
        .execute()
        .data
    )

    # Always run bcrypt against *something*, even for unknown usernames, so
    # response timing doesn't leak whether the account exists.
    valid = bool(rows) and verify_password(request.password, rows[0]["password_hash"])
    if not valid:
        verify_password(request.password, hash_password("dummy-timing-equalizer"))
        login_throttle.record_failure(username, ip)
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    login_throttle.record_success(username, ip)
    row = rows[0]
    user = CurrentUser(id=row["id"], username=row["username"], name=row["name"], role=row["role"])
    token = create_access_token(user)
    return {"access_token": token, "token_type": "bearer", "role": user.role, "name": user.name}


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    return user
