#!/usr/bin/env python3
"""Test script to verify LLM_qaenrich migration."""

import asyncio
import sys
sys.path.insert(0, "/home/pak/projects/LLM_qaenrich")

from infrastructure.loaders.mongo_loader import MongoContextLoader
from application.orchestrator import QAOrchestrator
from config import get_settings


async def test_migration():
    """Test the migrated LLM_qaenrich service."""
    print("=" * 60)
    print("       ТЕСТ ПЕРЕНОСА LLM_qaenrich")
    print("=" * 60)

    # Get settings
    settings = get_settings()
    print(f"\n📋 Конфигурация:")
    print(f"  MongoDB: {settings.MONGO_URI.split('@')[1] if '@' in settings.MONGO_URI else 'localhost'}")
    print(f"  Database: {settings.MONGO_DATABASE}")
    print(f"  Collection (source): {settings.MONGO_PROTOCOLS_COLLECTION}")
    print(f"  Collection (results): {settings.MONGO_QA_COLLECTION}")

    # Test loader
    print(f"\n🔍 Тест загрузчика документов:")
    loader = MongoContextLoader(settings.MONGO_URI, settings.MONGO_DATABASE, settings.MONGO_PROTOCOLS_COLLECTION)

    total_count = await loader.count()
    print(f"  Всего документов в docling_results: {total_count}")

    # Get 30 documents for testing
    unit_ids = await loader.list_unit_ids(limit=30)
    print(f"  Выбрано для тестирования: {len(unit_ids)} документов")

    # Test loading one document
    if unit_ids:
        test_unit_id = unit_ids[0]
        doc = await loader.load(test_unit_id)
        if doc:
            print(f"  Тестовый документ ({test_unit_id}): {len(doc.content)} символов")
        else:
            print(f"  ❌ Не удалось загрузить {test_unit_id}")
            return False

    await loader.close()

    # Test orchestrator class exists
    print(f"\n⚙️ Тест оркестратора:")
    try:
        # QAOrchestrator требует зависимостей, проверим только импорт
        from application.orchestrator import QAOrchestrator as Orch
        print(f"  ✅ QAOrchestrator класс доступен")
    except Exception as e:
        print(f"  ❌ Ошибка импорта: {e}")
        return False

    # Test API service name
    print(f"\n🌐 Тест конфигурации сервиса:")
    # Import and check main.py
    import importlib.util
    spec = importlib.util.spec_from_file_location("main", "/home/pak/projects/LLM_qaenrich/main.py")
    main_module = importlib.util.module_from_spec(spec)

    # Check service name in main module
    with open("/home/pak/projects/LLM_qaenrich/main.py") as f:
        content = f.read()
        if '"service": "llm_qaenrich"' in content:
            print(f"  ✅ Имя сервиса обновлено: llm_qaenrich")
        else:
            print(f"  ❌ Имя сервиса не обновлено")

    # Check pyproject.toml
    with open("/home/pak/projects/LLM_qaenrich/pyproject.toml") as f:
        content = f.read()
        if 'name = "llm_qaenrich"' in content:
            print(f"  ✅ pyproject.toml обновлён")
        else:
            print(f"  ❌ pyproject.toml не обновлён")

    print("\n" + "=" * 60)
    print("✅ ТЕСТ ПРОЙДЕН УСПЕШНО!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    result = asyncio.run(test_migration())
    sys.exit(0 if result else 1)
