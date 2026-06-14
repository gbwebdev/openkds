from __future__ import annotations

from pydantic import BaseModel, model_validator
from typing import Optional


class OrderCreate(BaseModel):
    items: dict[str, int]

    @model_validator(mode="after")
    def check_not_empty(self):
        if sum(v for v in self.items.values() if v > 0) == 0:
            raise ValueError("Order cannot be empty")
        return self


class GrillStockUpdate(BaseModel):
    model_config = {"extra": "allow"}


class PrinterTestRequest(BaseModel):
    printer: int | str  # 1, 2, or "both"


class ConfigUpdate(BaseModel):
    grill_window_minutes: Optional[int] = None
    grill_segment_size: Optional[int] = None
    next_order_number: Optional[int] = None
    printer1_device: Optional[str] = None
    printer2_device: Optional[str] = None
    button_colors: Optional[dict] = None
    org_name: Optional[str] = None
    event_name: Optional[str] = None
