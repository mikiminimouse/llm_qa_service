# PRD: Q&A Service для Docling Pipeline

**Версия:** 3.0 Final  
**Дата:** 2026-01-20  
**Статус:** Согласовано  
**Основа:** Анализ реальных протоколов госзакупок

---

## 1. Обзор и цели

### 1.1 Назначение сервиса

Q&A Service — это **финальный этап** обработки документов после Docling pipeline. Сервис анализирует оцифрованные протоколы госзакупок с помощью LLM и извлекает структурированную информацию о победителях.

### 1.2 Цели (Goals)

| Цель | Описание |
|------|----------|
| **Извлечение данных** | Определить победителя/поставщика из протокола госзакупки |
| **Поддержка нескольких лотов** | Извлекать ВСЕХ победителей при многолотовых закупках |
| **Обработка edge cases** | Корректно обрабатывать "закупка не состоялась + победитель есть" |
| **Различение сущностей** | НЕ путать данные ЗАКАЗЧИКА/ЭТП с данными ПОБЕДИТЕЛЯ |
| **Анонимизированные данные** | Корректно обрабатывать "Заявка №XXXXX" вместо названия организации |
| **Фильтрация мусора** | Идентифицировать служебные файлы без полезной информации |
| **Структурированный вывод** | Валидированный через Pydantic результат в MongoDB |

### 1.3 Не-цели (Non-Goals)

| Не делаем | Почему |
|-----------|--------|
| OCR, parsing, layout | Это задача Docling (уже выполнена) |
| RAG / embeddings | Документы помещаются в контекст LLM целиком |
| Интерактивный чат | Только автоматическая обработка |
| GigaChat | Не требуется (нет сертификата НУЦ) |

---

## 2. Анализ реальных данных

### 2.1 Сводная таблица Edge Cases

На основе анализа реальных файлов протоколов выявлены следующие сценарии:

| Файл | Тип документа | Победитель | Статус закупки | Особенности |
|------|---------------|------------|----------------|-------------|
| `UNIT_01e84964...` | Протокол несостоявшейся | ❌ НЕТ | Несостоявшаяся | Нет заявок |
| `UNIT_020f8f07...` | Протокол рассмотрения | ✅ ЕСТЬ | Несостоявшаяся | Единственный участник = победитель |
| `UNIT_00231969...` | Протокол подведения итогов | ✅ ЕСТЬ | Состоявшаяся | Данные АНОНИМИЗИРОВАНЫ |
| `UNIT_027bf812...` | Протокол запроса цен | ✅ ЕСТЬ | Несостоявшаяся | Единственный участник, анонимизирован |
| `UNIT_2ca07cb8...` | Расчёт баллов (Excel) | ⚠️ Служебный | N/A | Проблемы с кодировкой |

### 2.2 Критический Edge Case: "Несостоявшаяся" ≠ "Нет победителя"

**ВАЖНО:** Фраза "закупка признана несостоявшейся" НЕ означает отсутствие победителя!

| Причина несостоявшейся | Есть ли победитель? | Пример |
|------------------------|---------------------|--------|
| "Не подано ни одной заявки" | ❌ НЕТ | UNIT_01e84964 |
| "Подана только одна заявка" | ✅ ЕСТЬ | UNIT_020f8f07 |
| "Остальные отклонены" | ✅ ЕСТЬ | — |

### 2.3 Сравнение форматов контекста

| Формат | Читаемость LLM | Размер (токены) | Таблицы | Рекомендация |
|--------|----------------|-----------------|---------|--------------|
| **Markdown** | ⭐⭐⭐ Отличная | ⭐⭐⭐ Компактный | ⭐⭐ Хорошо | ✅ **Основной** |
| **HTML** | ⭐⭐ Хорошая | ⭐⭐ Средний | ⭐⭐⭐ Отлично | Для сложных таблиц |
| **JSON** | ⭐ Плохая | ⭐ Много | ⭐⭐⭐ Структурировано | ❌ Не использовать |

**Вывод:** Использовать **Markdown** как основной формат. JSON Docling содержит слишком много служебной информации (bbox, row_span, etc.) и тратит токены впустую.

---

## 3. Архитектура

### 3.1 Высокоуровневая схема

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        ВНЕШНИЙ ВЫЗОВ                                    │
│                                                                         │
│  POST /api/v1/qa/process                                               │
│  { "protocol_id": "..." }                                              │
│                                                                         │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Q&A SERVICE (FastAPI)                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      QA ORCHESTRATOR                             │   │
│  │                                                                  │   │
│  │  1. Загрузка контекста ─────────────▶ MongoContextLoader        │   │
│  │     (markdown_content из protocols)                             │   │
│  │                                                                  │   │
│  │  2. Загрузка промптов ──────────────▶ PromptManager             │   │
│  │     • system/winner_extractor_v2.txt                            │   │
│  │     • user/extract_winner_v2.txt                                │   │
│  │                                                                  │   │
│  │  3. Формирование запроса ───────────▶ { system + user + context }│  │
│  │                                                                  │   │
│  │  4. Вызов LLM ──────────────────────▶ GLM47Client               │   │
│  │                                       api.z.ai/api/paas/v4/     │   │
│  │                                                                  │   │
│  │  5. Парсинг ответа ─────────────────▶ JSON → Pydantic           │   │
│  │                                                                  │   │
│  │  6. Валидация ──────────────────────▶ WinnerExtractionResultV2  │   │
│  │     + проверка на смешивание с заказчиком                       │   │
│  │                                                                  │   │
│  │  7. Сохранение ─────────────────────▶ MongoQARepository         │   │
│  │     (ПЕРЕЗАПИСЬ предыдущего результата)                         │   │
│  │                                                                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           MONGODB                                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────┐      ┌─────────────────────────────────────┐  │
│  │ protocols           │      │ qa_results                          │  │
│  │ (от Docling)        │      │ (от Q&A Service)                    │  │
│  │                     │      │                                     │  │
│  │ _id: ObjectId       │◄────▶│ protocol_id: ObjectId (FK)          │  │
│  │ markdown_content    │      │ extraction_result: {...}            │  │
│  │ source_file         │      │ llm_metadata: {...}                 │  │
│  └─────────────────────┘      └─────────────────────────────────────┘  │
│                                                                         │
│  ⚠️ Связь 1:1 — на каждый протокол ОДИН актуальный QA результат       │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Правила различения сущностей

