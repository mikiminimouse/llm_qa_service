#!/usr/bin/env python3
"""
Полноценное тестирование LLM_qaenrich с детальным сбором метрик.

Тестирует обработку всех документов с анализом:
- Времени обработки по типам документов
- Успешности извлечения данных
- Ошибок и их причин
- Производительности по различным срезам
"""

import asyncio
import json
import logging
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

# Добавляем путь к проекту
sys.path.insert(0, "/home/pak/projects/LLM_qaenrich")

from motor.motor_asyncio import AsyncIOMotorClient
from application.orchestrator import QAOrchestrator
from config import get_settings
from infrastructure.llm.factory import create_llm_client
from infrastructure.repositories.mongo_qa_repository import MongoQARepository
from infrastructure.loaders.mongo_loader import MongoContextLoader
from infrastructure.prompt_manager import PromptManager
from domain.entities.extraction_components import DocumentInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class TestMetrics:
    """Класс для сбора метрик тестирования."""

    def __init__(self):
        self.start_time = time.time()
        self.total_documents = 0
        self.processed = 0
        self.successful = 0
        self.failed = 0
        self.skipped = 0
        self.errors = defaultdict(list)
        self.processing_times = []
        self.document_types = Counter()
        self.results_by_type = defaultdict(list)
        self.inn_stats = {"with_inn": 0, "without_inn": 0, "invalid_inn": 0}
        self.winner_stats = {"found": 0, "not_found": 0, "service_file": 0}
        self.llm_calls = 0
        self.llm_total_time = 0
        self.token_usage = {"prompt": 0, "completion": 0}

    def add_error(self, error_type: str, unit_id: str, message: str):
        """Добавить ошибку в статистику."""
        self.errors[error_type].append({"unit_id": unit_id, "message": message})

    def get_summary(self) -> Dict:
        """Получить итоговую статистику."""
        duration = time.time() - self.start_time
        avg_time = sum(self.processing_times) / len(self.processing_times) if self.processing_times else 0

        return {
            "duration_seconds": round(duration, 2),
            "total_documents": self.total_documents,
            "processed": self.processed,
            "successful": self.successful,
            "failed": self.failed,
            "skipped": self.skipped,
            "success_rate": round(self.successful / max(self.processed, 1) * 100, 1),
            "avg_processing_time_ms": round(avg_time * 1000, 1),
            "document_types": dict(self.document_types),
            "inn_stats": self.inn_stats,
            "winner_stats": self.winner_stats,
            "errors_by_type": {k: len(v) for k, v in self.errors.items()},
            "llm_calls": self.llm_calls,
        }


async def run_full_test():
    """Запустить полное тестирование всех документов."""
    metrics = TestMetrics()

    logger.info("=" * 70)
    logger.info("     ПОЛНОЦЕННОЕ ТЕСТИРОВАНИЕ LLM_qaenrich")
    logger.info("=" * 70)

    # Настройка
    settings = get_settings()
    logger.info(f"MongoDB: {settings.MONGO_DATABASE}")
    logger.info(f"GLM Model: {settings.GLM_MODEL}")

    # Инициализация компонентов
    logger.info("\n⚙️ Инициализация компонентов...")
    try:
        llm_client = create_llm_client(
            provider="glm",
            api_key=settings.GLM_API_KEY,
            base_url=settings.GLM_BASE_URL,
            model=settings.GLM_MODEL,
            timeout=settings.GLM_TIMEOUT,
            max_retries=settings.GLM_MAX_RETRIES,
            retry_delay=settings.GLM_RETRY_DELAY,
        )
        loader = MongoContextLoader(settings.MONGO_URI, settings.MONGO_DATABASE, settings.MONGO_PROTOCOLS_COLLECTION)
        repository = MongoQARepository(settings.MONGO_URI, settings.MONGO_DATABASE, settings.MONGO_QA_COLLECTION)
        prompt_manager = PromptManager()
        orchestrator = QAOrchestrator(
            llm_client=llm_client,
            context_loader=loader,
            repository=repository,
            prompt_manager=prompt_manager,
            skip_processed=False,  # Обрабатывать все
        )
        logger.info("✅ Компоненты инициализированы")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации: {e}")
        logger.error(f"Traceback: ", exc_info=True)
        return metrics

    # Получение списка документов
    logger.info("\n📋 Получение списка документов...")
    unit_ids = await loader.list_unit_ids(limit=2000)
    metrics.total_documents = len(unit_ids)
    logger.info(f"Найдено документов: {metrics.total_documents}")

    # Определение типов документов
    await categorize_documents(unit_ids, loader, metrics)

    # Тестирование по батчам
    batch_size = 10
    total_batches = (len(unit_ids) + batch_size - 1) // batch_size

    logger.info(f"\n🚀 Начало тестирования (batch_size={batch_size}, batches={total_batches})...")

    for batch_idx in range(total_batches):
        start_idx = batch_idx * batch_size
        end_idx = min(start_idx + batch_size, len(unit_ids))
        batch_unit_ids = unit_ids[start_idx:end_idx]

        logger.info(f"\n--- Batch {batch_idx + 1}/{total_batches} ({start_idx + 1}-{end_idx}) ---")

        # Обработка батча
        for unit_id in batch_unit_ids:
            result = await process_single_document(
                orchestrator, unit_id, loader, metrics
            )
            if result:
                metrics.processed += 1

        # Промежуточная статистика каждые 5 батчей
        if (batch_idx + 1) % 5 == 0:
            print_interim_stats(metrics, batch_idx + 1, total_batches)

    # Финальная статистика
    await loader.close()

    logger.info("\n" + "=" * 70)
    logger.info("     ИТОГОВАЯ СТАТИСТИКА")
    logger.info("=" * 70)

    summary = metrics.get_summary()
    print_final_stats(summary, metrics)

    # Сохранение детального отчёта
    await save_detailed_report(metrics)

    return metrics


