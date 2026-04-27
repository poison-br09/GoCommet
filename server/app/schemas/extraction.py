from pydantic import BaseModel, Field


class FieldValue(BaseModel):
    value: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class LineItem(BaseModel):
    description: str | None = None
    quantity: str | None = None
    hs_code: str | None = None
    origin: str | None = None
    incoterms: str | None = None
    unit_price: str | None = None
    currency: str | None = None
    net_weight: str | None = None
    gross_weight: str | None = None


class ExtractionOutput(BaseModel):
    consignee_name: FieldValue = Field(default_factory=FieldValue)
    hs_code: FieldValue = Field(default_factory=FieldValue)
    port_of_loading: FieldValue = Field(default_factory=FieldValue)
    port_of_discharge: FieldValue = Field(default_factory=FieldValue)
    incoterms: FieldValue = Field(default_factory=FieldValue)
    description_of_goods: FieldValue = Field(default_factory=FieldValue)
    gross_weight: FieldValue = Field(default_factory=FieldValue)
    invoice_number: FieldValue = Field(default_factory=FieldValue)
    global_confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    line_items: list[LineItem] | None = None
