"""Связь ноутбука с пакетом: анкета шага 0 → настройки пакета; печать проверки данных.

Ноутбук `метод_сравнения_вариантов.ipynb` заполняет анкету по-русски (как в версии 4), а считает
функциями пакета. Здесь только перевод анкеты и печать — формул нет.
"""
import os

from .config import finish_config
from .params import defaults
from .checks import check_config
from .blocks import DataError

_KIT_KEYS = {'значение', 'источник', 'строка_СП', 'процент_застройки_ПЗЗ', 'этажность_ПЗЗ'}
_MODES = {'слои': 'layers', 'таблица': 'table', 'layers': 'layers', 'table': 'table'}


def config_from_form(form, P=None, SCN=None, group_table=None, base=None):
    """Анкета шага 0 (словарь ДАННЫЕ или пример из ПРИМЕРЫ) → настройки, как из configs/<код>.yaml.

    P — параметры ноутбука, SCN — варианты, group_table — путь к таблице групп;
    base — папка, от которой считаются пути анкеты (по умолчанию — текущая, то есть папка ноутбука).

    Правила расчёта — поле анкеты «правила»: 'v5' (по умолчанию) или 'v4' (режим совместимости с ноутбуком v4;
    тогда P и SCN ноутбука не применяются — берутся параметры и варианты v4 по умолчанию).
    Пользовательскими (ТЗ 5.1) считаются параметры, значение которых отличается от значения по умолчанию,
    и параметры из поля анкеты «параметры»; источник значения — поле «источники».
    """
    rules = form.get('правила', 'v5')
    if rules == 'v4':
        P, SCN = None, None
    else:
        base_P = defaults(rules)
        P = {k: v for k, v in (P or {}).items() if k not in base_P or v != base_P[k]}
        P.update(form.get('параметры') or {})
    src = dict(form.get('источники') or {})
    kit = form.get('кит') or {}                            # ТЗ 18.2: КИТ — значение и источник или строка табл. Б.1
    if set(kit) - _KIT_KEYS:
        raise DataError(f'кит: неизвестные поля {sorted(set(kit) - _KIT_KEYS)}; допустимо {sorted(_KIT_KEYS)}.')
    if kit and rules != 'v4':
        if kit.get('значение') is not None and kit.get('строка_СП'):
            raise DataError('кит: укажите либо значение КИТ из ПЗЗ (значение), либо строку таблицы Б.1 СП 42.13330.2016 '
                            '(строка_СП) — не оба сразу.')
        for k_form, k in (('значение', 'kit'), ('строка_СП', 'kit_sp_row'),
                          ('процент_застройки_ПЗЗ', 'pzz_build_share'), ('этажность_ПЗЗ', 'pzz_max_storeys')):
            if kit.get(k_form) is not None:
                P[k] = kit[k_form]
        if kit.get('источник'):
            if kit.get('значение') is not None:
                P['kit_source'] = kit['источник']
            elif kit.get('строка_СП'):
                src['kit_sp_row'] = kit['источник']
    if rules != 'v4':
        note = form.get('ограничения_территории')        # ТЗ 18.2а: в отчёт о данных и в вывод для вариантов с жильём
        if note:
            P['data_note'] = P['housing_note'] = str(note).strip()
        st = form.get('статистика') or {}                  # ТЗ 18.2а: работники по статистике (проверка 4.8.4)
        if set(st) - {'работников', 'источник'}:
            raise DataError(f'статистика: неизвестные поля {sorted(set(st) - {"работников", "источник"})}; '
                            'допустимо «работников» (число) и «источник».')
        if st.get('работников') is not None:
            P['stat_jobs'] = st['работников']
            if st.get('источник'):
                src['stat_jobs'] = st['источник']
    ex = form.get('точный_расчёт') or {}                   # ТЗ 18.2: точный расчёт школ и садов (blocksnet)
    if set(ex) - {'включить', 'файл_OSM'}:
        raise DataError(f'точный_расчёт: неизвестные поля {sorted(set(ex) - {"включить", "файл_OSM"})}; '
                        'допустимо «включить» (True / False) и «файл_OSM» (путь или ссылка).')
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
        'rules': rules,
        'blocks': q.get('файл'),
        'block_id_field': q.get('поле_номера'),
        'territory': list(form.get('территория') or []),
        'params': dict(P or {}),
        'param_sources': src,
        'service_groups': group_table,
    }
    if SCN:
        cfg['scenarios'] = dict(SCN)
    if ex:
        cfg['provision'] = {'exact': bool(ex.get('включить')), 'osm_file': ex.get('файл_OSM')}
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
            'block_zone_field': z.get('поле_в_кварталах'),   # зона — поле слоя кварталов (Гатчина), если слоя зон нет
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


def check_data(cfg):
    """Шаг 0б целиком (ТЗ 18.3): проверка анкеты и слоёв (print_check), затем слои читаются, таблица кварталов
    строится и печатается отчёт о данных простыми словами — доля зданий без этажности, типы сервисов не из таблицы
    групп, школы и сады без мест, производственные кварталы без точек предприятий, кварталы с П, КИТ и его источник.
    Ошибки печатаются строкой «✕ что не так и как исправить» и останавливают расчёт. Возвращает (слои, город)."""
    from .blocks import load_layers, build_table
    from .data_report import data_report
    print_check(cfg)
    P = cfg['params']
    if cfg['rules'] == 'v5':
        from .compare import kit_value
        kit_value(P)                                   # КИТ не задан — ошибка сразу, до расчёта
    L = load_layers(cfg, cfg['_groups'])
    city = build_table(L, cfg, P, cfg['_groups'])
    lines, warns = data_report(city, cfg, P)
    print('Что нашлось в данных:')
    for m in lines:
        if m.strip():
            print(('      ' if m.startswith(' ') else '  ✓ ') + m.strip())
    for m in warns:
        print('  ! ' + m)
    print()
    return L, city
