"""Pydantic request models."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Relationship = Literal["current_client", "interested", "prospect", "do_not_contact"]
Priority = Literal["high", "medium", "low"]
ContactRole = Literal["manager", "doctor", "nurse", "receptionist", "staff", "owner", "it", "other"]
ApptType = Literal["visit", "call", "demo", "install", "support", "other"]
ApptStatus = Literal["scheduled", "completed", "cancelled", "no_show"]


def _blank_to_none(v):
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


class ClinicIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: Optional[str] = None
    city: Optional[str] = "Calgary"
    province: Optional[str] = "AB"
    postal_code: Optional[str] = None
    phone: Optional[str] = None
    fax: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    relationship: Relationship = "prospect"
    clinic_type: Optional[str] = None
    emr_system: Optional[str] = None
    it_provider: Optional[str] = None
    provider_count: Optional[int] = None
    priority: Priority = "medium"
    tags: Optional[str] = None
    notes: Optional[str] = None
    next_follow_up: Optional[str] = None  # YYYY-MM-DD

    _blank = field_validator(
        "address", "city", "province", "postal_code", "phone", "fax", "email", "website",
        "clinic_type", "emr_system", "it_provider", "tags", "notes", "next_follow_up",
        "lat", "lng", "provider_count", mode="before",
    )(_blank_to_none)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name is required")
        return v


class ContactIn(BaseModel):
    clinic_id: Optional[int] = None
    first_name: str = Field(min_length=1, max_length=100)
    last_name: Optional[str] = None
    role: ContactRole = "staff"
    title: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    is_primary: bool = False
    notes: Optional[str] = None

    _blank = field_validator(
        "clinic_id", "last_name", "title", "phone", "mobile", "email", "notes", mode="before"
    )(_blank_to_none)


class AppointmentIn(BaseModel):
    clinic_id: int
    contact_id: Optional[int] = None
    title: str = Field(min_length=1, max_length=200)
    appt_type: ApptType = "visit"
    status: ApptStatus = "scheduled"
    start_time: str  # ISO 8601 local datetime, e.g. 2026-09-01T09:30
    end_time: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    outcome: Optional[str] = None

    _blank = field_validator("contact_id", "end_time", "location", "notes", "outcome", mode="before")(
        _blank_to_none
    )

    @field_validator("start_time", "end_time")
    @classmethod
    def _check_iso(cls, v):
        if v is None:
            return v
        from datetime import datetime

        try:
            datetime.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"invalid datetime: {v}") from exc
        return v


class AppointmentPatch(BaseModel):
    status: Optional[ApptStatus] = None
    outcome: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class NoteIn(BaseModel):
    body: str = Field(min_length=1)
    author: Optional[str] = None
