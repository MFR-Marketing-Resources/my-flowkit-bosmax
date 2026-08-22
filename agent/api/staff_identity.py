from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path

from agent.models.staff_identity import (
    StaffProfileCreateRequest,
    StaffProfileResponse,
    StaffProfileUpdateRequest,
    StaffProfilesResponse,
)
from agent.services import staff_identity_service as staff

router = APIRouter(prefix="/staff", tags=["staff-identity"])


def _http(exc: staff.StaffIdentityError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"error": exc.code, "message": exc.message},
    )


@router.get("/profiles", response_model=StaffProfilesResponse)
async def list_profiles(include_inactive: bool = True) -> StaffProfilesResponse:
    return StaffProfilesResponse(
        profiles=await staff.list_staff_profiles(include_inactive=include_inactive)
    )


@router.post("/profiles", response_model=StaffProfileResponse, status_code=201)
async def create_profile(body: StaffProfileCreateRequest) -> StaffProfileResponse:
    try:
        return await staff.create_staff_profile(body.display_name)
    except staff.StaffIdentityError as exc:
        raise _http(exc) from exc


@router.get("/profiles/{staff_id}", response_model=StaffProfileResponse)
async def get_profile(staff_id: str = Path(min_length=1, max_length=80)) -> StaffProfileResponse:
    try:
        return await staff.resolve_staff_identity(staff_id, require_active=False)
    except staff.StaffIdentityError as exc:
        raise _http(exc) from exc


@router.patch("/profiles/{staff_id}", response_model=StaffProfileResponse)
async def patch_profile(
    body: StaffProfileUpdateRequest,
    staff_id: str = Path(min_length=1, max_length=80),
) -> StaffProfileResponse:
    try:
        return await staff.update_staff_profile(
            staff_id,
            display_name=body.display_name,
            active=body.active,
        )
    except staff.StaffIdentityError as exc:
        raise _http(exc) from exc


@router.get("/resolve/{staff_id}", response_model=StaffProfileResponse)
async def resolve_active_profile(
    staff_id: str = Path(min_length=1, max_length=80),
) -> StaffProfileResponse:
    try:
        return await staff.resolve_staff_identity(staff_id)
    except staff.StaffIdentityError as exc:
        raise _http(exc) from exc
