"""Группы функций: таблица «тип сервиса → группа», группа нежилого здания.

Обозначения: Ж — жильё; К — торговля и бытовое обслуживание; ОД — общественно-деловая;
П — производство и склады; X — нежилое здание без установленной функции.
Группа сервиса задана в таблице по коду ВРИ: К — 3.3, 4.2, 4.3, 4.4, 4.6;
ОД — 3.2.3, 3.5.2, 3.6.1, 3.8, 4.1, 4.5, 4.7; П — 6.x.
"""
import os

import pandas as pd

FUNCS = ['К', 'ОД', 'П']
GROUPS_ALLOWED = ['К', 'ОД', 'П', 'школа', 'детский_сад', 'метро', 'остановка', 'нет']
NOT_IN_TABLE = 'нет в таблице'

# таблица групп лежит в корне проекта (её же читает ноутбук)
DEFAULT_TABLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'таблица_групп_сервисов.csv')


def load_group_table(path=None):
    """Таблица групп (CSV, открывается в Excel; разделитель «;» или «,», UTF-8 с BOM).

    Нужны столбцы «тип» и «группа». Ключ словаря — значение «тип», а также теги из столбца
    «тег_OSM» (второй способ найти тип, например amenity=school). Как в ноутбуке.
    """
    path = path or DEFAULT_TABLE
    if not os.path.exists(path):
        raise FileNotFoundError(f'Нет таблицы групп сервисов: {path}.')
    t = pd.read_csv(path, sep=None, engine='python', encoding='utf-8-sig', dtype=str).fillna('')
    t.columns = [c.strip() for c in t.columns]
    miss = {'тип', 'группа'} - set(t.columns)
    if miss:
        raise ValueError(f'В таблице групп {path} нет столбцов: {", ".join(sorted(miss))}. Нужны столбцы «тип» и «группа».')
    bad = t[~t['группа'].str.strip().isin(GROUPS_ALLOWED)]
    if len(bad):
        raise ValueError(f'В таблице групп {path} неизвестные группы: '
                         + ', '.join(f'{r.тип} → «{r.группа}»' for r in bad.itertuples())
                         + '. Допустимо: ' + ', '.join(GROUPS_ALLOWED))
    groups = {}
    for r in t.itertuples():
        groups[r.тип.strip()] = r.группа.strip()
    for r in t.itertuples():       # теги OSM — второй способ найти тип
        for tag in str(getattr(r, 'тег_OSM', '')).split(','):
            if tag.strip():
                groups.setdefault(tag.strip(), r.группа.strip())
    return groups


def zone_group(zone, rules):
    """Группа нежилого здания без сервисов внутри — по зоне квартала (первое совпавшее начало кода).

    rules — список пар (начало кода зоны, группа), например [('ТП', 'П'), ('ТД', 'ОД')]; иначе X.
    """
    z = str(zone or '')
    for prefix, grp in rules:
        if z.startswith(prefix):
            return grp
    return 'X'


def building_group(found, zone, rules):
    """Группа нежилого здания (метод, шаг 4).

    1. есть сервисы К, ОД, П внутри контура → одна группа с приоритетом П → ОД → К;
    2. нет сервисов → по коду зоны квартала (zone_group);
    3. иначе X.
    found — множество групп сервисов, найденных внутри контура.
    """
    return 'П' if 'П' in found else 'ОД' if 'ОД' in found else 'К' if 'К' in found else zone_group(zone, rules)


def load_norms(path=None):
    """Нормы площади на работника по типам сервисов (столбец «норма_м2_на_работника» таблицы групп, раздел 6).

    Возвращает словарь «тип → м² на работника». Типы без нормы в словарь не входят.
    """
    path = path or DEFAULT_TABLE
    t = pd.read_csv(path, sep=None, engine='python', encoding='utf-8-sig', dtype=str).fillna('')
    t.columns = [c.strip() for c in t.columns]
    if 'норма_м2_на_работника' not in t:
        return {}
    v = pd.to_numeric(t['норма_м2_на_работника'].str.replace(',', '.'), errors='coerce')
    return {ty.strip(): float(n) for ty, n in zip(t['тип'], v) if n > 0}


def main_norm(types, norms, fallback):
    """Норма здания по типам сервисов в его контуре (правило 4.4.3).

    Берётся норма типа, точек которого в здании больше; при равенстве — большая норма.
    Тип без нормы → fallback(тип) — норма группы для вариантов (4.6.4).
    Возвращает (норма, число типов без нормы среди учтённых).
    """
    cnt = {}
    for ty in types:
        cnt[ty] = cnt.get(ty, 0) + 1
    top = max(cnt.values())
    leaders = [ty for ty, c in cnt.items() if c == top]
    vals = [(norms[ty], False) if ty in norms else (fallback(ty), True) for ty in leaders]
    best = max(vals, key=lambda x: x[0])
    return best[0], sum(1 for _, no in vals if no)
