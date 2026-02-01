"""Test v5 prompts on documents where INN was not extracted."""

import asyncio
import json
import sys
from pathlib import Path

# Добавляем проект в путь
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config import get_settings
from infrastructure.llm.factory import create_llm_client
from infrastructure.prompt_manager import PromptManager


def get_document_content(unit_id: str) -> str:
    """Получает содержимое документа из MongoDB."""
    from pymongo import MongoClient

    settings = get_settings()
    client = MongoClient(settings.MONGO_URI)
    db = client[settings.MONGO_DATABASE]

    doc = db[settings.MONGO_PROTOCOLS_COLLECTION].find_one({"unit_id": unit_id})

    if not doc or "content" not in doc:
        client.close()
        return None

    # Форматируем содержимое для промпта
    content = doc["content"]
    texts = content.get("texts", [])
    tables = content.get("tables", [])

    result_parts = []

    # Добавляем тексты
    for text_item in texts[:20]:  # Ограничиваем количество
        if text_item.get("text"):
            result_parts.append(text_item["text"])

    # Добавляем таблицы
    for table in tables[:10]:
        table_text = table.get("text", "")
        if table_text:
            result_parts.append(f"\n--- Таблица ---\n{table_text}")

    client.close()
    return "\n\n".join(result_parts)[:15000]  # Ограничиваем размер


async def process_with_v5(unit_id: str, pm: PromptManager, llm_client) -> dict:
    """Обрабатывает документ с v5 промптами."""
    # Получаем содержимое документа
    document_content = get_document_content(unit_id)
    if not document_content:
        return {"error": "Document not found"}

    # Загружаем v5 промпты
    system_prompt = pm.get_system_prompt("winner_extractor_v5")
    user_prompt = pm.format_user_prompt(
        "extract_winner_v5",
        document_content=document_content[:12000],
    )

    try:
        response = await llm_client.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=8192,  # Увеличиваем лимит для полного JSON
        )

        result_text = response.content

        # Парсим JSON
        # Извлекаем JSON если он в markdown
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0].strip()
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0].strip()

        result = json.loads(result_text)
        result["raw_response"] = response.content[:500] if response.content else ""

        return result

    except json.JSONDecodeError as e:
        return {
            "error": f"JSON parse error: {e}",
            "raw_response": response.content[:2000] if hasattr(response, 'content') else "No response",
            "winner_found": False,
            "winners": []
        }
    except Exception as e:
        return {
            "error": str(e),
            "winner_found": False,
            "winners": []
        }


async def get_previous_result(unit_id: str) -> dict:
    """Получает предыдущий результат из qa_results."""
    from pymongo import MongoClient

    settings = get_settings()
    client = MongoClient(settings.MONGO_URI)
    db = client[settings.MONGO_DATABASE]

    doc = db[settings.MONGO_QA_COLLECTION].find_one({"unit_id": unit_id})
    client.close()

    if doc:
        return doc.get("result", {})
    return None


