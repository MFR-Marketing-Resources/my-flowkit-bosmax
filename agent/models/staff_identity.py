from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StaffProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    staff_id: str
    display_name: str
    active: bool
    created_at: datetime | str
    updated_at: datetime | str


class StaffProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Display name is collected only by the profile-management surface. It is
    # never accepted as per-generation attribution.
    display_name: str = Field(min_length=1, max_length=160)


class StaffProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    active: bool | None = None


class StaffProfilesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiles: list[StaffProfileResponse]
