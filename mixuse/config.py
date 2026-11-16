"""Файл настроек набора данных (YAML): пути к слоям, имена полей, правила зон, параметры, варианты.

Пути к слоям в файле настроек указываются относительно самого файла настроек.
"""
import os

import yaml

from .params import DEFAULTS, SCENARIOS
from .groups import load_group_table


class ConfigError(ValueError):
    """Ошибка в файле настроек — сообщение для пользователя."""


_PATH_KEYS = ('blocks', 'buildings', 'zones', 'services', 'service_groups')
_YES = {'да', 'yes', 'true', 'вкл', '1'}
_NO = {'нет', 'no', 'false', 'выкл', '0'}
_KNOWN_KEYS = {'name', 'title', 'mode', 'blocks', 'block_id_field', 'buildings', 'services', 'service_type_field', 'zones',
               'zone_field', 'zone_rules', 'block_zone_field', 'count_prefix', 'capacity_prefix', 'fields',
               'territory', 'params', 'scenarios', 'service_groups', 'capacity_field', 'output'}


def _yes_no(v, key):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in _YES:
        return True
    if s in _NO:
        return False
    raise ConfigError(f'Параметр {key}: ожидается «да» или «нет», получено «{v}».')


def merge_params(user):
    """Параметры по умолчанию (params.DEFAULTS) + переопределения из настроек набора данных."""
    P = dict(DEFAULTS)
    for k, v in (user or {}).items():
        if k not in DEFAULTS:
            raise ConfigError(f'Неизвестный параметр «{k}». Допустимые: {", ".join(DEFAULTS)}.')
        if isinstance(DEFAULTS[k], bool):
            P[k] = _yes_no(v, k)
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
    unknown = set(cfg) - _KNOWN_KEYS
    if unknown:
        raise ConfigError(f'Неизвестные разделы в настройках: {", ".join(sorted(unknown))}. '
                          f'Допустимые: {", ".join(sorted(_KNOWN_KEYS))}.')
    base = os.path.dirname(os.path.abspath(path))
    for k in _PATH_KEYS:
        v = cfg.get(k)
        if isinstance(v, (list, tuple)):
            cfg[k] = [os.path.normpath(os.path.join(base, x)) for x in v]
        elif v:
            cfg[k] = os.path.normpath(os.path.join(base, v))
    cfg.setdefault('name', os.path.splitext(os.path.basename(path))[0])
    cfg.setdefault('mode', 'layers')
    cfg['fields'] = cfg.get('fields') or {}
    cfg.setdefault('capacity_field', 'capacity')
    cfg['params'] = merge_params(cfg.get('params'))
    cfg['scenarios'] = cfg.get('scenarios') or dict(SCENARIOS)
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
    cfg['_path'] = os.path.abspath(path)
    return cfg


__all__ = ['load_config', 'merge_params', 'ConfigError']
