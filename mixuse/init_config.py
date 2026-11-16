"""Команда init: составляет черновик файла настроек по папке с пользовательскими данными.

Программа смотрит на имена файлов и полей и предлагает соответствие. Всё, что угадано,
помечается «ПРОВЕРЬТЕ» — решение остаётся за пользователем.
"""
import os
import re

import pandas as pd

from .geometry import read_layer, describe_crs
from .groups import load_group_table
from .params import DEFAULTS, SCENARIOS, PARAM_HELP

_EXT = ('.geojson', '.gpkg', '.json')
_NAME_HINTS = {
    'blocks': r'block|квартал',
    'buildings': r'build|здани|дом',
    'zones': r'zone|зон|landuse|land_use|землепольз|functional',
}
_SERVICE_DIR = r'serv|ервис|poi|объект'
_FIELD_HINTS = {
    'footprint': ['building_area', 'footprint_area', 'footprint', 'area_footprint', 'площадь_застройки'],
    'is_living': ['is_living', 'living', 'residential', 'жилое', 'жилой'],
    'storeys': ['storeys_count', 'number_of_floors', 'storeys', 'floors', 'levels', 'building:levels', 'этажность', 'этажей'],
    'living_area': ['living_area', 'жилая_площадь'],
    'population': ['population_balanced', 'population', 'жители', 'население'],
}
_ID_HINTS = ['block_id', 'id', 'fid', 'номер', 'квартал']
_ZONE_FIELD_HINTS = ['functional_zone', 'zone', 'код_зоны', 'код', 'code', 'Зона', 'зона', 'land_use', 'landuse', 'Тип']


def _layers_in(folder):
    return [os.path.join(folder, f) for f in sorted(os.listdir(folder))
            if f.lower().endswith(_EXT) and os.path.isfile(os.path.join(folder, f))]


def _peek(path):
    try:
        df, geoms, geo = read_layer(path)
    except Exception as e:                          # файл не читается — сообщим в черновике
        return None, str(e)
    kinds = pd.Series([g[0] for g in geoms], dtype=object).value_counts()
    return {'df': df, 'kind': kinds.index[0] if len(kinds) else None, 'n': len(df),
            'crs': describe_crs(df.attrs.get('epsg'), geo)}, None


def _pick(cands, columns):
    low = {str(c).lower(): c for c in columns}
    for c in cands:
        if c.lower() in low:
            return low[c.lower()]
    return None