```
┌─────────────────────────────────────────────────────────────┐
│  СТРУКТУРА ПРОТОКОЛА                                        │
├─────────────────────────────────────────────────────────────┤
│  ЗАГОЛОВОК                                                  │
│  "ПРОТОКОЛ ПОДВЕДЕНИЯ ИТОГОВ"                              │
├─────────────────────────────────────────────────────────────┤
│  I. ОБЩИЕ ПОЛОЖЕНИЯ                                         │
│  ├─ Сведения об организаторе → ЗАКАЗЧИК (НЕ брать ИНН!)    │
│  ├─ Сведения о заказчике → ЗАКАЗЧИК (НЕ брать ИНН!)        │
│  ├─ Сведения об операторе ЭТП → ОПЕРАТОР (НЕ брать!)       │
│  └─ Наименование закупки, НМЦ                               │
├─────────────────────────────────────────────────────────────┤
│  II. РЕЗУЛЬТАТЫ ПОДВЕДЕНИЯ ИТОГОВ                           │
│  ├─ Таблица присвоения номеров → УЧАСТНИКИ                  │
│  ├─ Таблица победителей → ПОБЕДИТЕЛЬ (ИЗВЛЕКАТЬ!)          │
│  └─ Признание несостоявшейся → Статус                      │
├─────────────────────────────────────────────────────────────┤
│  СОСТАВ КОМИССИИ                                            │
│  └─ Члены комиссии → НЕ БРАТЬ                              │
└─────────────────────────────────────────────────────────────┘
```

**Маркеры ЗАКАЗЧИКА (НЕ извлекать!):**
- "Сведения об организаторе:"
- "Сведения о заказчике:"
- "Организатор закупки:"
- Обычно это бюджетные учреждения (МАДОУ, ГАУ, ОГБПОУ и т.д.)

**Маркеры ОПЕРАТОРА ЭТП (НЕ извлекать!):**
- "Сведения об операторе электронной площадки:"
- ООО «ТОРГИ-ОНЛАЙН», Сбербанк-АСТ, РТС-тендер

**Маркеры ПОБЕДИТЕЛЯ (ИЗВЛЕКАТЬ):**
- "Победитель"
- "первый порядковый номер (победитель)"
- "Результат: Победитель"
- Таблица "Сведения об участниках закупки, которым присвоены..."

---

## 4. Структура проекта

```
qa_service/
│
├── main.py                          # FastAPI entrypoint
├── requirements.txt
├── .env.example
│
├── config/
│   ├── __init__.py
│   └── settings.py                  # Pydantic Settings
│
├── prompts/                         # ВСЕ ПРОМПТЫ ЗДЕСЬ
│   ├── system/
│   │   └── winner_extractor_v2.txt  # System prompt v2.0
│   │
│   ├── user/
│   │   └── extract_winner_v2.txt    # User prompt template v2.0
│   │
│   └── validation/
│       └── rules_v2.yaml            # Правила валидации v2.0
│
├── domain/
│   ├── __init__.py
│   ├── entities/
│   │   ├── __init__.py
│   │   ├── winner.py                # WinnerInfo, OtherParticipant
│   │   ├── extraction_result.py     # WinnerExtractionResultV2
│   │   └── qa_record.py             # QARecord для MongoDB
│   │
│   └── interfaces/
│       ├── __init__.py
│       ├── llm_client.py            # ILLMClient ABC
│       ├── context_loader.py        # IContextLoader ABC
│       └── qa_repository.py         # IQARepository ABC
│
├── infrastructure/
│   ├── __init__.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── glm47_client.py          # GLM-4.7 implementation
│   │   └── factory.py               # LLMClientFactory
│   │
│   ├── loaders/
│   │   ├── __init__.py
│   │   ├── mongo_loader.py          # MongoContextLoader (основной)
│   │   └── file_loader.py           # FileContextLoader (для тестов)
│   │
│   ├── repositories/
│   │   ├── __init__.py
│   │   └── mongo_qa_repository.py   # MongoDB repository
│   │
│   └── prompt_manager.py            # Загрузка промптов из файлов
│
├── application/
│   ├── __init__.py
│   ├── orchestrator.py              # QAOrchestrator
│   ├── response_parser.py           # Парсинг JSON из ответа LLM
│   └── validators/
│       ├── __init__.py
│       └── result_validator.py      # Валидация + проверка на заказчика
│
└── api/
    ├── __init__.py
    ├── routes.py                    # REST API endpoints
    ├── schemas.py                   # Request/Response Pydantic models
    └── dependencies.py              # FastAPI dependencies
```

---

## 5. Domain Entities (Pydantic Models v2.0)

### 5.1 Enums

```python
# domain/entities/enums.py
from enum import Enum

class ParticipantStatus(str, Enum):
    """Статус участника закупки"""
    WINNER = "winner"                        # Победитель
    SINGLE_PARTICIPANT = "single_participant" # Единственный участник (стал победителем)
    ADMITTED = "admitted"                    # Допущен к участию
    REJECTED = "rejected"                    # Отклонён
    NOT_FOUND = "not_found"                  # Не найден в документе


class ProcurementStatus(str, Enum):
    """Статус закупки"""
    COMPLETED = "completed"      # Закупка состоялась, есть победитель
    NOT_HELD = "not_held"        # Не состоялась (но победитель МОЖЕТ быть!)
    CANCELLED = "cancelled"      # Отменена
    UNKNOWN = "unknown"          # Не удалось определить


class NotHeldReason(str, Enum):
    """Причина, почему закупка не состоялась"""
    SINGLE_PARTICIPANT = "single_participant"  # Единственный участник → ЕСТЬ победитель
    NO_APPLICATIONS = "no_applications"        # Нет заявок → НЕТ победителя
    ALL_REJECTED = "all_rejected"              # Все отклонены → НЕТ победителя


class DocumentType(str, Enum):
    """Тип документа"""
    FINAL_PROTOCOL = "итоговый_протокол"
    REVIEW_PROTOCOL = "протокол_рассмотрения"
    PRICE_REQUEST_PROTOCOL = "протокол_запроса_цен"
    TECHNICAL_SPEC = "техзадание"
    SCORING_CALCULATION = "расчет_баллов"
    OTHER = "иное"
```

### 5.2 Winner Info (с поддержкой нескольких лотов)

