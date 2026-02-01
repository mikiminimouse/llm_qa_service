#!/usr/bin/env python3
"""
Система сбора детальных метрик для pipeline LLM_qaenrich.

Собирает метрики по следующим измерениям:
- По типам документов (docx, html, xlsx, xml)
- По размеру документов (empty, small, medium, large, xlarge)
- Pipeline этапы (load, llm, parse, save)
- Результаты (winner_found, inn_found, confidence)
- Ошибки (timeout, 429, parse_error, llm_error)
- Производительность (throughput, percentiles)
"""

import dataclasses
import json
import logging
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, "/home/pak/projects/LLM_qaenrich")

logger = logging.getLogger(__name__)


class DocumentType(Enum):
    """Типы документов."""
    DOCX = "docx"
    HTML = "html"
    XLSX = "xlsx"
    XML = "xml"
    UNKNOWN = "unknown"


class DocumentSize(Enum):
    """Категории размеров документов по количеству символов."""
    EMPTY = "empty"       # 0 chars
    SMALL = "small"       # 1-499 chars
    MEDIUM = "medium"     # 500-1999 chars
    LARGE = "large"       # 2000-4999 chars
    XLARGE = "xlarge"     # >=5000 chars


class ErrorType(Enum):
    """Типы ошибок."""
    TIMEOUT = "timeout"
    HTTP_429 = "http_429"
    RATE_LIMITED = "rate_limited"
    PARSE_ERROR = "parse_error"
    LLM_ERROR = "llm_error"
    EMPTY_CONTENT = "empty_content"
    UNKNOWN = "unknown"


