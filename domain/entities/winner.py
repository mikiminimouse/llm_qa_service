"""Winner and participant models."""

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .enums import ParticipantStatus


class WinnerInfo(BaseModel):
    """Information about a winner."""

    name: str = Field(..., description="Наименование организации победителя")
    inn: Optional[str] = Field(None, description="ИНН победителя (10 или 12 цифр)")
    kpp: Optional[str] = Field(None, description="КПП победителя (9 цифр)")
    ogrn: Optional[str] = Field(None, description="ОГРН победителя (13 или 15 цифр)")
    address: Optional[str] = Field(None, description="Адрес победителя")
    contract_price: Optional[float] = Field(None, description="Цена контракта")
    status: ParticipantStatus = Field(
        default=ParticipantStatus.WINNER,
        description="Статус участника",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Уверенность в результате (0-1)",
    )

    @field_validator("inn")
    @classmethod
    def validate_inn(cls, v: Optional[str]) -> Optional[str]:
        """Validate INN format (10 or 12 digits)."""
        if v is None:
            return None
        v = re.sub(r"\s+", "", str(v))
        if v and not re.match(r"^\d{10}$|^\d{12}$", v):
            return None  # Return None for invalid format instead of raising
        return v

    @field_validator("kpp")
    @classmethod
    def validate_kpp(cls, v: Optional[str]) -> Optional[str]:
        """Validate KPP format (9 digits)."""
        if v is None:
            return None
        v = re.sub(r"\s+", "", str(v))
        if v and not re.match(r"^\d{9}$", v):
            return None
        return v

    @field_validator("ogrn")
    @classmethod
    def validate_ogrn(cls, v: Optional[str]) -> Optional[str]:
        """Validate OGRN format (13 or 15 digits)."""
        if v is None:
            return None
        v = re.sub(r"\s+", "", str(v))
        if v and not re.match(r"^\d{13}$|^\d{15}$", v):
            return None
        return v


class OtherParticipant(BaseModel):
    """Information about other participants (not winners)."""

    name: str = Field(..., description="Наименование организации")
    inn: Optional[str] = Field(None, description="ИНН участника")
    status: ParticipantStatus = Field(
        default=ParticipantStatus.ADMITTED,
        description="Статус участника",
    )
    rejection_reason: Optional[str] = Field(
        None,
        description="Причина отклонения (если отклонён)",
    )
    proposed_price: Optional[float] = Field(
        None,
        description="Предложенная цена",
    )

    @field_validator("inn")
    @classmethod
    def validate_inn(cls, v: Optional[str]) -> Optional[str]:
        """Validate INN format."""
        if v is None:
            return None
        v = re.sub(r"\s+", "", str(v))
        if v and not re.match(r"^\d{10}$|^\d{12}$", v):
            return None
        return v