```python
# domain/entities/winner.py
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal
from .enums import ParticipantStatus


class WinnerInfo(BaseModel):
    """
    Информация о победителе одного лота.
    
    Поддерживает как полные данные организации,
    так и анонимизированные (только номер заявки).
    """
    
    # Идентификация лота (для многолотовых закупок)
    lot_number: int = Field(1, description="Номер лота")
    lot_name: Optional[str] = Field(None, description="Наименование лота")
    
    # Основные данные победителя
    name: str = Field(..., description="Наименование организации или номер заявки")
    inn: Optional[str] = Field(None, description="ИНН победителя")
    kpp: Optional[str] = Field(None, description="КПП победителя")
    ogrn: Optional[str] = Field(None, description="ОГРН победителя")
    address: Optional[str] = Field(None, description="Адрес победителя")
    
    # Данные о предложении
    contract_price: Optional[str] = Field(None, description="Цена контракта")
    application_number: Optional[str] = Field(None, description="Номер заявки")
    rank: int = Field(1, description="Место в рейтинге")
    
    # Статус и флаги
    status: ParticipantStatus = Field(..., description="Статус участника")
    data_anonymized: bool = Field(False, description="Данные анонимизированы (только номер заявки)")
    
    # Подтверждение из документа
    source_quote: Optional[str] = Field(None, description="Цитата из документа (до 200 символов)")
    
    @field_validator('inn')
    @classmethod
    def validate_inn(cls, v):
        """Валидация ИНН: 10 или 12 цифр"""
        if v is not None and v != "":
            v = v.replace(" ", "").replace("-", "")
            if not v.isdigit() or len(v) not in (10, 12):
                return None  # Невалидный ИНН — игнорируем
        return v
    
    @field_validator('kpp')
    @classmethod
    def validate_kpp(cls, v):
        """Валидация КПП: 9 цифр"""
        if v is not None and v != "":
            v = v.replace(" ", "")
            if not v.isdigit() or len(v) != 9:
                return None
        return v
    
    @field_validator('ogrn')
    @classmethod
    def validate_ogrn(cls, v):
        """Валидация ОГРН: 13 или 15 цифр"""
        if v is not None and v != "":
            v = v.replace(" ", "")
            if not v.isdigit() or len(v) not in (13, 15):
                return None
        return v


class OtherParticipant(BaseModel):
    """Информация о другом участнике закупки (не победитель)"""
    name: str
    inn: Optional[str] = None
    rank: Optional[int] = None
    price: Optional[str] = None
    status: Literal["admitted", "rejected"] = "admitted"
    rejection_reason: Optional[str] = None
```

### 5.3 Вложенные модели

```python
# domain/entities/extraction_components.py
from pydantic import BaseModel, Field
from typing import Optional
from .enums import ProcurementStatus, NotHeldReason, DocumentType


class ProcurementInfo(BaseModel):
    """Информация о закупке"""
    number: Optional[str] = Field(None, description="Номер закупки / реестровый номер")
    name: Optional[str] = Field(None, description="Наименование закупки")
    initial_price: Optional[str] = Field(None, description="Начальная (максимальная) цена")
    status: ProcurementStatus = Field(..., description="Статус закупки")
    not_held_reason: Optional[NotHeldReason] = Field(None, description="Причина несостоявшейся")


class ExtractionFlags(BaseModel):
    """Флаги особых случаев"""
    is_single_participant_winner: bool = Field(
        False, 
        description="Победитель = единственный участник"
    )
    procurement_not_held_but_winner_exists: bool = Field(
        False,
        description="Закупка не состоялась, но победитель определён"
    )
    data_anonymized: bool = Field(
        False, 
        description="Данные победителя анонимизированы"
    )
    multiple_lots: bool = Field(
        False, 
        description="В закупке несколько лотов"
    )


class DocumentInfo(BaseModel):
    """Информация о документе"""
    type: DocumentType = Field(..., description="Тип документа")
    is_service_file: bool = Field(False, description="Служебный файл без победителя")
    no_useful_content: bool = Field(False, description="Нет полезной информации")
    has_encoding_issues: bool = Field(False, description="Проблемы с кодировкой")
```

### 5.4 Главная модель результата

```python
# domain/entities/extraction_result.py
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List
from datetime import datetime

from .winner import WinnerInfo, OtherParticipant
from .extraction_components import ProcurementInfo, ExtractionFlags, DocumentInfo


class WinnerExtractionResultV2(BaseModel):
    """
    Структурированный результат извлечения информации о победителях.
    
    Версия 2.0:
    - Поддержка нескольких лотов (winners: List)
    - Флаги особых случаев
    - Информация о документе
    - Улучшенная валидация
    """
    
    # === Основной результат ===
    winner_found: bool = Field(..., description="Найден ли хотя бы один победитель")
    winners: List[WinnerInfo] = Field(
        default_factory=list, 
        description="Список победителей (один или несколько при многолотовой закупке)"
    )
    
    # === Информация о закупке ===
    procurement_info: ProcurementInfo
    
    # === Другие участники ===
    other_participants: List[OtherParticipant] = Field(default_factory=list)
    total_participants_count: int = Field(0, description="Общее число участников")
    
    # === Флаги особых случаев ===
    flags: ExtractionFlags = Field(default_factory=ExtractionFlags)
    
    # === Информация о документе ===
    document_info: DocumentInfo
    
    # === Объяснение логики ===
    reasoning: str = Field(..., description="Объяснение, как был определён победитель")
    
    # === Валидаторы ===
    
    @model_validator(mode='after')
    def validate_winners_consistency(self):
        """Проверка консистентности winner_found и winners"""
        if self.winner_found and len(self.winners) == 0:
            raise ValueError('winners list cannot be empty when winner_found is True')
        if not self.winner_found and len(self.winners) > 0:
            raise ValueError('winners list must be empty when winner_found is False')
        return self
    
    @model_validator(mode='after')
    def set_flags_automatically(self):
        """Автоматическая установка флагов на основе данных"""
        # Проверка на анонимизированные данные
        if self.winners:
            if any(w.data_anonymized for w in self.winners):
                self.flags.data_anonymized = True
        
        # Проверка на несколько лотов
        if len(self.winners) > 1:
            lot_numbers = {w.lot_number for w in self.winners}
            if len(lot_numbers) > 1:
                self.flags.multiple_lots = True
        
        return self


class QARecord(BaseModel):
    """
    Запись Q&A результата для MongoDB.
    Связывается с протоколом через protocol_id.
    """
    protocol_id: str = Field(..., description="ID протокола в MongoDB")
    
    # Результат извлечения
    extraction_result: WinnerExtractionResultV2
    
    # Метаданные LLM
    llm_provider: str = Field(..., description="Провайдер LLM")
    llm_model: str = Field(..., description="Модель LLM")
    prompt_tokens: int = Field(0, description="Токены в промпте")
    completion_tokens: int = Field(0, description="Токены в ответе")
    latency_ms: float = Field(0, description="Время ответа LLM в мс")
    
    # Метаданные контекста
    context_format: str = Field(..., description="markdown | html")
    context_length: int = Field(0, description="Длина контекста в символах")
    
    # Timestamps
    processed_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
```

---

## 6. Промпты (версия 2.0)

### 6.1 System Prompt

