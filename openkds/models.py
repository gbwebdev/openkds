from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class OrderStatus(str, Enum):
    EN_PREPARATION = "en_preparation"
    LIVRE = "livre"
    ANNULE = "annule"


class OrderCreate(BaseModel):
    items: dict[str, int]

    @model_validator(mode="after")
    def check_not_empty(self):
        if sum(v for v in self.items.values() if v > 0) == 0:
            raise ValueError("Order cannot be empty")
        return self


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


class OrderDelayUpdate(BaseModel):
    additional_seconds: int = Field(gt=0, le=3600)


class GrillStockUpdate(BaseModel):
    model_config = {"extra": "allow"}


class PrinterTestRequest(BaseModel):
    printer: str  # printer ID, or "all"


class ConfigUpdate(BaseModel):
    grill_window_minutes: Optional[int] = None
    grill_segment_size: Optional[int] = None
    grill_demand_threshold: Optional[int] = None
    next_order_number: Optional[int] = None
    printer_devices: Optional[dict] = None
    button_colors: Optional[dict] = None
    org_name: Optional[str] = None
    event_name: Optional[str] = None
    auto_delivery_enabled: Optional[bool] = None
    auto_delivery_minutes: Optional[float] = None
