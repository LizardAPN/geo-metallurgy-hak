"""Промпты для structured extraction сущностей и связей."""

EXTRACTION_SYSTEM_PROMPT = """Ты — эксперт по извлечению знаний из научных документов
горно-металлургической отрасли. Извлекай сущности и связи строго по онтологии.

Типы сущностей: Material, Process, Equipment, Property, Experiment,
Publication, Expert, Facility.

Типы связей: uses_material, operates_at_condition, produces_output,
described_in, validated_by, contradicts, authored_by, conducted_at,
uses_equipment, relates_to.

Каждый факт должен содержать source_doc, confidence (0-1), geography, year.
Числовые ограничения — всегда с единицами измерения как в источнике.
Ответ — только валидный JSON."""

# TODO: few-shot примеры из глоссария корпуса (обессоливание, выщелачивание, флотация)
EXTRACTION_FEW_SHOT: list[dict[str, str]] = [
    # TODO: добавить 2-3 примера RU/EN из справочников организаторов
    {
        "input": "При содержании сульфатов 250 мг/л применялся обратный осмос.",
        "output": '{"entities": [...], "relations": [...]}',
    },
]

EXTRACTION_USER_TEMPLATE = """Документ: {doc_id}
Текст:
{text}

Извлеки entities и relations в JSON по схеме онтологии."""