```text
# prompts/system/winner_extractor_v2.txt

Ты — эксперт по анализу документов государственных закупок России (44-ФЗ, 223-ФЗ).

## ТВОЯ ЗАДАЧА

Проанализировать протокол закупки и извлечь информацию о ПОБЕДИТЕЛЕ (поставщике).

## КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА

### 1. ЗАКУПКА НЕ СОСТОЯЛАСЬ ≠ НЕТ ПОБЕДИТЕЛЯ

Фраза "закупка признана несостоявшейся" НЕ означает отсутствие победителя!

| Причина несостоявшейся | Есть ли победитель? |
|------------------------|---------------------|
| "Не подано ни одной заявки" | ❌ НЕТ победителя |
| "Подана только одна заявка" | ✅ ЕСТЬ победитель (единственный участник) |
| "Остальные отклонены" | ✅ ЕСТЬ победитель (оставшийся участник) |

### 2. РАЗЛИЧАЙ СУЩНОСТИ — НЕ ПУТАЙ ЗАКАЗЧИКА И ПОБЕДИТЕЛЯ!

**ЗАКАЗЧИК (НЕ извлекать ИНН/КПП/ОГРН!):**
- Указан в разделах "Сведения об организаторе", "Сведения о заказчике"
- Обычно это бюджетное учреждение (МАДОУ, ГАУ, ОГБПОУ и т.д.)
- Его реквизиты указаны В НАЧАЛЕ документа

**ОПЕРАТОР ЭТП (НЕ извлекать!):**
- "Сведения об операторе электронной площадки"
- ООО «ТОРГИ-ОНЛАЙН», Сбербанк-АСТ, РТС-тендер и т.д.

**ПОБЕДИТЕЛЬ (ИЗВЛЕКАТЬ!):**
- Указан в таблицах с РЕЗУЛЬТАТАМИ (в конце документа)
- Маркеры: "Победитель", "первый порядковый номер", "Результат: Победитель"
- Это коммерческая организация (ООО, ИП, АО) или физлицо

### 3. АНОНИМИЗИРОВАННЫЕ ДАННЫЕ

Если вместо названия организации указано "Заявка №XXXXX, -":
- Установи `data_anonymized: true`
- В `name` укажи номер заявки: "Заявка №31666"
- Извлеки цену, если она указана

### 4. НЕСКОЛЬКО ЛОТОВ

Если в закупке несколько лотов — извлеки ВСЕХ победителей по каждому лоту.
Каждый победитель — отдельный элемент в массиве `winners`.

### 5. СЛУЖЕБНЫЕ ФАЙЛЫ

Если документ НЕ содержит информации о победителе:
- Техническое задание
- Проект контракта
- Расчёт баллов (без итогов)
- Извещение о закупке

Установи `is_service_file: true` и `winner_found: false`.

### 6. ИЗВЛЕКАЙ ВСЮ ЮР. ИНФОРМАЦИЮ ПОБЕДИТЕЛЯ

Если данные не анонимизированы, извлеки ВСЕ доступные реквизиты:
- Полное наименование организации
- ИНН (10 или 12 цифр)
- КПП (9 цифр)
- ОГРН (13 или 15 цифр)
- Адрес
- Цену контракта / предложение о цене
- Номер заявки

## ФОРМАТ ОТВЕТА

Верни ТОЛЬКО валидный JSON без markdown-форматирования (без ```json).
```

### 6.2 User Prompt Template

```text
# prompts/user/extract_winner_v2.txt

<document>
$document_content
</document>

## ЗАДАЧА

Проанализируй протокол выше и извлеки информацию о победителе(ях) закупки.

## ФОРМАТ ОТВЕТА

{
    "winner_found": true | false,
    
    "winners": [
        {
            "lot_number": 1,
            "lot_name": "Наименование лота или null",
            "name": "Полное наименование организации-победителя",
            "inn": "ИНН (10 или 12 цифр) или null",
            "kpp": "КПП (9 цифр) или null",
            "ogrn": "ОГРН (13 или 15 цифр) или null",
            "address": "Адрес или null",
            "contract_price": "Цена с единицей измерения (например: 245 890.00 руб.)",
            "application_number": "Номер заявки или null",
            "rank": 1,
            "status": "winner | single_participant",
            "data_anonymized": false,
            "source_quote": "Цитата из документа до 200 символов"
        }
    ],
    
    "procurement_info": {
        "number": "Номер закупки / реестровый номер ЕИС",
        "name": "Наименование закупки",
        "initial_price": "Начальная (максимальная) цена",
        "status": "completed | not_held | cancelled | unknown",
        "not_held_reason": "single_participant | no_applications | all_rejected | null"
    },
    
    "other_participants": [
        {
            "name": "Наименование участника",
            "inn": "ИНН или null",
            "rank": 2,
            "price": "Ценовое предложение",
            "status": "admitted | rejected",
            "rejection_reason": "Причина отклонения или null"
        }
    ],
    
    "total_participants_count": 0,
    
    "flags": {
        "is_single_participant_winner": false,
        "procurement_not_held_but_winner_exists": false,
        "data_anonymized": false,
        "multiple_lots": false
    },
    
    "document_info": {
        "type": "итоговый_протокол | протокол_рассмотрения | протокол_запроса_цен | техзадание | расчет_баллов | иное",
        "is_service_file": false,
        "no_useful_content": false,
        "has_encoding_issues": false
    },
    
    "reasoning": "Подробное объяснение, как был определён победитель"
}

## ПРАВИЛА ЗАПОЛНЕНИЯ

1. Если `winner_found: false` — массив `winners` ДОЛЖЕН быть пустым `[]`

2. Если данные победителя анонимизированы (только "Заявка №XXXXX"):
   - `name`: "Заявка №31666"
   - `data_anonymized`: true

3. Если несколько лотов — добавь победителя по каждому лоту в массив `winners`

4. Если закупка "не состоялась" из-за единственного участника:
   - `winner_found`: true (!)
   - `procurement_info.status`: "not_held"
   - `procurement_info.not_held_reason`: "single_participant"
   - `flags.procurement_not_held_but_winner_exists`: true

5. Цену ВСЕГДА указывай с единицей измерения: "245 890.00 руб."

6. В `source_quote` приведи ТОЧНУЮ цитату из документа (до 200 символов)

## КРИТИЧЕСКИ ВАЖНО

- НЕ извлекай ИНН/КПП/ОГРН ЗАКАЗЧИКА вместо данных ПОБЕДИТЕЛЯ!
- Заказчик указан в начале документа в разделе "Сведения об организаторе/заказчике"
- Победитель указан в РЕЗУЛЬТАТАХ (таблицы в конце документа)

Верни ТОЛЬКО JSON, без дополнительного текста и без ```json.
```

### 6.3 Validation Rules