async def categorize_documents(unit_ids: List[str], loader, metrics: TestMetrics):
    """Классифицировать документы по типу."""
    logger.info("📊 Классификация документов по типу...")

    types = defaultdict(int)

    for unit_id in unit_ids[:100]:  # Выборка для анализа
        doc = await loader.load(unit_id)
        if doc and doc.source_file:
            # Определяем тип по пути
            if "/html/" in doc.source_file:
                types["html"] += 1
            elif "/docx/" in doc.source_file:
                types["docx"] += 1
            elif "/pdf/" in doc.source_file:
                types["pdf"] += 1
            elif "/image/" in doc.source_file:
                types["image"] += 1
            elif "/jpeg/" in doc.source_file:
                types["jpeg"] += 1
            elif "/tiff/" in doc.source_file:
                types["tiff"] += 1
            else:
                types["other"] += 1

    metrics.document_types = types
    logger.info(f"Типы документов: {dict(types)}")


async def process_single_document(
    orchestrator: QAOrchestrator,
    unit_id: str,
    loader,
    metrics: TestMetrics
) -> bool:
    """Обработать один документ."""
    start_time = time.time()

    try:
        # Проверяем, был ли уже обработан
        existing = await orchestrator.repository.get_by_unit_id(unit_id)
        if existing and existing.get("winner_found") is not None:
            metrics.skipped += 1
            # Собираем статистику из существующих результатов
            collect_stats_from_existing(existing, metrics)
            return False

        # Загружаем документ
        doc = await loader.load(unit_id)
        if not doc:
            metrics.add_error("document_not_found", unit_id, "Документ не найден")
            return False

        # Определяем тип документа
        doc_type = get_document_type(doc)
        metrics.document_types[doc_type] += 1

        # Обрабатываем через Orchestrator
        result = await orchestrator.process_protocol(unit_id)

        processing_time = time.time() - start_time
        metrics.processing_times.append(processing_time)

        if result.success:
            metrics.successful += 1

            # Анализируем результат
            if result.record:
                collect_stats_from_result(result.record, doc_type, metrics)
        else:
            metrics.failed += 1
            metrics.add_error("processing_failed", unit_id, result.error or "Неизвестная ошибка")

        return result.success

    except Exception as e:
        processing_time = time.time() - start_time
        metrics.failed += 1
        metrics.add_error("exception", unit_id, str(e))
        logger.error(f"Ошибка при обработке {unit_id}: {e}")
        return False


def get_document_type(doc) -> str:
    """Определить тип документа."""
    if doc.source_file:
        if "/html/" in doc.source_file:
            return "html"
        elif "/docx/" in doc.source_file:
            return "docx"
        elif "/pdf/" in doc.source_file:
            return "pdf"
        elif "/image/" in doc.source_file:
            return "image"
        elif "/jpeg/" in doc.source_file:
            return "jpeg"
        elif "/tiff/" in doc.source_file:
            return "tiff"
        elif "/xlsx/" in doc.source_file:
            return "xlsx"
    return "unknown"


def collect_stats_from_existing(record: Dict, metrics: TestMetrics):
    """Собрать статистику из существующего результата."""
    if record.get("winner_found"):
        metrics.winner_stats["found"] += 1

        winners = record.get("result", {}).get("winners", [])
        if winners:
            winner = winners[0]
            inn = winner.get("inn")
            if inn and len(inn) >= 10:
                metrics.inn_stats["with_inn"] += 1
            else:
                metrics.inn_stats["without_inn"] += 1
        else:
            metrics.inn_stats["without_inn"] += 1
    else:
        flags = record.get("result", {}).get("flags", {})
        if flags.get("is_service_file"):
            metrics.winner_stats["service_file"] += 1
        else:
            metrics.winner_stats["not_found"] += 1


