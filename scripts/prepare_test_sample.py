#!/usr/bin/env python3
"""
Pick 5 PDF + 5 DOCX from data/corpus/ and copy to data/test_run/.
Tries to cover different categories (Доклады, Журналы, Обзоры, Статьи).
Safe to re-run — skips files already present.
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CORPUS   = Path("data/corpus")
TEST_DIR = Path("data/test_run")

SAMPLE = [
    # PDF — все до 1 МБ, разные категории
    "Доклады/Тяпкина ПА_Пермь_Зимняя школа.pdf",
    "Обзоры/Самовозгорание сульфидной пыли.pdf",
    "Обзоры/Мышьяк в Cu конц.pdf",
    "Обзоры/ОИ - 2 - 2016  Извлечение благородных металлов из шламов и шлаков металлургического производсва.pdf",
    "Обзоры/Медный купорос.pdf",
    "Обзоры/Закладочные комплексы 2017.pdf",
    "Обзоры/Sheba's Ridge.pdf",
    "Обзоры/BCL 2011.pdf",
    "Обзоры/Справка. Методы конц-я SO2.pdf",
    "Обзоры/Проблемы выделения элементарной серы.pdf",
    "Обзоры/Bindura_2010.pdf",
    "Обзоры/Tati Nkomati Cu conc.pdf",
    "Обзоры/Cu 2011.pdf",
    "Обзоры/NPI_2013.pdf",
    "Обзоры/ТИ-5-2017. Кучное выщелачивание в условиях холодного климата.pdf",
    "Обзоры/Соли железа.pdf",
    "Обзоры/Cunico Resources.pdf",
    "Обзоры/Смеш_гидроксиды.pdf",
    "Обзоры/Предприятие Mount Keith.pdf",
    "Обзоры/ПРОБЛЕМЫ_Гидромет.pdf",
    # DOCX — Обзоры
    "Обзоры/Методы очистки шахтных вод.docx",
    "Обзоры/Переработка Cu-Ni шлаков (2024).docx",
    "Обзоры/Хлорное выщелачивание ОИП 02-2024.docx",
    "Обзоры/ОИП-06-2022 Технологии производства лития из рудного сырья.docx",
    "Обзоры/Автоматизация в горной отрасли (2019).docx",
    "Обзоры/Закладка_май2018.docx",
    "Обзоры/Очистка от Fe 2020.docx",
    "Обзоры/Cerro Matoso.docx",
    "Обзоры/Карб Fe.docx",
    "Обзоры/Зарубежный и отечественный опыт флотации шлаков медеплавильного производства.docx",
    "Обзоры/Куба_ПунтаГорда_2018.docx",
    "Обзоры/Металлургический комплекс Уэльва.docx",
    "Обзоры/Вдувание дисперсного сырья в ванну расплава.docx",
    # DOCX — Статьи
    "Статьи/1 Моделирование тектонических нарушений с применением связей конечной жёсткости с интеграцией в CAE Fidesys (002).docx",
    "Статьи/44 ИССЛЕДОВАНИЕ ПРОЦЕССА ГРАНУЛЯЦИИ МЕДНО-НИКЕЛЕВЫХ ШТЕЙНОВ.docx",
    "Статьи/6 Влияние различных факторов на окисление железа, часть 2 v3.docx",
    "Статьи/39 ИССЛЕДОВАНИЕ ПЕРСПЕКТИВНЫХ СОСТАВОВ ДЛЯ ОТЛИВКИ МЕДНЫХ АНОДОВ.docx",
    "Статьи/45 Статья. Магнитная сепарация. Часть 1.docx",
    "Статьи/54 Поведение селена и теллура при электроэкстракции меди.docx",
    "Статьи/7 Хранение САМ_версия 25.05.20.docx",
]

TEST_DIR.mkdir(exist_ok=True)

copied = 0
skipped = 0
missing = 0

for rel in SAMPLE:
    src = CORPUS / rel
    dst = TEST_DIR / src.name
    if not src.exists():
        print(f"  MISSING  {src}")
        missing += 1
        continue
    if dst.exists():
        print(f"  exists   {src.name}")
        skipped += 1
        continue
    shutil.copy2(src, dst)
    print(f"  copied   {src.name}")
    copied += 1

print(f"\n{TEST_DIR}: {copied} copied, {skipped} already there, {missing} missing")
print(f"Total files: {len(list(TEST_DIR.iterdir()))}")
