"""Pydantic request models."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Relationship = Literal["current_client", "interested", "prospect", "do_not_contact"]
Priority = Literal["high", "medium", "low"]
ContactRole = Literal["manager", "doctor", "nurse", "receptionist", "staff", "owner", "it", "other"]
ApptType = Literal["visit", "call", "demo", "install", "support", "other"]
ApptStatus = Literal["scheduled", "completed", "cancelled", "no_show"]
Stage = Literal["prospect", "contacted", "demo", "proposal", "won", "lost"]


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
    # Pipeline / deal tracking
    stage: Stage = "prospect"
    deal_value: Optional[float] = Field(default=None, ge=0, description="Estimated annual contract value")
    expected_close: Optional[str] = None  # YYYY-MM-DD
    win_probability: Optional[int] = Field(default=None, ge=0, le=100)
    outcome_reason: Optional[str] = None
    outcome_notes: Optional[str] = None
    outcome_date: Optional[str] = None
    # Client-specific
    shorthand: Optional[str] = Field(default=None, max_length=10)
    group_id: Optional[int] = None

    _blank = field_validator(
        "address", "city", "province", "postal_code", "phone", "fax", "email", "website",
        "clinic_type", "emr_system", "it_provider", "tags", "notes", "next_follow_up",
        "lat", "lng", "provider_count", "deal_value", "expected_close", "win_probability",
        "outcome_reason", "outcome_notes", "outcome_date", "shorthand", "group_id", mode="before",
    )(_blank_to_none)

    @field_validator("shorthand")
    @classmethod
    def _upper(cls, v):
        return v.strip().upper() if v else v

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
    extension: Optional[str] = None
    use_main_line: bool = False
    mobile: Optional[str] = None
    email: Optional[str] = None
    is_primary: bool = False
    shared_with_group: bool = False
    notes: Optional[str] = None

    _blank = field_validator(
        "clinic_id", "last_name", "title", "phone", "extension", "mobile", "email", "notes", mode="before"
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
    reminder_minutes: Optional[int] = None
    rep: Optional[str] = None

    _blank = field_validator("contact_id", "end_time", "location", "notes", "outcome", "reminder_minutes", "rep", mode="before")(
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
    kind: str = "note"

    _blank = field_validator("author", mode="before")(_blank_to_none)


class QuickLogIn(BaseModel):
    preset: str
    author: Optional[str] = None
    detail: Optional[str] = None

    _blank = field_validator("author", "detail", mode="before")(_blank_to_none)


class StageChange(BaseModel):
    """Move a clinic along the pipeline (used by the Kanban board)."""
    stage: Stage
    outcome_reason: Optional[str] = None
    outcome_notes: Optional[str] = None
    outcome_date: Optional[str] = None  # allow back-dating (e.g. onboarded years ago)

    _blank = field_validator("outcome_reason", "outcome_notes", "outcome_date", mode="before")(_blank_to_none)


class ArchiveIn(BaseModel):
    archived: bool = True


class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: Optional[str] = None
    city: Optional[str] = "Calgary"
    province: Optional[str] = "AB"
    postal_code: Optional[str] = None
    phone: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    notes: Optional[str] = None

    _blank = field_validator("address", "city", "province", "postal_code", "phone", "lat", "lng", "notes", mode="before")(_blank_to_none)


class LinkIn(BaseModel):
    other_clinic_id: int
    link_type: str = "other"
    notes: Optional[str] = None

    _blank = field_validator("notes", mode="before")(_blank_to_none)


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    notes: Optional[str] = None

    _blank = field_validator("notes", mode="before")(_blank_to_none)


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=300)
    body: str = ""


class SavedViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    page: str = "map"
    state: dict


class ImportRequest(BaseModel):
    rows: list[dict]
    skip_duplicates: bool = True


class BulkGeocodeRequest(BaseModel):
    clinic_ids: Optional[list[int]] = None


class TaskIn(BaseModel):
    clinic_id: Optional[int] = None
    contact_id: Optional[int] = None
    title: str = Field(min_length=1, max_length=200)
    notes: Optional[str] = None
    due_date: Optional[str] = None  # YYYY-MM-DD
    due_time: Optional[str] = None  # HH:MM
    reminder_minutes: Optional[int] = None
    rep: Optional[str] = None
    priority: Priority = "medium"
    done: bool = False

    _blank = field_validator("clinic_id", "contact_id", "notes", "due_date", "due_time", "reminder_minutes", "rep", mode="before")(_blank_to_none)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title is required")
        return v


class TaskPatch(BaseModel):
    done: Optional[bool] = None
    due_date: Optional[str] = None


class LatLng(BaseModel):
    lat: float
    lng: float


class RouteRequest(BaseModel):
    clinic_ids: list[int] = Field(min_length=1)
    start: Optional[LatLng] = None
    return_to_start: bool = False


class SettingsIn(BaseModel):
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None


DeviceStatus = Literal["active", "spare", "retired"]


class DeviceIn(BaseModel):
    device_type: str
    name: Optional[str] = None  # blank = auto-generate from the template
    location_id: Optional[int] = None
    designation: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial: Optional[str] = None
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    os: Optional[str] = None
    user_name: Optional[str] = None
    uplink_id: Optional[int] = None
    link_type: Optional[Literal["ethernet", "wireless"]] = None
    status: DeviceStatus = "active"
    services: Optional[list[str]] = None
    purchase_date: Optional[str] = None
    warranty_until: Optional[str] = None
    notes: Optional[str] = None
    quantity: int = Field(default=1, ge=1, le=50)  # create several at once (auto-named)

    _blank = field_validator(
        "name", "location_id", "designation", "manufacturer", "model", "serial", "ip_address", "mac_address", "os",
        "user_name", "uplink_id", "link_type", "purchase_date", "warranty_until", "notes", mode="before",
    )(_blank_to_none)

    @field_validator("services", mode="before")
    @classmethod
    def _services(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = v.replace(",", "\n").splitlines()
        return [str(x).strip() for x in v if str(x).strip()] or None


class TicketIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    url: Optional[str] = None
    ticket_date: Optional[str] = None
    notes: Optional[str] = None

    _blank = field_validator("url", "ticket_date", "notes", mode="before")(_blank_to_none)