```yaml
# prompts/validation/rules_v2.yaml

# === Минимальные требования ===
min_answer_length: 50

# === Обязательные поля ===
required_fields:
  - winner_found
  - winners
  - procurement_info.status
  - document_info.type
  - reasoning

# === Паттерны отсутствия победителя ===
no_winner_patterns:
  - "не подано ни одной заявки"
  - "заявки не поступили"
  - "закупка отменена"
  - "отсутствуют участники"

# === Паттерны НАЛИЧИЯ победителя при несостоявшейся закупке ===
winner_despite_not_held_patterns:
  - "подана только одна заявка"
  - "единственный участник"
  - "допущен и признан участником закупки единственный участник"
  - "остальные участники отклонены"

# === Маркеры победителя (ИЗВЛЕКАТЬ) ===
winner_markers:
  - "Победитель"
  - "первый порядковый номер"
  - "присвоен первый порядковый номер"
  - "Результат: Победитель"
  - "признан победителем"

# === Маркеры заказчика (НЕ извлекать ИНН!) ===
customer_markers:
  - "Сведения об организаторе"
  - "Сведения о заказчике"
  - "Организатор закупки"
  - "Организатором процедуры является"
  - "Контактная информация заказчика"

# === Маркеры оператора ЭТП (НЕ извлекать) ===
operator_markers:
  - "Сведения об операторе электронной площадки"
  - "Техническая поддержка"
  - "ТОРГИ-ОНЛАЙН"
  - "Сбербанк-АСТ"
  - "РТС-тендер"

# === Маркеры служебных файлов ===
service_file_patterns:
  - "Техническое задание"
  - "Проект контракта"
  - "Расчёт баллов"
  - "Извещение о закупке"
  - "Форма заявки"

# === Маркеры анонимизированных данных ===
anonymized_patterns:
  - "Заявка №\\d+, -"
  - "Заявка №\\d+$"
  - "участник №\\d+"

# === Проверки качества ===
quality_checks:
  winner_not_customer: true          # Победитель ≠ Заказчик
  winner_required_if_found: true     # Если found=true, должен быть winner
  inn_format: "^\\d{10}$|^\\d{12}$"  # ИНН: 10 или 12 цифр
  kpp_format: "^\\d{9}$"             # КПП: 9 цифр
  ogrn_format: "^\\d{13}$|^\\d{15}$" # ОГРН: 13 или 15 цифр

# === Лимиты ===
limits:
  max_reasoning_length: 1000
  max_source_quote_length: 200
  max_winners_per_document: 50

# === Маркеры галлюцинаций (снижают confidence) ===
hallucination_markers:
  - "по моему мнению"
  - "вероятно"
  - "скорее всего"
  - "предположительно"
  - "возможно"
```

---

## 7. Infrastructure Components

### 7.1 LLM Client (GLM-4.7)

```python
# infrastructure/llm/glm47_client.py
from typing import Dict, Any
from domain.interfaces.llm_client import ILLMClient
import httpx
import time
import logging

logger = logging.getLogger(__name__)


class GLM47Client(ILLMClient):
    """
    Клиент для GLM-4.7 (Z.ai)
    
    API совместим с OpenAI, поэтому используем стандартный формат.
    """
    
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.z.ai/api/paas/v4",
        model: str = "glm-4.7",
        timeout: float = 120.0,
        max_retries: int = 3
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self._model = model
        self.timeout = timeout
        self.max_retries = max_retries
        
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
        )
    
    @property
    def provider_name(self) -> str:
        return "glm47"
    
    @property
    def model_name(self) -> str:
        return self._model
    
    async def ask(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        Отправить запрос к GLM-4.7
        
        Returns:
            {
                "answer": str,
                "prompt_tokens": int,
                "completion_tokens": int,
                "latency_ms": float
            }
        """
        url = f"{self.base_url}/chat/completions"
        
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        start_time = time.time()
        
        for attempt in range(self.max_retries):
            try:
                response = await self._client.post(url, json=payload)
                response.raise_for_status()
                
                data = response.json()
                latency_ms = (time.time() - start_time) * 1000
                
                return {
                    "answer": data["choices"][0]["message"]["content"],
                    "prompt_tokens": data.get("usage", {}).get("prompt_tokens", 0),
                    "completion_tokens": data.get("usage", {}).get("completion_tokens", 0),
                    "latency_ms": latency_ms
                }
                
            except httpx.HTTPStatusError as e:
                logger.warning(f"HTTP error (attempt {attempt + 1}): {e}")
                if attempt == self.max_retries - 1:
                    raise
                    
            except httpx.TimeoutException:
                logger.warning(f"Timeout (attempt {attempt + 1})")
                if attempt == self.max_retries - 1:
                    raise
    
    async def health_check(self) -> bool:
        """Проверка доступности API"""
        try:
            await self.ask(system_prompt="", user_prompt="ping", max_tokens=5)
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
    
    async def close(self):
        """Закрыть HTTP клиент"""
        await self._client.aclose()
```

### 7.2 Context Loader (MongoDB)

```python
# infrastructure/loaders/mongo_loader.py
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from domain.interfaces.context_loader import IContextLoader
from typing import Optional
import hashlib
import logging

logger = logging.getLogger(__name__)


class DocumentContext:
    """Контекст документа для Q&A"""
    def __init__(
        self,
        protocol_id: str,
        content: str,
        content_format: str,
        content_hash: str,
        source_file: Optional[str] = None
    ):
        self.protocol_id = protocol_id
        self.content = content
        self.content_format = content_format
        self.content_hash = content_hash
        self.source_file = source_file


class MongoContextLoader(IContextLoader):
    """
    Загрузчик контекста из MongoDB.
    
    Читает документы из коллекции protocols (от Docling).
    Использует markdown_content как основной источник.
    """
    
    def __init__(
        self,
        mongo_uri: str,
        database: str,
        collection: str = "protocols",
        content_field: str = "markdown_content",
        content_format: str = "markdown"
    ):
        self.client = AsyncIOMotorClient(mongo_uri)
        self.db: AsyncIOMotorDatabase = self.client[database]
        self.collection = self.db[collection]
        self.content_field = content_field
        self.content_format = content_format
    
    def get_source_type(self) -> str:
        return "mongodb"
    
    async def load(self, protocol_id: str) -> DocumentContext:
        """
        Загрузить контекст документа из MongoDB.
        
        Args:
            protocol_id: _id документа в коллекции protocols
            
        Returns:
            DocumentContext с содержимым документа
            
        Raises:
            ValueError: если документ не найден
        """
        from bson import ObjectId
        
        # Поддержка как строки, так и ObjectId
        query_id = ObjectId(protocol_id) if ObjectId.is_valid(protocol_id) else protocol_id
        
        doc = await self.collection.find_one({"_id": query_id})
        
        if not doc:
            raise ValueError(f"Protocol not found: {protocol_id}")
        
        # Получаем контент (приоритет: markdown → html → text)
        content = doc.get(self.content_field, "")
        current_format = self.content_format
        
        if not content:
            # Fallback на html_content (для сложных таблиц)
            content = doc.get("html_content", "")
            if content:
                current_format = "html"
            else:
                # Fallback на text_content
                content = doc.get("text_content", "")
                current_format = "text"
        
        if not content:
            logger.warning(f"Empty content for protocol {protocol_id}")
        
        content_hash = hashlib.md5(content.encode()).hexdigest()
        
        return DocumentContext(
            protocol_id=str(doc["_id"]),
            content=content,
            content_format=current_format,
            content_hash=content_hash,
            source_file=doc.get("source_file")
        )
    
    async def check_connection(self) -> bool:
        """Проверить подключение к MongoDB"""
        try:
            await self.client.admin.command('ping')
            return True
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")
            return False
```

