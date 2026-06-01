from pydantic import BaseModel, model_validator
from typing import Optional


class OrderCreate(BaseModel):
    adulte_merguez: int = 0
    adulte_chipo: int = 0
    enfant_merguez: int = 0
    enfant_chipo: int = 0
    galette_saucisse: int = 0
    barquette_frite: int = 0

    @model_validator(mode="after")
    def check_not_empty(self):
        total = (
            self.adulte_merguez + self.adulte_chipo +
            self.enfant_merguez + self.enfant_chipo +
            self.galette_saucisse + self.barquette_frite
        )
        if total == 0:
            raise ValueError("La commande ne peut pas être vide")
        return self


class Order(BaseModel):
    id: int
    number: int
    created_at: str
    adulte_merguez: int
    adulte_chipo: int
    enfant_merguez: int
    enfant_chipo: int
    galette_saucisse: int
    barquette_frite: int

    class Config:
        from_attributes = True


class OrderResponse(BaseModel):
    id: int
    number: int
    created_at: str
    printer1_status: str
    printer2_status: str


class GrillStockUpdate(BaseModel):
    merguez: Optional[int] = None
    chipo: Optional[int] = None
    saucisse: Optional[int] = None


class PrinterTestRequest(BaseModel):
    printer: int | str  # 1, 2, or "both"


class ConfigUpdate(BaseModel):
    grill_window_minutes: Optional[int] = None
    grill_segment_size: Optional[int] = None
    next_order_number: Optional[int] = None
    printer1_device: Optional[str] = None
    printer2_device: Optional[str] = None
    button_colors: Optional[dict] = None
    event_name: Optional[str] = None
