"""Связь ноутбука с пакетом: анкета шага 0 → настройки пакета; печать проверки данных.

Ноутбук `метод_сравнения_вариантов.ipynb` заполняет анкету по-русски (как в версии 4), а считает
функциями пакета. Здесь только перевод анкеты и печать — формул нет.
"""
import os

from .config import finish_config
from .checks import check_config
from .blocks import DataError

_MODES = {'слои': 'layers', 'таблица': 'table', 'layers': 'layers', 'table': 'table'}


def config_from_form(form, P=None, SCN=None, group_table=None, base=None):
    """Анкета шага 0 (словарь ДАННЫЕ или пример из ПРИМЕРЫ) → настройки, как из configs/<код>.yaml.

    P — параметры ноутбука, SCN — варианты, group_table — путь к таблице групп;
    base — папка, от которой считаются пути анкеты (по умолчанию — текущая, то есть папка ноутбука).
    """
    q = form.get('кварталы') or {}
    b = form.get('здания') or {}
    s = form.get('сервисы') or {}
    z = form.get('зоны') or {}
    tb = form.get('готовая_таблица') or {}
    mode = _MODES.get(form.get('режим', 'слои'))
    if mode is None:
        raise DataError(f'режим: «{form.get("режим")}» — допустимо «слои» или «таблица».')
    cfg = {
        'name': form.get('код') or 'город',
        'title': form.get('название') or form.get('код') or 'город',
        'mode': mode,
        'blocks': q.get('файл'),
        'block_id_field': q.get('поле_номера'),
        'territory': list(form.get('территория') or []),
        'params': dict(P or {}),
        'service_groups': group_table,
    }
    if SCN:
        cfg['scenarios'] = dict(SCN)
    if mode == 'layers':
        cfg.update({
            'buildings': b.get('файл'),
            'fields': {'is_living': b.get('поле_жилое'), 'storeys': b.get('поле_этажность'),
                       'footprint': b.get('поле_площадь_застройки'), 'living_area': b.get('поле_жилая_площадь'),
                       'population': b.get('поле_жители')},
            'services': s.get('файл'),
            'service_type_field': s.get('поле_типа'),
            'capacity_field': s.get('поле_мест'),
            'zones': z.get('файл'),
            'zone_field': z.get('поле_кода'),
            'zone_rules': [list(r) for r in (z.get('правила') or [])],
        })
    else:
        cfg.update({
            'fields': {'population': tb.get('поле_жители'), 'living_area': tb.get('поле_жилая_площадь'),
                       'non_living_area': tb.get('поле_нежилая_площадь')},
            'block_zone_field': tb.get('поле_зоны'),
            'count_prefix': tb.get('префикс_числа', 'count_'),
            'capacity_prefix': tb.get('префикс_мест', 'capacity_'),
            'zone_rules': [list(r) for r in (tb.get('правила') or [])],
        })
    # пустые значения анкеты (None) — как отсутствие строки в файле настроек
    cfg = {k: v for k, v in cfg.items() if v is not None}
    return finish_config(cfg, os.path.abspath(base or os.getcwd()), 'анкета ноутбука')


def print_check(cfg):
    """Шаг 0б. Печатает проверку данных: ✓ — сведения, ! — предупреждения, ✕ — ошибки.
    При ошибках останавливает ноутбук с понятным сообщением."""
    errors, warns, info = check_config(cfg)
    for m in info:
        print('  ✓ ' + m)
    for m in warns:
        print('  ! ' + m)
    for m in errors:
        print('  ✕ ' + m)
    print()
    if errors:
        raise DataError(f'Ошибок: {len(errors)}. Исправьте анкету в шаге 0 или слои и запустите снова. '
                        "Чтобы проверить ноутбук на примере, поставьте ПРИМЕР = 'spb'.")
    print(f'Проверка пройдена. Предупреждений: {len(warns)}. Можно запускать расчёт.')
    return warns