### 7.3 QA Repository (MongoDB)

```python
# infrastructure/repositories/mongo_qa_repository.py
from motor.motor_asyncio import AsyncIOMotorClient
from domain.interfaces.qa_repository import IQARepository
from domain.entities.extraction_result import QARecord
from typing import Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class MongoQARepository(IQARepository):
    """
    MongoDB репозиторий для Q&A результатов.
    
    ВАЖНО: Использует стратегию ПЕРЕЗАПИСИ.
    На каждый protocol_id хранится только один (последний) результат.
    """
    
    def __init__(
        self,
        mongo_uri: str,
        database: str,
        collection: str = "qa_results"
    ):
        self.client = AsyncIOMotorClient(mongo_uri)
        self.db = self.client[database]
        self.collection = self.db[collection]
    
    async def save(self, record: QARecord) -> str:
        """
        Сохранить или перезаписать результат Q&A.
        
        Использует upsert по protocol_id.
        """
        doc = record.model_dump(mode='json')
        
        result = await self.collection.replace_one(
            {"protocol_id": record.protocol_id},
            doc,
            upsert=True
        )
        
        if result.upserted_id:
            logger.info(f"Created new QA result for protocol {record.protocol_id}")
        else:
            logger.info(f"Updated QA result for protocol {record.protocol_id}")
        
        return record.protocol_id
    
    async def get_by_protocol(self, protocol_id: str) -> Optional[QARecord]:
        """Получить результат Q&A по ID протокола"""
        doc = await self.collection.find_one({"protocol_id": protocol_id})
        
        if doc:
            doc.pop('_id', None)
            return QARecord(**doc)
        
        return None
    
    async def exists(self, protocol_id: str) -> bool:
        """Проверить, есть ли результат для протокола"""
        count = await self.collection.count_documents(
            {"protocol_id": protocol_id},
            limit=1
        )
        return count > 0
    
    async def delete(self, protocol_id: str) -> bool:
        """Удалить результат Q&A"""
        result = await self.collection.delete_one({"protocol_id": protocol_id})
        return result.deleted_count > 0
    
    async def get_stats(self) -> dict:
        """Получить статистику по результатам"""
        pipeline = [
            {
                "$group": {
                    "_id": "$extraction_result.winner_found",
                    "count": {"$sum": 1}
                }
            }
        ]
        
        cursor = self.collection.aggregate(pipeline)
        stats = {"total": 0, "with_winner": 0, "without_winner": 0}
        
        async for doc in cursor:
            if doc["_id"] is True:
                stats["with_winner"] = doc["count"]
            else:
                stats["without_winner"] = doc["count"]
            stats["total"] += doc["count"]
        
        return stats
    
    async def get_by_flags(
        self, 
        is_service_file: Optional[bool] = None,
        data_anonymized: Optional[bool] = None,
        limit: int = 100
    ) -> List[QARecord]:
        """Получить результаты по флагам"""
        query = {}
        
        if is_service_file is not None:
            query["extraction_result.document_info.is_service_file"] = is_service_file
        
        if data_anonymized is not None:
            query["extraction_result.flags.data_anonymized"] = data_anonymized
        
        cursor = self.collection.find(query).limit(limit)
        
        results = []
        async for doc in cursor:
            doc.pop('_id', None)
            results.append(QARecord(**doc))
        
        return results
```

---

## 8. Application Layer

### 8.1 Response Parser

```python
# application/response_parser.py
import json
import re
from typing import Optional
from domain.entities.extraction_result import WinnerExtractionResultV2
from pydantic import ValidationError
import logging

logger = logging.getLogger(__name__)


class ResponseParser:
    """
    Парсер ответов LLM.
    
    Извлекает JSON из ответа модели и валидирует через Pydantic.
    """
    
    @staticmethod
    def extract_json(text: str) -> Optional[str]:
        """
        Извлечь JSON из текста ответа LLM.
        
        LLM может вернуть:
        - Чистый JSON
        - JSON в markdown блоке ```json ... ```
        - JSON с текстом до/после
        """
        # Убираем markdown блоки
        json_block_pattern = r'```(?:json)?\s*([\s\S]*?)```'
        matches = re.findall(json_block_pattern, text)
        
        if matches:
            text = matches[0]
        
        # Ищем от первой { до последней }
        start = text.find('{')
        end = text.rfind('}')
        
        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]
        
        return None
    
    @staticmethod
    def parse(llm_response: str) -> WinnerExtractionResultV2:
        """
        Распарсить ответ LLM в WinnerExtractionResultV2.
        
        Args:
            llm_response: Сырой ответ от LLM
            
        Returns:
            WinnerExtractionResultV2
            
        Raises:
            ValueError: если не удалось распарсить JSON
            ValidationError: если JSON не соответствует схеме
        """
        json_str = ResponseParser.extract_json(llm_response)
        
        if not json_str:
            logger.error(f"No JSON found in response: {llm_response[:200]}...")
            raise ValueError("No valid JSON found in LLM response")
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            raise ValueError(f"Invalid JSON: {e}")
        
        # Валидация через Pydantic
        try:
            result = WinnerExtractionResultV2(**data)
            return result
        except ValidationError as e:
            logger.error(f"Pydantic validation error: {e}")
            raise
```

### 8.2 QA Orchestrator

