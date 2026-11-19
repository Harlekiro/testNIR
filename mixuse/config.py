"""Файл настроек набора данных (YAML): пути к слоям, имена полей, правила зон, параметры, варианты.

Пути к слоям в файле настроек указываются относительно самого файла настроек.
"""
import os

import yaml

from .params import DEFAULTS, SCENARIOS, SCENARIOS_V5, defaults, TEXT_PARAMS, SP42_B1
from .groups import load_group_table


class ConfigError(ValueError):
    """Ошибка в файле настроек — сообщение для пользователя."""


_PATH_KEYS = ('blocks', 'buildings', 'zones', 'services', 'service_groups')
_YES = {'да', 'yes', 'true', 'вкл', '1'}
_NO = {'нет', 'no', 'false', 'выкл', '0'}
_KNOWN_KEYS = {'name', 'title', 'mode', 'blocks', 'block_id_field', 'buildings', 'services', 'service_type_field', 'zones',
               'zone_field', 'zone_rules', 'block_zone_field', 'count_prefix', 'capacity_prefix', 'fields',
               'territory', 'params', 'scenarios', 'service_groups', 'capacity_field', 'output', 'rules', 'param_sources', 'explore'}
RULES = ('v4', 'v5')   # правила расчёта: v4 — совместимость с ноутбуком v4; v5 — раздел 4 ТЗ (по умолчанию)


def _yes_no(v, key):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in _YES:
        return True
    if s in _NO:
        return False
    raise ConfigError(f'Параметр {key}: ожидается «да» или «нет», получено «{v}».')


def merge_params(user, rules='v4'):
    """Параметры по умолчанию для правил v4 или v5 (params.py) + переопределения из настроек набора данных."""
    base = defaults(rules)
    P = dict(base)
    for k, v in (user or {}).items():
        if k not in base:
            raise ConfigError(f'Неизвестный параметр «{k}» для правил {rules}. Допустимые: {", ".join(base)}.')
        d = base[k]
        if k in TEXT_PARAMS:                   # строковые параметры
            P[k] = None if v is None else str(v).strip()
            if k == 'kit_sp_row' and P[k] is not None and P[k] not in SP42_B1:
                raise ConfigError(f'kit_sp_row: «{v}» — нет такой строки табл. Б.1 СП 42.13330.2016. '
                                  f'Допустимо: {", ".join(SP42_B1)}.')
            continue
        if isinstance(d, bool):
            P[k] = _yes_no(v, k)
        elif isinstance(d, dict):              # нормы по типам: можно переопределить часть
            if not isinstance(v, dict):
                raise ConfigError(f'Параметр {k}: ожидается список «тип: число».')
            P[k] = dict(d)
            for kk, vv in v.items():
                try:
                    P[k][str(kk)] = float(vv)
                except (TypeError, ValueError):
                    raise ConfigError(f'Параметр {k}.{kk}: ожидается число, получено «{vv}».')
        else:
            try:
                P[k] = float(v) if isinstance(v, str) else v
            except ValueError:
                raise ConfigError(f'Параметр {k}: ожидается число, получено «{v}».')
    return P


def _rules(raw):
    if not raw:
        return []
    items = raw.items() if isinstance(raw, dict) else raw
    out = []
    for it in items:
        if isinstance(it, dict):
            it = next(iter(it.items()))
        if len(it) != 2:
            raise ConfigError(f'zone_rules: каждое правило — пара «начало кода зоны: группа», получено {it!r}.')
        prefix, grp = str(it[0]), str(it[1])
        if grp not in ('К', 'ОД', 'П', 'X'):
            raise ConfigError(f'zone_rules: группа «{grp}» у правила «{prefix}» — допустимо К, ОД, П, X.')
        out.append((prefix, grp))
    return out


def load_config(path):
    """Читает файл настроек, проверяет ключи, подставляет параметры по умолчанию.

    Возвращает словарь с абсолютными путями, параметрами `params`, вариантами `scenarios`
    и таблицей групп `_groups`.
    """
    if not os.path.exists(path):
        raise ConfigError(f'Файл настроек не найден: {path}')
    with open(path, encoding='utf-8') as f:
        try:
            cfg = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f'Ошибка в записи файла настроек {path}: {e}')
    return finish_config(cfg, os.path.dirname(os.path.abspath(path)), os.path.abspath(path))


