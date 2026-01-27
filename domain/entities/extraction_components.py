"""Extraction component models."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from .enums import DocumentType, NotHeldReason, ProcurementStatus


class CustomerInfo(BaseModel):
    """Information about the customer (zakazchik) - NOT the winner."""

    name: Optional[str] = Field(
        None,
        description="Наименование заказчика",
    )
    inn: Optional[str] = Field(
        None,
        description="ИНН заказчика (для сверки, что не путаем с победителем)",
    )


class ProcurementInfo(BaseModel):
    """Information about the procurement procedure."""

    purchase_number: Optional[str] = Field(
        None,
        description="Номер закупки (реестровый номер) - УСТАРЕЛО, используйте purchase_notice_number",
    )
    purchase_notice_number: Optional[str] = Field(
        None,
        description="Номер госзакупки (purchaseNoticeNumber) - 11 цифр для 223-ФЗ",
    )
    purchase_name: Optional[str] = Field(
        None,
        description="Наименование закупки",
    )
    lot_number: Optional[str] = Field(
        None,
        description="Номер лота",
    )
    initial_price: Optional[float] = Field(
        None,
        description="Начальная (максимальная) цена контракта",
    )
    final_price: Optional[float] = Field(
        None,
        description="Итоговая цена контракта",
    )
    status: ProcurementStatus = Field(
        default=ProcurementStatus.UNKNOWN,
        description="Статус процедуры",
    )
    not_held_reason: Optional[NotHeldReason] = Field(
        None,
        description="Причина несостоявшейся закупки",
    )
    protocol_date: Optional[datetime] = Field(
        None,
        description="Дата протокола",
    )
    protocol_number: Optional[str] = Field(
        None,
        description="Номер протокола",
    )


class ExtractionFlags(BaseModel):
    """Flags for special extraction cases."""

    is_service_file: bool = Field(
        default=False,
        description="Служебный файл (не протокол)",
    )
    is_multi_lot: bool = Field(
        default=False,
        description="Многолотовая закупка",
    )
    no_winner_declared: bool = Field(
        default=False,
        description="Победитель не определён",
    )
    procurement_cancelled: bool = Field(
        default=False,
        description="Закупка отменена",
    )
    single_participant: bool = Field(
        default=False,
        description="Единственный участник",
    )
    all_rejected: bool = Field(
        default=False,
        description="Все заявки отклонены",
    )
    insufficient_data: bool = Field(
        default=False,
        description="Недостаточно данных для извлечения",
    )
    customer_confused_with_winner: bool = Field(
        default=False,
        description="Возможно смешение заказчика с победителем",
    )


class DocumentInfo(BaseModel):
    """Information about the source document."""

    document_type: DocumentType = Field(
        default=DocumentType.UNKNOWN,
        description="Тип документа",
    )
    source_file: Optional[str] = Field(
        None,
        description="Имя исходного файла",
    )
    content_quality: str = Field(
        default="unknown",
        description="Качество контента: good, partial, poor, unknown",
    )
    has_tables: bool = Field(
        default=False,
        description="Документ содержит таблицы",
    )
    page_count: Optional[int] = Field(
        None,
        description="Количество страниц",
    )