def make_config(data_dir, name=None, out=None):
    """Возвращает (путь файла настроек, текст YAML)."""
    data_dir = os.path.abspath(data_dir)
    if not os.path.isdir(data_dir):
        raise FileNotFoundError(f'Папка с данными не найдена: {data_dir}')
    # если внутри одна вложенная папка (так бывает после распаковки архива) — заходим в неё
    inner = [d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d))]
    if not _layers_in(data_dir) and len(inner) == 1:
        data_dir = os.path.join(data_dir, inner[0])
    code = name or re.sub(r'[^0-9A-Za-z_]+', '_', os.path.basename(data_dir)).strip('_').lower() or 'mydata'
    out = os.path.abspath(out or os.path.join('configs', f'{code}.yaml'))
    base = os.path.dirname(out)
    def rel(p, start=base):
        try:
            return os.path.relpath(p, start).replace('\\', '/')
        except ValueError:                     # другой диск (Windows) — путь целиком
            return os.path.abspath(p).replace('\\', '/')

    files = {p: _peek(p) for p in _layers_in(data_dir)}
    found, notes = {}, []
    for key, rx in _NAME_HINTS.items():
        for p, (meta, err) in files.items():
            if meta and meta['kind'] == 'poly' and re.search(rx, os.path.basename(p), re.I) and p not in found.values():
                found[key] = p
                break
    subdirs = [os.path.join(data_dir, d) for d in sorted(os.listdir(data_dir)) if os.path.isdir(os.path.join(data_dir, d))]
    svc = [d for d in subdirs if re.search(_SERVICE_DIR, os.path.basename(d), re.I) and _layers_in(d)]
    if not svc:
        withfiles = sorted([d for d in subdirs if _layers_in(d)], key=lambda d: -len(_layers_in(d)))
        svc = withfiles[:1]
    unused_dirs = [d for d in subdirs if d not in svc]
    unused_files = [p for p in files if p not in found.values()]

    groups = load_group_table()
    L = []
    w = L.append
    w(f'# Настройки набора данных «{code}». Черновик составлен командой init по папке:')
    w(f'#   {data_dir}')
    w('# Пути указаны относительно этого файла. Строки с пометкой «ПРОВЕРЬТЕ» программа угадала —')
    w('# проверьте их и запустите:  python -m mixuse check ' + rel(out, os.getcwd()))
    w('')
    w(f'name: {code}')
    w('mode: layers            # layers — отдельные слои; table — готовая таблица кварталов (как у Гатчины)')
    w('')

    def layer_line(key, label):
        p = found.get(key)
        if not p:
            w(f'{key}:                  # ПРОВЕРЬТЕ: слой «{label}» не найден по имени файла — укажите путь')
            return None
        meta = files[p][0]
        w(f'{key}: {rel(p)}   # ПРОВЕРЬТЕ: {label}; {meta["n"]} объектов, {meta["crs"]}')
        return meta

    m = layer_line('blocks', 'кварталы')
    idf = _pick(_ID_HINTS, m['df'].columns) if m else None
    if idf and m['df'][idf].is_unique:
        w(f'block_id_field: {idf}   # ПРОВЕРЬТЕ: поле номера квартала')
    else:
        w('block_id_field:          # поля номера нет — номер квартала = порядок в файле (0, 1, 2…)')
    w('')
    m = layer_line('buildings', 'здания')
    cols = list(m['df'].columns) if m else []
    w('fields:                  # имена полей в слое зданий' + (f'; есть поля: {", ".join(map(str, cols))}' if cols else ''))
    for key, label in [('footprint', 'площадь застройки, м² (нет — по контуру)'), ('is_living', 'жилое: 1/0 или да/нет'),
                       ('storeys', 'этажность (нет — 1 этаж)'), ('living_area', 'жилая площадь, м² (нет — A·k_liv)'),
                       ('population', 'жители (нет — жилая площадь ÷ q)')]:
        fld = _pick(_FIELD_HINTS[key], cols)
        w(f'  {key}: {fld if fld else ""}' + ' ' * max(1, 22 - len(key) - len(fld or '')) + f'# {"ПРОВЕРЬТЕ: " if fld else "НЕ НАЙДЕНО: "}{label}')
    w('')
    if svc:
        w('services:               # папка «один файл = один тип сервиса»; тип = имя файла')
        for d in svc:
            types = [os.path.splitext(os.path.basename(x))[0] for x in _layers_in(d)]
            known = [t for t in types if t in groups]
            w(f'  - {rel(d)}   # ПРОВЕРЬТЕ: {len(types)} типов, из них в таблице групп: {", ".join(known) or "ни одного"}')
        for d in unused_dirs:
            if _layers_in(d):
                w(f'  # - {rel(d)}   # не подключено: {", ".join(os.path.splitext(os.path.basename(x))[0] for x in _layers_in(d))}')
    else:
        w('services:               # ПРОВЕРЬТЕ: папка сервисов не найдена — укажите путь')
    w('service_groups:          # своя таблица «тип сервиса → группа» (CSV); пусто — встроенная таблица')
    w('')
    m = layer_line('zones', 'зоны')
    zcols = [c for c in (m['df'].columns if m else [])
             if pd.api.types.is_object_dtype(m['df'][c]) or pd.api.types.is_string_dtype(m['df'][c])]
    zf = _pick(_ZONE_FIELD_HINTS, zcols) if m else None
    w(f'zone_field: {zf or ""}' + (f'   # ПРОВЕРЬТЕ: поле кода зоны; текстовые поля: {", ".join(map(str, zcols))}' if m else ''))
    w('zone_rules:              # нежилое здание без сервисов: «код зоны начинается с …» → группа (К, ОД, П); иначе X')
    w('  # "ТП": П              # пример')
    if m and zf:
        vals = m['df'][zf].dropna().astype(str).value_counts()
        w(f'  # коды зон в слое ({len(vals)}):')
        for v, n in vals.head(40).items():
            w(f'  #   {v}  ({n})')
    w('')
    w('territory: []            # номера кварталов территории, например [12, 13]; номера — в results/<код>_кварталы.geojson')
    w('')
    w('params:                  # параметры метода; раскомментируйте, чтобы изменить значение по умолчанию')
    for k, v in DEFAULTS.items():
        vv = ('да' if v else 'нет') if isinstance(v, bool) else v
        w(f'  # {k}: {vv}' + ' ' * max(1, 22 - len(k) - len(str(vv))) + f'# {PARAM_HELP.get(k, "")}')
    w('')
    w('scenarios:               # варианты: доли поэтажной площади, %, по группам Ж, К, ОД, П')
    for s, sh in SCENARIOS.items():
        w(f'  "{s}": {{Ж: {sh["Ж"]}, К: {sh["К"]}, ОД: {sh["ОД"]}, П: {sh["П"]}}}')
    if unused_files or unused_dirs:
        w('')
        w('# Не использовано (программе не нужно или не распознано):')
        for p in unused_files:
            meta, err = files[p]
            w(f'#   {rel(p)}' + (f' — {meta["n"]} объектов, {meta["kind"]}' if meta else f' — не читается: {err}'))
        for d in unused_dirs:
            w(f'#   {rel(d)}/')
    return out, '\n'.join(L) + '\n'