def finish_config(cfg, base, source):
    """Общая часть для файла настроек и анкеты ноутбука: проверка ключей, абсолютные пути
    (относительно папки base), параметры по умолчанию, варианты, таблица групп.
    source — откуда взяты настройки (путь к файлу или «анкета ноутбука»), для сообщений."""
    unknown = set(cfg) - _KNOWN_KEYS
    if unknown:
        raise ConfigError(f'Неизвестные разделы в настройках: {", ".join(sorted(unknown))}. '
                          f'Допустимые: {", ".join(sorted(_KNOWN_KEYS))}.')
    for k in _PATH_KEYS:
        v = cfg.get(k)
        if isinstance(v, (list, tuple)):
            cfg[k] = [os.path.normpath(os.path.join(base, x)) for x in v]
        elif v:
            cfg[k] = os.path.normpath(os.path.join(base, v))
    cfg.setdefault('name', os.path.splitext(os.path.basename(source))[0])
    cfg.setdefault('mode', 'layers')
    cfg['rules'] = str(cfg.get('rules') or 'v5').strip()
    if cfg['rules'] not in RULES:
        raise ConfigError(f'rules: «{cfg["rules"]}» — допустимо v4 (совместимость с ноутбуком v4) или v5.')
    cfg['fields'] = cfg.get('fields') or {}
    cfg.setdefault('capacity_field', 'capacity')
    cfg['_user_params'] = sorted((cfg.get('params') or {}).keys())    # заданы пользователем (ТЗ 5.1)
    cfg['params'] = merge_params(cfg.get('params'), cfg['rules'])
    src = cfg.get('param_sources') or {}
    if not isinstance(src, dict) or set(src) - set(cfg['params']):
        raise ConfigError('param_sources: источники значений параметров в виде «параметр: источник»; '
                          f'неизвестные параметры: {", ".join(sorted(set(src) - set(cfg["params"]))) if isinstance(src, dict) else src}.')
    cfg['param_sources'] = {k: str(v) for k, v in src.items()}
    cfg['scenarios'] = cfg.get('scenarios') or dict(SCENARIOS_V5 if cfg['rules'] == 'v5' else SCENARIOS)
    cfg['zone_rules'] = _rules(cfg.get('zone_rules'))
    terr = cfg.get('territory') or []
    try:
        cfg['territory'] = [int(x) for x in terr]
    except (TypeError, ValueError):
        raise ConfigError(f'territory: нужен список номеров кварталов, например [12, 13], получено {terr!r}.')
    try:
        cfg['_groups'] = load_group_table(cfg.get('service_groups'))
    except (OSError, ValueError) as e:
        raise ConfigError(str(e))
    cfg['_path'] = source
    return cfg


__all__ = ['load_config', 'finish_config', 'merge_params', 'ConfigError']


def param_origins(cfg, info=None):
    """Откуда взято значение каждого параметра (ТЗ 5.1): «пользователь» (с источником из param_sources),
    «свод правил» (сейчас только КИТ — СП 42.13330.2016, 4.6.2), «по умолчанию» (со статусом из таблицы раздела 5).
    КИТ окружения по данным — только для сравнения, сюда не входит.
    info — сводка compare (выбранный КИТ и его источник). Возвращает список (параметр, значение, откуда)."""
    from .params import PARAM_STATUS
    user, src = set(cfg.get('_user_params', [])), cfg.get('param_sources', {})
    rows = []
    for k, v in cfg['params'].items():
        if k == 'kit' and info and info.get('КИТ: откуда'):          # 4.6.2: пользователь или свод правил
            v, how = info['КИТ варианта'], info['КИТ: откуда']
        elif k == 'kit_source' and v:
            how = 'пользователь'
        elif k in user:
            how = 'пользователь' + (f': {src[k]}' if k in src else ' (источник не указан)')
        else:
            how = 'по умолчанию' + (f' — {PARAM_STATUS[k]}' if k in PARAM_STATUS else '')
        rows.append((k, v, how))
    return rows