@dataclasses.dataclass
class PipelineMetrics:
    """Метрики для одного документа."""
    unit_id: str
    document_type: DocumentType
    document_size: DocumentSize
    content_length: int

    # Временные метрики (в миллисекундах)
    load_time_ms: float = 0
    llm_time_ms: float = 0
    parse_time_ms: float = 0
    save_time_ms: float = 0
    total_time_ms: float = 0

    # Результаты
    success: bool = False
    skipped: bool = False
    winner_found: bool = False
    inn_found: bool = False
    confidence: float = 0.0

    # Ошибки
    error_type: Optional[ErrorType] = None
    error_message: Optional[str] = None

    # Дополнительные данные
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь для сериализации."""
        return {
            "unit_id": self.unit_id,
            "document_type": self.document_type.value,
            "document_size": self.document_size.value,
            "content_length": self.content_length,
            "load_time_ms": self.load_time_ms,
            "llm_time_ms": self.llm_time_ms,
            "parse_time_ms": self.parse_time_ms,
            "save_time_ms": self.save_time_ms,
            "total_time_ms": self.total_time_ms,
            "success": self.success,
            "skipped": self.skipped,
            "winner_found": self.winner_found,
            "inn_found": self.inn_found,
            "confidence": self.confidence,
            "error_type": self.error_type.value if self.error_type else None,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


class MetricsCollector:
    """
    Коллектор метрик для pipeline LLM_qaenrich.

    Собирает, агрегирует и анализирует метрики на всех этапах обработки.
    """

    def __init__(self, output_dir: Path = Path("/home/pak/llm_qa_service/metrics")):
        """
        Инициализация коллектора.

        Args:
            output_dir: Директория для сохранения метрик.
        """
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.metrics: List[PipelineMetrics] = []
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def start(self) -> None:
        """Начало сбора метрик."""
        self.start_time = datetime.now().timestamp()
        logger.info("📊 MetricsCollector: начало сбора метрик")

    def finish(self) -> None:
        """Окончание сбора метрик."""
        self.end_time = datetime.now().timestamp()
        duration = self.end_time - self.start_time if self.start_time else 0
        logger.info(f"📊 MetricsCollector: окончание сбора метрик (всего времени: {duration:.1f} сек)")

    def add_metric(self, metric: PipelineMetrics) -> None:
        """Добавление метрики."""
        self.metrics.append(metric)

    def add_from_result(
        self,
        unit_id: str,
        processing_time_ms: float,
        success: bool,
        skipped: bool,
        error: Optional[str],
        record: Optional[Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Добавление метрик из результата QAOrchestrator.

        Args:
            unit_id: ID документа
            processing_time_ms: Время обработки в мс
            success: Успешность обработки
            skipped: Был ли пропущен
            error: Текст ошибки (если есть)
            record: Результат обработки
            metadata: Дополнительные метаданные
        """
        # Определение типа документа
        doc_type = DocumentType.UNKNOWN
        if metadata:
            file_type = metadata.get("file_type", "")
            doc_type = DocumentType(file_type) if file_type in [e.value for e in DocumentType] else DocumentType.UNKNOWN

        # Определение размера
        content_length = metadata.get("content_length", 0) if metadata else 0
        doc_size = self._categorize_size(content_length)

        # Определение типа ошибки
        error_type = None
        if error:
            error_type = self._classify_error(error)

        # Извлечение результатов
        winner_found = False
        inn_found = False
        confidence = 0.0

        if record and hasattr(record, 'result'):
            result = record.result
            if hasattr(result, 'winner_found'):
                winner_found = result.winner_found
            if hasattr(result, 'inn_found'):
                inn_found = result.inn_found
            if hasattr(result, 'confidence'):
                confidence = result.confidence

        metric = PipelineMetrics(
            unit_id=unit_id,
            document_type=doc_type,
            document_size=doc_size,
            content_length=content_length,
            total_time_ms=processing_time_ms,
            success=success,
            skipped=skipped,
            winner_found=winner_found,
            inn_found=inn_found,
            confidence=confidence,
            error_type=error_type,
            error_message=error,
            metadata=metadata or {},
        )
        self.add_metric(metric)

    @staticmethod
    def _categorize_size(content_length: int) -> DocumentSize:
        """Категоризация размера документа."""
        if content_length == 0:
            return DocumentSize.EMPTY
        elif content_length < 500:
            return DocumentSize.SMALL
        elif content_length < 2000:
            return DocumentSize.MEDIUM
        elif content_length < 5000:
            return DocumentSize.LARGE
        else:
            return DocumentSize.XLARGE

    @staticmethod
    def _classify_error(error: str) -> ErrorType:
        """Классификация ошибки по тексту."""
        error_lower = error.lower()
        if "timeout" in error_lower or "timed out" in error_lower:
            return ErrorType.TIMEOUT
        elif "429" in error_lower:
            return ErrorType.HTTP_429
        elif "rate limit" in error_lower:
            return ErrorType.RATE_LIMITED
        elif "parse" in error_lower or "json" in error_lower:
            return ErrorType.PARSE_ERROR
        elif "llm" in error_lower or "api" in error_lower:
            return ErrorType.LLM_ERROR
        elif "empty" in error_lower or "no content" in error_lower:
            return ErrorType.EMPTY_CONTENT
        else:
            return ErrorType.UNKNOWN

    def get_summary(self) -> Dict[str, Any]:
        """Получить сводную статистику."""
        if not self.metrics:
            return {}

        total = len(self.metrics)
        success = sum(1 for m in self.metrics if m.success and not m.skipped)
        failed = sum(1 for m in self.metrics if not m.success)
        skipped = sum(1 for m in self.metrics if m.skipped)

        times = [m.total_time_ms for m in self.metrics if m.total_time_ms > 0]
        avg_time = statistics.mean(times) if times else 0
        median_time = statistics.median(times) if times else 0

        duration = self.end_time - self.start_time if self.start_time and self.end_time else 0
        throughput = total / duration if duration > 0 else 0

        winner_found = sum(1 for m in self.metrics if m.winner_found)
        inn_found = sum(1 for m in self.metrics if m.inn_found)

        return {
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": round(duration, 2),
            "total_documents": total,
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "success_rate": round(100 * success / total, 1) if total > 0 else 0,
            "avg_time_ms": round(avg_time, 1),
            "median_time_ms": round(median_time, 1),
            "throughput_per_sec": round(throughput, 3),
            "winner_found": winner_found,
            "winner_rate": round(100 * winner_found / max(success, 1), 1),
            "inn_found": inn_found,
            "inn_rate": round(100 * inn_found / max(success, 1), 1),
        }

    def get_by_type(self) -> Dict[str, Any]:
        """Статистика по типам документов."""
        by_type: Dict[DocumentType, List[PipelineMetrics]] = defaultdict(list)
        for m in self.metrics:
            by_type[m.document_type].append(m)

        result = {}
        for doc_type, metrics in by_type.items():
            times = [m.total_time_ms for m in metrics if m.total_time_ms > 0]
            success = sum(1 for m in metrics if m.success and not m.skipped)
            winner_found = sum(1 for m in metrics if m.winner_found)

            result[doc_type.value] = {
                "count": len(metrics),
                "success": success,
                "failed": len(metrics) - success,
                "winner_found": winner_found,
                "winner_rate": round(100 * winner_found / max(success, 1), 1),
                "avg_time_ms": round(statistics.mean(times), 1) if times else 0,
                "median_time_ms": round(statistics.median(times), 1) if times else 0,
            }

        return result

    def get_by_size(self) -> Dict[str, Any]:
        """Статистика по размеру документов."""
        by_size: Dict[DocumentSize, List[PipelineMetrics]] = defaultdict(list)
        for m in self.metrics:
            by_size[m.document_size].append(m)

        result = {}
        for doc_size, metrics in by_size.items():
            times = [m.total_time_ms for m in metrics if m.total_time_ms > 0]
            success = sum(1 for m in metrics if m.success and not m.skipped)
            winner_found = sum(1 for m in metrics if m.winner_found)

            result[doc_size.value] = {
                "count": len(metrics),
                "success": success,
                "failed": len(metrics) - success,
                "winner_found": winner_found,
                "winner_rate": round(100 * winner_found / max(success, 1), 1),
                "avg_time_ms": round(statistics.mean(times), 1) if times else 0,
                "median_time_ms": round(statistics.median(times), 1) if times else 0,
            }

        return result

    def get_errors(self) -> Dict[str, Any]:
        """Статистика по ошибкам."""
        errors = [m for m in self.metrics if m.error_type]

        by_type: Dict[ErrorType, int] = Counter(m.error_type for m in errors)
        error_messages = Counter(m.error_message for m in errors if m.error_message)

        return {
            "total_errors": len(errors),
            "by_type": {et.value: count for et, count in by_type.most_common()},
            "most_common": [
                {"error": msg, "count": count}
                for msg, count in error_messages.most_common(10)
            ],
        }

    def get_percentiles(self) -> Dict[str, Any]:
        """Процентили по времени обработки."""
        times = sorted([m.total_time_ms for m in self.metrics if m.total_time_ms > 0])

        if not times:
            return {}

        return {
            "p50": round(times[len(times) // 2], 1),
            "p75": round(times[int(len(times) * 0.75)], 1),
            "p90": round(times[int(len(times) * 0.90)], 1),
            "p95": round(times[int(len(times) * 0.95)], 1),
            "p99": round(times[int(len(times) * 0.99)], 1),
            "min": round(times[0], 1),
            "max": round(times[-1], 1),
        }

    def save_all(self) -> Dict[str, Path]:
        """Сохранить все метрики в файлы."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        files = {}

        # Summary
        summary_path = self.output_dir / f"summary_{timestamp}.json"
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(self.get_summary(), f, indent=2, ensure_ascii=False)
        files["summary"] = summary_path

        # By type
        by_type_path = self.output_dir / f"by_type_{timestamp}.json"
        with open(by_type_path, 'w', encoding='utf-8') as f:
            json.dump(self.get_by_type(), f, indent=2, ensure_ascii=False)
        files["by_type"] = by_type_path

        # By size
        by_size_path = self.output_dir / f"by_size_{timestamp}.json"
        with open(by_size_path, 'w', encoding='utf-8') as f:
            json.dump(self.get_by_size(), f, indent=2, ensure_ascii=False)
        files["by_size"] = by_size_path

        # Errors
        errors_path = self.output_dir / f"errors_{timestamp}.json"
        with open(errors_path, 'w', encoding='utf-8') as f:
            json.dump(self.get_errors(), f, indent=2, ensure_ascii=False)
        files["errors"] = errors_path

        # Percentiles
        percentiles_path = self.output_dir / f"percentiles_{timestamp}.json"
        with open(percentiles_path, 'w', encoding='utf-8') as f:
            json.dump(self.get_percentiles(), f, indent=2, ensure_ascii=False)
        files["percentiles"] = percentiles_path

        # Raw metrics (для детального анализа)
        raw_path = self.output_dir / f"raw_{timestamp}.json"
        with open(raw_path, 'w', encoding='utf-8') as f:
            json.dump([m.to_dict() for m in self.metrics], f, indent=2, ensure_ascii=False)
        files["raw"] = raw_path

        # Latest (символические ссылки)
        for name, path in files.items():
            latest_path = self.output_dir / f"{name}_latest.json"
            latest_path.write_text(path.read_text(encoding='utf-8'), encoding='utf-8')

        logger.info(f"📁 Метрики сохранены: {self.output_dir}")
        return files

    def print_summary(self) -> None:
        """Вывести сводку в лог."""
        summary = self.get_summary()
        if not summary:
            logger.info("Нет метрик для отображения")
            return

        logger.info("=" * 70)
        logger.info("📊 СВОДКА МЕТРИК")
        logger.info("=" * 70)
        logger.info(f"Всего документов: {summary['total_documents']}")
        logger.info(f"Успешно: {summary['success']} | Ошибок: {summary['failed']} | Пропущено: {summary['skipped']}")
        logger.info(f"Успешность: {summary['success_rate']}%")
        logger.info(f"Время выполнения: {summary['duration_seconds']} сек")
        logger.info(f"Пропускная способность: {summary['throughput_per_sec']} док/сек")
        logger.info(f"Среднее время: {summary['avg_time_ms']} мс | Медиана: {summary['median_time_ms']} мс")
        logger.info(f"Winner найден: {summary['winner_found']}/{summary['success']} ({summary['winner_rate']}%)")
        logger.info(f"INN найден: {summary['inn_found']}/{summary['success']} ({summary['inn_rate']}%)")
        logger.info("=" * 70)


def print_comparison(baseline: Dict[str, Any], current: Dict[str, Any]) -> None:
    """
    Вывести сравнение двух результатов тестирования.

    Args:
        baseline: Базовые метрики
        current: Текущие метрики
    """
    print("\n" + "=" * 70)
    print(f"{'СРАВНЕНИЕ РЕЗУЛЬТАТОВ':^70}")
    print("=" * 70)

    metrics_to_compare = [
        ("Пропускная способность (док/сек)", "throughput_per_sec"),
        ("Среднее время (мс)", "avg_time_ms"),
        ("Медиана времени (мс)", "median_time_ms"),
        ("Winner rate (%)", "winner_rate"),
        ("Успешность (%)", "success_rate"),
    ]

    for label, key in metrics_to_compare:
        base_val = baseline.get(key, 0)
        curr_val = current.get(key, 0)

        if base_val > 0:
            diff = curr_val - base_val
            diff_pct = (diff / base_val) * 100
            arrow = "↑" if diff > 0 else "↓" if diff < 0 else "="
            print(f"{label}:")
            print(f"   Было: {base_val} | Стало: {curr_val} | {arrow} {diff_pct:+.1f}%")
        else:
            print(f"{label}: {curr_val}")

    print("=" * 70)