async def main():
    """Главная функция тестирования."""
    settings = get_settings()

    # Инициализируем зависимости
    # Используем абсолютный путь к промптам
    prompts_dir = project_root / settings.PROMPTS_DIR
    pm = PromptManager(str(prompts_dir))
    llm_client = create_llm_client(
        provider="glm",
        api_key=settings.GLM_API_KEY,
        base_url=settings.GLM_BASE_URL,
        model=settings.GLM_MODEL,
        timeout=settings.GLM_TIMEOUT,
        max_retries=settings.GLM_MAX_RETRIES,
        retry_delay=settings.GLM_RETRY_DELAY,
    )

    # Тестовые случаи - документы где ИНН не извлечён
    test_cases = [
        "UNIT_d7ba9b7b1a6949b5",
        "UNIT_1b856be82c95455f",  # ООО "ТЗК АЭРОФЬЮЭЛЗ"
        "UNIT_a119e7272d9449d2",  # ООО "КОМПАНИЯ "БИОЛОГИЯ"
        "UNIT_bd629be0c3064df7",  # ИП ПАНОВ ЕВГЕНИЙ ВИТАЛЬЕВИЧ
        "UNIT_949af365313a44ce",  # ООО "САРАТОВСКИЙ КОМБИНАТ ШКОЛЬНОГО ПИТАНИЯ"
    ]

    print("=" * 80)
    print("ТЕСТИРОВАНИЕ V5 ПРОМПТОВ")
    print("=" * 80)
    print()

    results_summary = []

    for i, unit_id in enumerate(test_cases, 1):
        print(f"\n{'─' * 80}")
        print(f"ТЕСТ {i}/{len(test_cases)}: {unit_id}")
        print(f"{'─' * 80}")

        # Получаем предыдущий результат
        prev_result = await get_previous_result(unit_id)
        if prev_result:
            prev_winner = prev_result.get("winners", [{}])[0]
            prev_inn = prev_winner.get("inn")
            prev_name = prev_winner.get("name", "N/A")
            print(f"БЫЛО (v4):")
            print(f"  Победитель: {prev_name[:60]}")
            print(f"  ИНН: {prev_inn}")
            print(f"  КПП: {prev_winner.get('kpp')}")
            print(f"  Confidence: {prev_winner.get('confidence')}")
        else:
            print(f"БЫЛО: Результат не найден")
            prev_inn = None
            prev_name = "N/A"

        # Обрабатываем с v5
        print(f"\nОБРАБОТКА с v5...")
        v5_result = await process_with_v5(unit_id, pm, llm_client)

        if "error" in v5_result:
            print(f"ОШИБКА: {v5_result['error']}")
            if "raw_response" in v5_result:
                print(f"Raw response: {v5_result['raw_response'][:500]}")
            continue

        winners = v5_result.get("winners", [])
        if not winners:
            print(f"\n⚠ Победитель не найден (winners пустой)")
            print(f"Winner found: {v5_result.get('winner_found')}")
            print(f"Raw response (первые 1000 символов):")
            print(v5_result.get("raw_response", "N/A")[:1000])
            results_summary.append({
                "unit_id": unit_id,
                "prev_name": prev_name,
                "v5_name": "N/A",
                "prev_inn": prev_inn,
                "v5_inn": None,
                "improved": False
            })
            continue

        v5_winner = winners[0]
        v5_inn = v5_winner.get("inn")
        v5_name = v5_winner.get("name", "N/A")

        print(f"\nСТАЛО (v5):")
        print(f"  Победитель: {v5_name[:60]}")
        print(f"  ИНН: {v5_inn}")
        print(f"  КПП: {v5_winner.get('kpp')}")
        print(f"  ОГРН: {v5_winner.get('ogrn')}")
        print(f"  Confidence: {v5_winner.get('confidence')}")
        print(f"  Reasoning: {v5_result.get('reasoning', 'N/A')[:300]}...")

        # Сравнение
        inn_improved = prev_inn is None and v5_inn is not None
        results_summary.append({
            "unit_id": unit_id,
            "prev_name": prev_name,
            "v5_name": v5_name,
            "prev_inn": prev_inn,
            "v5_inn": v5_inn,
            "improved": inn_improved
        })

        if inn_improved:
            print(f"\n✅ УЛУЧШЕНИЕ: ИНН извлечён!")
        elif v5_inn:
            print(f"\n✓ ИНН уже был извлечён")
        else:
            print(f"\n⚠ ИНН не извлечён (возможно отсутствует в документе)")

    # Закрываем LLM клиент
    await llm_client.close()

    # Итоговая статистика
    print(f"\n\n{'=' * 80}")
    print("ИТОГОВАЯ СТАТИСТИКА")
    print(f"{'=' * 80}")

    improved_count = sum(1 for r in results_summary if r["improved"])
    total_count = len(results_summary)

    print(f"\nВсего протестировано: {total_count}")
    print(f"Улучшено (ИНН извлечён): {improved_count}")
    print(f"Процент улучшения: {improved_count/total_count*100:.1f}%")

    print(f"\nДетали:")
    for r in results_summary:
        status = "✅ Улучшено" if r["improved"] else "⚠ Без изменений"
        print(f"  {r['unit_id']}: {status}")
        print(f"    ИНН: {r['prev_inn']} → {r['v5_inn']}")


if __name__ == "__main__":
    asyncio.run(main())
