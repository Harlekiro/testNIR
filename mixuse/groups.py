"""Группы функций: справочник «тип сервиса → группа», группа нежилого здания.

Обозначения: Ж — жильё; К — торговля и бытовое обслуживание; ОД — общественно-деловая;
П — производство и склады; X — нежилое здание без установленной функции.
"""
import csv
import os

FUNCS = ['К', 'ОД', 'П']

# Внутренние имена групп — как в ноутбуке. В таблице групп допустимы и имена из ТЗ.
_ALIASES = {'детский_сад': 'сад', 'детский сад': 'сад', 'нет': 'не используется', '': 'не используется'}
KNOWN_GROUPS = {'К', 'ОД', 'П', 'школа', 'сад', 'метро', 'остановка', 'не используется'}

DEFAULT_TABLE = os.path.join(os.path.dirname(__file__), 'data', 'таблица_групп_сервисов.csv')


def load_service_groups(path=None):
    """Читает таблицу групп сервисов (CSV: тип_сервиса, группа, код_ВРИ, примечание).

    Возвращает словарь {тип сервиса: группа}. Если путь не задан — встроенная таблица,
    повторяющая справочник ноутбука.
    """
    path = path or DEFAULT_TABLE
    out = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f'Таблица групп сервисов пуста: {path}')
    cols = rows[0].keys()
    tcol = next((c for c in ('тип_сервиса', 'service_type', 'тип') if c in cols), None)
    gcol = next((c for c in ('группа', 'group') if c in cols), None)
    if not tcol or not gcol:
        raise ValueError(f'В таблице групп {path} нужны столбцы «тип_сервиса» и «группа»; найдены: {", ".join(cols)}')
    for i, r in enumerate(rows, 2):
        t = (r[tcol] or '').strip()
        if not t:
            continue
        g = (r[gcol] or '').strip()
        g = _ALIASES.get(g, g)
        if g not in KNOWN_GROUPS:
            raise ValueError(f'Таблица групп {path}, строка {i}: неизвестная группа «{r[gcol]}» у типа «{t}». '
                             f'Допустимо: К, ОД, П, школа, детский_сад, метро, остановка, нет.')
        out[t] = g
    return out


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
