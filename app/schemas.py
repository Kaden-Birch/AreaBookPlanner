"""Pydantic request models."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Relationship = Literal["current_client", "interested", "prospect", "do_not_contact"]
Priority = Literal["high", "medium", "low"]
ContactRole = Literal["manager", "doctor", "nurse", "receptionist", "staff", "owner", "it", "other"]
ApptType = Literal["visit", "call", "demo", "install", "support", "other"]
ApptStatus = Literal["scheduled", "completed", "cancelled", "no_show"]
Stage = Literal["lead", "prospect", "demo", "proposal", "won", "lost"]


def _blank_to_none(v):
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


class ClinicIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: Optional[str] = None
    display_address: Optional[str] = None  # shown on the clinic page; falls back to `address`
    city: Optional[str] = "Calgary"
    province: Optional[str] = "AB"
    postal_code: Optional[str] = None
    hours: Optional[dict] = None  # {mon: {closed, open, close}, ...}
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
    stage: Stage = "lead"
    deal_value: Optional[float] = Field(default=None, ge=0, description="Estimated annual contract value")
    expected_close: Optional[str] = None  # YYYY-MM-DD
    win_probability: Optional[int] = Field(default=None, ge=0, le=100)
    outcome_reason: Optional[str] = None
    outcome_notes: Optional[str] = None
    outcome_date: Optional[str] = None
    # Client-specific
    shorthand: Optional[str] = Field(default=None, max_length=10)
    group_id: Optional[int] = None
    # Contract & recurring revenue (mostly relevant once a client)
    mrr: Optional[float] = Field(default=None, ge=0, description="Monthly recurring revenue")
    contract_start: Optional[str] = None  # YYYY-MM-DD
    contract_end: Optional[str] = None  # YYYY-MM-DD
    contract_term_months: Optional[int] = Field(default=None, ge=0, le=120)
    auto_renew: bool = False
    renewal_reminder_days: Optional[int] = Field(default=None, ge=0, le=365)
    # Competitor / displacement (it_provider holds the competitor's name)
    competitor_contract_end: Optional[str] = None  # YYYY-MM-DD

    _blank = field_validator(
        "address", "display_address", "city", "province", "postal_code", "phone", "fax", "email", "website",
        "clinic_type", "emr_system", "it_provider", "tags", "notes", "next_follow_up",
        "lat", "lng", "provider_count", "deal_value", "expected_close", "win_probability",
        "outcome_reason", "outcome_notes", "outcome_date", "shorthand", "group_id",
        "mrr", "contract_start", "contract_end", "contract_term_months", "renewal_reminder_days",
        "competitor_contract_end", mode="before",
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
    # Optional context this note is attached to (at most one).
    appointment_id: Optional[int] = None
    task_id: Optional[int] = None
    attachment_id: Optional[int] = None

    _blank = field_validator("author", "appointment_id", "task_id", "attachment_id", mode="before")(_blank_to_none)


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
    company_name: Optional[str] = None
    company_contact: Optional[str] = None
    quote_terms: Optional[str] = None
    quote_tax_pct: Optional[float] = None
    quote_valid_days: Optional[int] = None
    onboarding_enabled: Optional[bool] = None
    onboarding_template: Optional[list[dict]] = None


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
    link_type: Optional[Literal["ethernet", "wireless", "virtual"]] = None
    status: DeviceStatus = "active"
    off_site: bool = False
    rack: Optional[str] = None
    rack_room: Optional[str] = None
    rack_position: Optional[int] = Field(default=None, ge=1, le=60)
    rack_units: Optional[int] = Field(default=None, ge=1, le=48)
    shelf_id: Optional[int] = None
    services: Optional[list[str]] = None
    purchase_date: Optional[str] = None
    warranty_until: Optional[str] = None
    notes: Optional[str] = None
    quantity: int = Field(default=1, ge=1, le=50)  # create several at once (auto-named)

    _blank = field_validator(
        "name", "location_id", "designation", "manufacturer", "model", "serial", "ip_address", "mac_address", "os",
        "user_name", "uplink_id", "link_type", "purchase_date", "warranty_until", "notes",
        "rack", "rack_room", "rack_position", "rack_units", "shelf_id", mode="before",
    )(_blank_to_none)


    @field_validator("services", mode="before")
    @classmethod
    def _services(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = v.replace(",", "\n").splitlines()
        return [str(x).strip() for x in v if str(x).strip()] or None


class ConnectionIn(BaseModel):
    """Add a secondary uplink (extra topology link) to a device."""
    uplink_id: int
    link_type: Optional[Literal["ethernet", "wireless", "virtual"]] = None
    notes: Optional[str] = None

    _blank = field_validator("link_type", "notes", mode="before")(_blank_to_none)


class EdgeOp(BaseModel):
    """Connect or disconnect two devices from the topology view. child links up to parent."""
    child_id: int
    parent_id: Optional[int] = None
    link_type: Optional[Literal["ethernet", "wireless", "virtual"]] = None


class TicketIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    url: Optional[str] = None
    ticket_date: Optional[str] = None
    notes: Optional[str] = None

    _blank = field_validator("url", "ticket_date", "notes", mode="before")(_blank_to_none)


class PriceItemIn(BaseModel):
    key: Optional[str] = None
    label: str = Field(min_length=1, max_length=200)
    category: str = "extras"
    unit: str = "per_month"
    alt_unit: Optional[str] = None
    mode_group: Optional[str] = None
    price: Optional[float] = None
    alt_price: Optional[float] = None
    description: Optional[str] = None
    active: bool = True

    _blank = field_validator("key", "alt_unit", "mode_group", "price", "alt_price", "description", mode="before")(_blank_to_none)


class PriceBookIn(BaseModel):
    items: list[PriceItemIn]


class QuoteLineIn(BaseModel):
    key: str
    label: str
    category: str = "extras"
    unit: str = "per_month"
    qty: float = 0
    unit_price: float = 0
    included: bool = True
    note: Optional[str] = None

    _blank = field_validator("note", mode="before")(_blank_to_none)


class QuoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    pricing_mode: Literal["per_device", "per_user"] = "per_device"
    emr_mode: Literal["flat", "per_user"] = "flat"
    plan_key: Optional[str] = None
    user_count: int = 0
    device_count: int = 0
    counts: Optional[dict] = None
    lines: list[QuoteLineIn]
    discount_pct: float = 0
    tax_pct: float = 0
    notes: Optional[str] = None
    terms: Optional[str] = None
    prepared_by: Optional[str] = None
    contact_id: Optional[int] = None
    valid_until: Optional[str] = None

    _blank = field_validator("plan_key", "notes", "terms", "prepared_by", "contact_id", "valid_until", mode="before")(_blank_to_none)


class QuoteStatusIn(BaseModel):
    status: Literal["draft", "sent", "accepted", "declined", "expired"]


# ---- Inventory / orders / invoices ------------------------------------------

class InventoryItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sku: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    unit_price: Optional[float] = Field(default=None, ge=0)
    cost: Optional[float] = Field(default=None, ge=0)
    quantity: int = Field(default=0, ge=0)
    reorder_level: Optional[int] = Field(default=None, ge=0)
    supplier: Optional[str] = None
    notes: Optional[str] = None

    _blank = field_validator("sku", "category", "description", "location", "unit_price", "cost",
                             "reorder_level", "supplier", "notes", mode="before")(_blank_to_none)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name is required")
        return v.strip()


class StockAdjustIn(BaseModel):
    delta: int  # +/- change to quantity on hand
    note: Optional[str] = None

    _blank = field_validator("note", mode="before")(_blank_to_none)


OrderStatus = Literal["ordered", "received", "cancelled"]


class OrderIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    item_id: Optional[int] = None          # link to an existing inventory item, or None for a new/custom item
    clinic_id: Optional[int] = None         # ordered on behalf of a specific clinic
    sku: Optional[str] = None
    supplier: Optional[str] = None
    quantity: int = Field(default=1, ge=1)
    unit_cost: Optional[float] = Field(default=None, ge=0)
    unit_price: Optional[float] = Field(default=None, ge=0)
    status: OrderStatus = "ordered"
    ordered_date: Optional[str] = None
    expected_date: Optional[str] = None
    ticket_url: Optional[str] = None
    notes: Optional[str] = None

    _blank = field_validator("item_id", "clinic_id", "sku", "supplier", "unit_cost", "unit_price",
                             "ordered_date", "expected_date", "ticket_url", "notes", mode="before")(_blank_to_none)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name is required")
        return v.strip()


class OrderReceiveIn(BaseModel):
    """How to handle an order when it arrives."""
    disposition: Literal["inventory", "invoice"]
    # disposition == "inventory": add to (item_id) or create a new inventory item
    item_id: Optional[int] = None
    # disposition == "invoice": append a line to (invoice_id), or start a new draft invoice for (clinic_id)
    invoice_id: Optional[int] = None
    clinic_id: Optional[int] = None

    _blank = field_validator("item_id", "invoice_id", "clinic_id", mode="before")(_blank_to_none)


class InvoiceLineIn(BaseModel):
    item_id: Optional[int] = None
    description: str = Field(min_length=1, max_length=300)
    quantity: float = Field(default=1, ge=0)
    unit_price: float = Field(default=0, ge=0)

    _blank = field_validator("item_id", mode="before")(_blank_to_none)


class InvoiceIn(BaseModel):
    title: Optional[str] = None
    contact_id: Optional[int] = None
    issue_date: Optional[str] = None
    due_date: Optional[str] = None
    ticket_url: Optional[str] = None
    notes: Optional[str] = None
    tax_pct: float = Field(default=0, ge=0)
    discount_pct: float = Field(default=0, ge=0, le=100)
    lines: list[InvoiceLineIn] = Field(default_factory=list)

    _blank = field_validator("title", "contact_id", "issue_date", "due_date", "ticket_url", "notes", mode="before")(_blank_to_none)


class InvoiceStatusIn(BaseModel):
    status: Literal["draft", "sent", "paid", "void"]


class ClinicTicketIn(BaseModel):
    """A support ticket (e.g. from SyncroMSP) linked to a clinic."""
    title: str = Field(min_length=1, max_length=300)
    url: Optional[str] = None
    ticket_at: Optional[str] = None          # ISO datetime; defaults to now if omitted
    device_id: Optional[int] = None          # existing machine in the topology
    device_name: Optional[str] = None        # or a name; created as a workstation if it doesn't exist
    notes: Optional[str] = None

    _blank = field_validator("url", "ticket_at", "device_id", "device_name", "notes", mode="before")(_blank_to_none)

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title is required")
        return v.strip()
