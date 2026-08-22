from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SetupOwnerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=256)
    password_confirmation: str = Field(min_length=12, max_length=256)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class PasswordTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=512)
    password: str = Field(min_length=12, max_length=256)
    password_confirmation: str = Field(min_length=12, max_length=256)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=12, max_length=256)
    password_confirmation: str = Field(min_length=12, max_length=256)


class InviteStaffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=320)
    role_codes: list[str] = Field(default_factory=lambda: ["VIEWER"], max_length=5)


class UpdateStaffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    email: str | None = Field(default=None, min_length=3, max_length=320)


class RoleAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_codes: list[str] = Field(min_length=1, max_length=5)


class RolePermissionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permission_codes: list[str] = Field(max_length=64)


class SessionRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="OWNER_REVOKED", min_length=1, max_length=80)
