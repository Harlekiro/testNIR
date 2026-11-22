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


DEFAULT_ZONE_DICT = os.path.join(os.path.dirname(DEFAULT_TABLE), 'zone_dictionary.csv')


def load_zone_dictionary(path=None):
    """Словарь кодов зон (ТЗ 18.5): zone_dictionary.csv в корне проекта, столбцы «значение; группа; схема; сравнение».
    сравнение: «начало» — код зоны начинается со значения (коды ПЗЗ), «вхождение» — значение встречается в коде (слова).
    Регистр не учитывается. Возвращает список строк (значение, группа, схема, сравнение)."""
    path = path or DEFAULT_ZONE_DICT
    if not os.path.exists(path):
        raise FileNotFoundError(f'Нет словаря зон: {path}.')
    t = pd.read_csv(path, sep=None, engine='python', encoding='utf-8-sig', dtype=str).fillna('')
    t.columns = [c.strip() for c in t.columns]
    miss = {'значение', 'группа', 'схема', 'сравнение'} - set(t.columns)
    if miss:
        raise ValueError(f'В словаре зон {path} нет столбцов: {", ".join(sorted(miss))}.')
    rows = []
    for r in t.itertuples():
        v, g, how = r.значение.strip(), r.группа.strip(), r.сравнение.strip()
        if not v:
            continue
        if g not in ('П', 'ОД') or how not in ('начало', 'вхождение'):
            raise ValueError(f'Словарь зон {path}, строка «{v}»: группа — П или ОД, сравнение — «начало» или «вхождение».')
        rows.append((v, g, r.схема.strip(), how))
    return rows


def zone_match(zone, rules, zdict=None):
    """Группа зоны квартала и откуда она взята. Возвращает (группа, откуда, конфликт).

    rules — ручные правила (начало кода → группа, как раньше); zdict — словарь зон (ТЗ 18.5) или None.
    1) ручное правило — первое совпавшее начало кода; 2) словарь — все подходящие строки; если подходят и П, и ОД —
    конфликт, побеждает П; 3) иначе X («прочее»)."""
    z = '' if zone is None or (isinstance(zone, float) and zone != zone) else str(zone)
    for prefix, grp in rules:
        if z.startswith(prefix):
            return grp, f'правило анкеты «{prefix}»', False
    if not zdict or not z:
        return 'X', None, False
    zl = z.lower()
    hits = [r for r in zdict if (zl.startswith(r[0].lower()) if r[3] == 'начало' else r[0].lower() in zl)]
    if not hits:
        return 'X', None, False
    groups = {r[1] for r in hits}
    grp = 'П' if 'П' in groups else 'ОД'
    r = next(h for h in hits if h[1] == grp)
    return grp, f'словарь: «{r[0]}» ({r[2]})', len(groups) > 1


def zone_group(zone, rules, zdict=None):
    """Группа нежилого здания без сервисов внутри — по зоне квартала (zone_match): К, ОД, П или X."""
    return zone_match(zone, rules, zdict)[0]


def building_group(found, zone, rules, zdict=None):
    """Группа нежилого здания (метод, шаг 4).

    1. есть сервисы К, ОД, П внутри контура → одна группа с приоритетом П → ОД → К;
    2. нет сервисов → по коду зоны квартала (zone_group);
    3. иначе X.
    found — множество групп сервисов, найденных внутри контура.
    """
    return 'П' if 'П' in found else 'ОД' if 'ОД' in found else 'К' if 'К' in found else zone_group(zone, rules, zdict)


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