```python
# application/orchestrator.py
from typing import Optional, List
from domain.entities.extraction_result import QARecord, WinnerExtractionResultV2
from domain.interfaces.llm_client import ILLMClient
from domain.interfaces.context_loader import IContextLoader
from domain.interfaces.qa_repository import IQARepository
from infrastructure.prompt_manager import PromptManager
from application.response_parser import ResponseParser
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class QAOrchestrator:
    """
    Оркестратор Q&A процесса.
    
    Координирует:
    1. Загрузку контекста из MongoDB
    2. Загрузку промптов v2
    3. Вызов LLM
    4. Парсинг и валидацию ответа
    5. Сохранение результата (перезапись)
    """
    
    def __init__(
        self,
        llm_client: ILLMClient,
        context_loader: IContextLoader,
        repository: IQARepository,
        prompt_manager: PromptManager
    ):
        self.llm = llm_client
        self.loader = context_loader
        self.repository = repository
        self.prompts = prompt_manager
        self.parser = ResponseParser()
    
    async def process_protocol(
        self,
        protocol_id: str,
        system_prompt_name: str = "winner_extractor_v2",
        user_prompt_name: str = "extract_winner_v2",
        force_reprocess: bool = False
    ) -> QARecord:
        """
        Обработать протокол и извлечь информацию о победителе(ях).
        
        Args:
            protocol_id: ID протокола в MongoDB
            system_prompt_name: Имя system prompt файла
            user_prompt_name: Имя user prompt файла
            force_reprocess: Принудительно переобработать
            
        Returns:
            QARecord с результатом
        """
        # Проверяем кэш
        if not force_reprocess:
            existing = await self.repository.get_by_protocol(protocol_id)
            if existing:
                logger.info(f"Using cached result for {protocol_id}")
                return existing
        
        # 1. Загружаем контекст
        logger.info(f"Loading context for protocol {protocol_id}")
        context = await self.loader.load(protocol_id)
        
        # 2. Загружаем промпты
        system_prompt = self.prompts.get_system_prompt(system_prompt_name)
        user_prompt = self.prompts.get_user_prompt(
            user_prompt_name,
            document_content=context.content
        )
        
        # 3. Вызываем LLM
        logger.info(f"Calling LLM for protocol {protocol_id}")
        llm_response = await self.llm.ask(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.1  # Низкая температура для детерминизма
        )
        
        # 4. Парсим ответ
        logger.info(f"Parsing LLM response for protocol {protocol_id}")
        extraction_result = self.parser.parse(llm_response["answer"])
        
        # 5. Формируем запись
        record = QARecord(
            protocol_id=protocol_id,
            extraction_result=extraction_result,
            llm_provider=self.llm.provider_name,
            llm_model=self.llm.model_name,
            prompt_tokens=llm_response["prompt_tokens"],
            completion_tokens=llm_response["completion_tokens"],
            latency_ms=llm_response["latency_ms"],
            context_format=context.content_format,
            context_length=len(context.content),
            processed_at=datetime.utcnow()
        )
        
        # 6. Сохраняем (перезапись)
        await self.repository.save(record)
        
        # Логируем результат
        if extraction_result.winner_found:
            winners_names = [w.name for w in extraction_result.winners]
            logger.info(f"Protocol {protocol_id}: winners found - {winners_names}")
        else:
            logger.info(f"Protocol {protocol_id}: no winners found")
        
        return record
    
    async def process_batch(
        self,
        protocol_ids: List[str],
        skip_existing: bool = True
    ) -> dict:
        """
        Обработать несколько протоколов.
        
        Returns:
            {"processed": int, "skipped": int, "errors": int, "details": [...]}
        """
        stats = {
            "processed": 0, 
            "skipped": 0, 
            "errors": 0,
            "details": []
        }
        
        for protocol_id in protocol_ids:
            try:
                if skip_existing and await self.repository.exists(protocol_id):
                    stats["skipped"] += 1
                    stats["details"].append({
                        "protocol_id": protocol_id,
                        "status": "skipped"
                    })
                    continue
                
                record = await self.process_protocol(protocol_id, force_reprocess=True)
                stats["processed"] += 1
                stats["details"].append({
                    "protocol_id": protocol_id,
                    "status": "processed",
                    "winner_found": record.extraction_result.winner_found
                })
                
            except Exception as e:
                logger.error(f"Error processing {protocol_id}: {e}")
                stats["errors"] += 1
                stats["details"].append({
                    "protocol_id": protocol_id,
                    "status": "error",
                    "error": str(e)
                })
        
        return stats
```

---

## 9. REST API

### 9.1 API Schemas

```python
# api/schemas.py
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from domain.entities.extraction_result import WinnerExtractionResultV2


class ProcessProtocolRequest(BaseModel):
    """Запрос на обработку одного протокола"""
    protocol_id: str = Field(..., description="ID протокола в MongoDB")
    force_reprocess: bool = Field(False, description="Принудительно переобработать")


class ProcessBatchRequest(BaseModel):
    """Запрос на обработку нескольких протоколов"""
    protocol_ids: List[str] = Field(..., max_length=100)
    skip_existing: bool = Field(True, description="Пропускать уже обработанные")


class WinnerSummary(BaseModel):
    """Краткая информация о победителе для ответа API"""
    name: str
    inn: Optional[str] = None
    contract_price: Optional[str] = None
    lot_number: int = 1
    data_anonymized: bool = False


class ProcessProtocolResponse(BaseModel):
    """Ответ на запрос обработки"""
    success: bool
    protocol_id: str
    winner_found: bool = False
    winners: List[WinnerSummary] = []
    procurement_status: Optional[str] = None
    is_service_file: bool = False
    reasoning: Optional[str] = None
    latency_ms: float = 0
    error: Optional[str] = None


class ProcessBatchResponse(BaseModel):
    """Ответ на batch-обработку"""
    processed: int
    skipped: int
    errors: int
    details: List[dict] = []


class StatsResponse(BaseModel):
    """Статистика"""
    total: int
    with_winner: int
    without_winner: int


class HealthResponse(BaseModel):
    """Health check"""
    status: str
    mongodb: bool
    llm: bool
    version: str = "3.0.0"
```

### 9.2 API Endpoints

| Endpoint | Method | Описание |
|----------|--------|----------|
| `/api/v1/qa/process` | POST | Обработать один протокол |
| `/api/v1/qa/process/batch` | POST | Обработать несколько протоколов |
| `/api/v1/qa/result/{protocol_id}` | GET | Получить результат |
| `/api/v1/qa/stats` | GET | Статистика |
| `/api/v1/qa/health` | GET | Health check |

### 9.3 API Usage Example

```bash
# Обработать протокол
curl -X POST "http://localhost:8001/api/v1/qa/process" \
  -H "Content-Type: application/json" \
  -d '{"protocol_id": "679abc123def456789012345"}'

# Ответ (победитель найден)
{
    "success": true,
    "protocol_id": "679abc123def456789012345",
    "winner_found": true,
    "winners": [
        {
            "name": "ООО \"ИНТРЕЙД\"",
            "inn": null,
            "contract_price": "130 500,00 руб.",
            "lot_number": 1,
            "data_anonymized": false
        }
    ],
    "procurement_status": "not_held",
    "is_service_file": false,
    "reasoning": "Закупка признана несостоявшейся из-за единственной заявки, но участник ООО ИНТРЕЙД признан победителем",
    "latency_ms": 3250.5
}

# Ответ (анонимизированные данные)
{
    "success": true,
    "protocol_id": "679abc123def456789012346",
    "winner_found": true,
    "winners": [
        {
            "name": "Заявка №31666",
            "inn": null,
            "contract_price": "245 890.00 руб.",
            "lot_number": 1,
            "data_anonymized": true
        }
    ],
    "procurement_status": "completed",
    "reasoning": "Победитель определён по итогам закупки. Данные анонимизированы."
}

# Ответ (служебный файл)
{
    "success": true,
    "protocol_id": "679abc123def456789012347",
    "winner_found": false,
    "winners": [],
    "procurement_status": "unknown",
    "is_service_file": true,
    "reasoning": "Документ является служебным файлом расчёта баллов"
}
```

---

## 10. Конфигурация

### 10.1 Settings