def collect_stats_from_result(record, doc_type: str, metrics: TestMetrics):
    """Собрать статистику из результата обработки."""
    metrics.results_by_type[doc_type].append(record)

    if record.winner_found:
        metrics.winner_stats["found"] += 1

        if record.winners:
            inn = record.winners[0].get("inn")
            if inn and len(inn) >= 10:
                metrics.inn_stats["with_inn"] += 1
            else:
                metrics.inn_stats["without_inn"] += 1
    else:
        if record.flags and record.flags.is_service_file:
            metrics.winner_stats["service_file"] += 1
        else:
            metrics.winner_stats["not_found"] += 1


def print_interim_stats(metrics: TestMetrics, batch: int, total_batches: int):
    """Вывести промежуточную статистику."""
    processed = metrics.processed
    successful = metrics.successful
    failed = metrics.failed
    skipped = metrics.skipped

    logger.info(f"Прогресс: Batch {batch}/{total_batches} | "
                f"Обработано: {processed}, Успешно: {successful}, Ошибок: {failed}, Пропущено: {skipped}")


def print_final_stats(summary: Dict, metrics: TestMetrics):
    """Вывести финальную статистику."""
    print(f"\n⏱️ Время выполнения: {summary['duration_seconds']} сек")
    print(f"📄 Всего документов: {summary['total_documents']}")
    print(f"✅ Успешно обработано: {summary['successful']}")
    print(f"❌ С ошибками: {summary['failed']}")
    print(f"⏭️ Пропущено (уже были): {summary['skipped']}")
    print(f"📈 Успешность: {summary['success_rate']}%")
    print(f"⚡ Среднее время: {summary['avg_processing_time_ms']} мс")

    print(f"\n📊 По типам документов:")
    for doc_type, count in summary.get("document_types", {}).items():
        print(f"   {doc_type}: {count}")

    print(f"\n🔍 Статистика ИНН:")
    inn = summary.get("inn_stats", {})
    print(f"   С ИНН: {inn.get('with_inn', 0)}")
    print(f"   Без ИНН: {inn.get('without_inn', 0)}")

    print(f"\n🏆 Статистика победителей:")
    winner = summary.get("winner_stats", {})
    print(f"   Найдено: {winner.get('found', 0)}")
    print(f"   Не найдено: {winner.get('not_found', 0)}")
    print(f"   Служебные: {winner.get('service_file', 0)}")

    if summary.get("errors_by_type"):
        print(f"\n⚠️ Ошибки по типам:")
        for error_type, count in summary["errors_by_type"].items():
            print(f"   {error_type}: {count}")


async def save_detailed_report(metrics: TestMetrics):
    """Сохранить детальный отчёт в JSON."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": metrics.get_summary(),
        "errors": dict(metrics.errors),
        "results_by_type": {
            k: [{"unit_id": r.unit_id, "winner_found": r.winner_found} for r in v[:10]]
            for k, v in metrics.results_by_type.items()
        },
    }

    report_path = f"/home/pak/projects/LLM_qaenrich/test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"\n📄 Отчёт сохранён: {report_path}")


async def analyze_performance_by_type():
    """Детальный анализ производительности по типам документов."""
    logger.info("\n" + "=" * 70)
    logger.info("     АНАЛИЗ ПРОИЗВОДИТЕЛЬНОСТИ ПО ТИПАМ ДОКУМЕНТОВ")
    logger.info("=" * 70)

    settings = get_settings()
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DATABASE]
    collection = db[settings.MONGO_QA_COLLECTION]

    # Агрегация по source_file (типу документа)
    pipeline = [
        {"$group": {
            "_id": "$source_file",
            "count": {"$sum": 1},
            "winner_found": {"$sum": {"$cond": ["$winner_found", 1, 0]}},
            "avg_time": {"$avg": "$processing_time_ms"}
        }},
        {"$sort": {"count": -1}}
    ]

    results = await collection.aggregate(pipeline).to_list(50)

    print("\n📊 Производительность по типу источника:")
    print(f"{'Тип':<15} | {'Кол-во':>8} | {'Победителей':>12} | {'Сред. время (мс)':>15}")
    print("-" * 70)

    for r in results[:20]:
        source_type = get_type_from_path(r.get("_id", ""))
        avg_time = r.get('avg_time') or 0
        print(f"{source_type:<15} | {r['count']:>8} | {r['winner_found']:>12} | {avg_time:>15.1f}")

    client.close()


def get_type_from_path(path: Optional[str]) -> str:
    """Извлечь тип документа из пути."""
    if not path:
        return "unknown"
    if "/html/" in path:
        return "html"
    elif "/docx/" in path:
        return "docx"
    elif "/pdf/" in path:
        return "pdf"
    elif "/image/" in path:
        return "image"
    elif "/jpeg/" in path:
        return "jpeg"
    return "other"


if __name__ == "__main__":
    metrics = asyncio.run(run_full_test())

    # Дополнительный анализ производительности
    asyncio.run(analyze_performance_by_type())