```python
# config/settings.py
from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    """Настройки приложения"""
    
    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DATABASE: str = "docling_qa"
    MONGO_PROTOCOLS_COLLECTION: str = "protocols"
    MONGO_QA_COLLECTION: str = "qa_results"
    
    # GLM-4.7 (Z.ai)
    GLM_API_KEY: str
    GLM_BASE_URL: str = "https://api.z.ai/api/paas/v4"
    GLM_MODEL: str = "glm-4.7"
    GLM_TIMEOUT: float = 120.0
    
    # Context
    CONTEXT_FORMAT: Literal["markdown", "html"] = "markdown"
    CONTEXT_FIELD: str = "markdown_content"
    
    # Prompts
    PROMPTS_DIR: str = "./prompts"
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8001
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
```

### 10.2 .env.example

```env
# MongoDB
MONGO_URI=mongodb://localhost:27017
MONGO_DATABASE=docling_qa
MONGO_PROTOCOLS_COLLECTION=protocols
MONGO_QA_COLLECTION=qa_results

# GLM-4.7 (Z.ai)
GLM_API_KEY=your_api_key_here
GLM_BASE_URL=https://api.z.ai/api/paas/v4
GLM_MODEL=glm-4.7

# Context
CONTEXT_FORMAT=markdown
CONTEXT_FIELD=markdown_content

# Prompts
PROMPTS_DIR=./prompts

# Server
HOST=0.0.0.0
PORT=8001
```

---

## 11. MongoDB Schema

```javascript
// Коллекция: protocols (от Docling)
{
    "_id": ObjectId("..."),
    "source_file": "2025-12-12_32515494387_Протокол.docx",
    "markdown_content": "ПРОТОКОЛ ПОДВЕДЕНИЯ ИТОГОВ...",
    "html_content": "<html>...</html>",  // Опционально
    "json_content": {...},  // DoclingDocument
    "page_count": 3,
    "tables_count": 4,
    "created_at": ISODate("..."),
    "docling_version": "2.15.0"
}

// Коллекция: qa_results (от Q&A Service)
{
    "protocol_id": "679abc123...",
    
    "extraction_result": {
        "winner_found": true,
        "winners": [
            {
                "lot_number": 1,
                "lot_name": null,
                "name": "ООО \"ИНТРЕЙД\"",
                "inn": null,
                "kpp": null,
                "ogrn": null,
                "address": null,
                "contract_price": "130 500,00 руб.",
                "application_number": null,
                "rank": 1,
                "status": "single_participant",
                "data_anonymized": false,
                "source_quote": "Результат: Победитель - ООО ИНТРЕЙД"
            }
        ],
        "procurement_info": {
            "number": "32515512858",
            "name": "на поставку электрокардиографа",
            "initial_price": "130 500,00 руб.",
            "status": "not_held",
            "not_held_reason": "single_participant"
        },
        "other_participants": [],
        "total_participants_count": 1,
        "flags": {
            "is_single_participant_winner": true,
            "procurement_not_held_but_winner_exists": true,
            "data_anonymized": false,
            "multiple_lots": false
        },
        "document_info": {
            "type": "протокол_рассмотрения",
            "is_service_file": false,
            "no_useful_content": false,
            "has_encoding_issues": false
        },
        "reasoning": "Закупка признана несостоявшейся из-за единственной заявки..."
    },
    
    "llm_provider": "glm47",
    "llm_model": "glm-4.7",
    "prompt_tokens": 2500,
    "completion_tokens": 450,
    "latency_ms": 3200.5,
    "context_format": "markdown",
    "context_length": 15000,
    "processed_at": ISODate("2026-01-20T10:30:00Z")
}

// Индексы
db.qa_results.createIndex({ "protocol_id": 1 }, { unique: true })
db.qa_results.createIndex({ "extraction_result.winner_found": 1 })
db.qa_results.createIndex({ "extraction_result.document_info.is_service_file": 1 })
db.qa_results.createIndex({ "processed_at": -1 })
```

---

## 12. Тестовые случаи

На основе анализа реальных файлов определены следующие тестовые сценарии:

### Тест 1: Несостоявшаяся без победителя
**Input:** Протокол с "не подано ни одной заявки"
**Expected:**
- `winner_found: false`
- `winners: []`
- `procurement_info.status: "not_held"`
- `procurement_info.not_held_reason: "no_applications"`

### Тест 2: Несостоявшаяся С победителем (критический!)
**Input:** Протокол с "подана только одна заявка" + "Результат: Победитель"
**Expected:**
- `winner_found: true`
- `winners[0].name: "ООО \"ИНТРЕЙД\""`
- `procurement_info.status: "not_held"`
- `flags.procurement_not_held_but_winner_exists: true`
- `flags.is_single_participant_winner: true`

### Тест 3: Анонимизированные данные
**Input:** Протокол с "Заявка №31666, -"
**Expected:**
- `winner_found: true`
- `winners[0].name: "Заявка №31666"`
- `winners[0].data_anonymized: true`
- `flags.data_anonymized: true`

### Тест 4: Служебный файл
**Input:** Файл "Расчёт баллов" без итогов
**Expected:**
- `winner_found: false`
- `winners: []`
- `document_info.is_service_file: true`

### Тест 5: Многолотовая закупка
**Input:** Протокол с несколькими лотами и победителями
**Expected:**
- `winner_found: true`
- `len(winners) > 1`
- `flags.multiple_lots: true`

---

## 13. Чек-лист для обработки протокола

```
□ Определить тип документа (протокол / служебный файл)
□ Найти раздел с результатами подведения итогов
□ Проверить статус закупки (состоялась / не состоялась)
□ Если "не состоялась" — проверить ПРИЧИНУ:
  □ "Нет заявок" → winner_found: false
  □ "Одна заявка" → winner_found: true (!)
□ Найти таблицу с победителем
□ Убедиться, что это НЕ данные заказчика (в начале документа)
□ Убедиться, что это НЕ данные оператора ЭТП
□ Извлечь все доступные реквизиты победителя
□ Проверить, анонимизированы ли данные
□ Если несколько лотов — извлечь по каждому
□ Заполнить reasoning с обоснованием
```

---

## 14. Резюме решений

| Параметр | Решение |
|----------|---------|
| **Источник контекста** | MongoDB (markdown_content) |
| **LLM провайдер** | GLM-4.7 (Z.ai) |
| **Формат контекста** | Markdown (основной), HTML (fallback) |
| **JSON Docling** | НЕ использовать для контекста |
| **Стратегия хранения** | Перезапись (1 протокол = 1 результат) |
| **API** | REST (FastAPI) |
| **Валидация** | Pydantic v2 |
| **Версия промптов** | v2.0 с edge cases |
| **Поддержка нескольких лотов** | ДА (List[WinnerInfo]) |
| **Анонимизированные данные** | ДА (флаг data_anonymized) |

---

**Статус:** ✅ Согласовано и готово к реализации

**Следующие шаги:**
1. Создать структуру проекта
2. Реализовать domain entities
3. Создать файлы промптов v2
4. Реализовать infrastructure
5. Реализовать application layer
6. Создать REST API
7. Написать тесты по сценариям
8. Docker + deployment