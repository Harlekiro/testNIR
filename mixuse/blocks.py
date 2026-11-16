"""Шаги 1–4: таблица кварталов.

Файл разделён на две части:
  * чтение слоёв (load_*) — открывает файлы и приводит координаты к системе кварталов;
  * расчёт (table_from_layers, table_from_table, finish_table) — только формулы, без файлов и печати.
Расчёт повторяет ноутбук; новое — только встроенные помещения (переключатель `builtin`).
Номера формул — по `docs/метод.md` [НУЖЕН ФАЙЛ: номера формул сверить, когда автор пришлёт документ].
"""
import os
from collections import defaultdict

import numpy as np
import pandas as pd

from .geometry import (read_layer, LocalProjection, project, poly_area, centroid, inner_point,
                       assign_points, BlockGeometry, to_frame, check_crs, describe_crs)
from .groups import FUNCS, zone_group, building_group


class DataError(ValueError):
    """Ошибка во входных данных — сообщение для пользователя."""


# ================================================================================================
# ЧТЕНИЕ СЛОЁВ
# ================================================================================================

def load_blocks(cfg):
    """Шаг 1. Кварталы: чтение, отбор, перевод в метры, площадь, центр, зона.

    Как в ноутбуке. Дополнительно возвращается frame — система координат кварталов,
    к которой приводятся остальные слои, и список выполненных пересчётов координат.
    """
    df, geoms, geographic = read_layer(cfg['blocks'])
    epsg = df.attrs.get('epsg')
    check_crs(epsg, geographic, 'кварталы')
    idf = cfg.get('block_id_field')
    df['block_id'] = df[idf].astype(int) if idf and idf in df else np.arange(len(df))
    df['_g'] = geoms
    df = df[[g[0] == 'poly' for g in geoms]].copy()
    if len(df) == 0:
        raise DataError(f'В слое кварталов {cfg["blocks"]} нет полигонов.')
    if cfg.get('clip_ids') is not None:
        df = df[df['block_id'].isin(set(cfg['clip_ids']))].copy()
    df = df.reset_index(drop=True)
    proj = None
    if geographic:
        xy = np.vstack([r for g in df['_g'] for p in g[1] for r in p])
        proj = LocalProjection(xy[:, 0].mean(), xy[:, 1].mean())
        df['polys'] = [project([g], proj)[0][1] for g in df['_g']]
    else:
        df['polys'] = [g[1] for g in df['_g']]
    frame = {'proj': proj, 'epsg': epsg, 'geographic': geographic}
    notes = []
    df['area'] = [poly_area(p) for p in df['polys']]
    c = np.array([centroid(p) for p in df['polys']]); df['cx'], df['cy'] = c[:, 0], c[:, 1]
    df['zone'] = None
    if cfg.get('zones'):
        zdf, zg, zgeo = read_layer(cfg['zones'])
        zg, note = to_frame(zg, zdf.attrs.get('epsg'), zgeo, frame, 'зоны')
        if note: notes.append(note)
        zpolys = [g[1] if g[0] == 'poly' else [] for g in zg]
        k = assign_points(c, zpolys)
        df['zone'] = [zdf[cfg['zone_field']].iloc[i] if i >= 0 else None for i in k]
    elif cfg.get('block_zone_field'):
        df['zone'] = df[cfg['block_zone_field']]
    return df, frame, notes


def _service_files(src):
    if os.path.isdir(src):
        return [os.path.join(src, f) for f in sorted(os.listdir(src)) if f.lower().endswith(('.geojson', '.gpkg'))], True
    return [src], False


def load_services(cfg, frame, groups):
    """Шаг 2. Сервисы: папка «один файл — один тип» или один файл с полем типа; точка для каждого
    объекта; группа по таблице групп. Источников может быть несколько (список в настройках)."""
    srcs = cfg['services'] if isinstance(cfg['services'], (list, tuple)) else [cfg['services']]
    frames, notes = [], []
    for src in srcs:
        files, is_dir = _service_files(src)
        for path in files:
            df, g, geo = read_layer(path)
            name = os.path.splitext(os.path.basename(path))[0]
            if is_dir:
                df['service_type'] = name
            else:
                fld = cfg.get('service_type_field', 'service_type')
                if fld not in df:
                    raise DataError(f'В файле сервисов {path} нет поля типа «{fld}». Укажите service_type_field в настройках.')
                df['service_type'] = df[fld]
            if len(df) == 0:
                continue
            g, note = to_frame(g, df.attrs.get('epsg'), geo, frame, f'сервисы {name}')
            if note: notes.append(note)
            pts = [gg[1] if gg[0] == 'point' else (inner_point(gg[1]) if gg[0] == 'poly' else None) for gg in g]
            df['x'] = [p[0] if p is not None else np.nan for p in pts]; df['y'] = [p[1] if p is not None else np.nan for p in pts]
            df['capacity'] = pd.to_numeric(df['capacity'], errors='coerce') if 'capacity' in df else np.nan
            frames.append(df[['service_type', 'x', 'y', 'capacity']])
    if not frames:
        s = pd.DataFrame({'service_type': pd.Series(dtype=object), 'x': pd.Series(dtype=float),
                          'y': pd.Series(dtype=float), 'capacity': pd.Series(dtype=float)})
    else:
        s = pd.concat(frames, ignore_index=True).dropna(subset=['x', 'y'])
    s['group'] = s['service_type'].map(groups).fillna('не используется')
    return s, notes


def load_buildings(cfg, frame):
    """Здания: таблица атрибутов и контуры в системе кварталов (только полигоны)."""
    bdf, bg, bgeo = read_layer(cfg['buildings'])
    bg, note = to_frame(bg, bdf.attrs.get('epsg'), bgeo, frame, 'здания')
    keep = [i for i, g in enumerate(bg) if g[0] == 'poly']
    bdf = bdf.iloc[keep].reset_index(drop=True); bpolys = [bg[i][1] for i in keep]
    return bdf, bpolys, ([note] if note else [])


def load_layers(cfg, groups):
    """Читает все слои набора данных. Возвращает словарь для table_from_layers / table_from_table."""
    blocks, frame, notes = load_blocks(cfg)
    L = {'mode': cfg.get('mode', 'layers'), 'blocks': blocks, 'frame': frame, 'epsg': frame['epsg'], 'crs_notes': notes}
    if L['mode'] == 'layers':
        L['services'], n2 = load_services(cfg, frame, groups)
        L['buildings'], L['bpolys'], n3 = load_buildings(cfg, frame)
        notes += n2 + n3
    return L


# ================================================================================================
# РАСЧЁТ
# ================================================================================================

def _num(series):
    return pd.to_numeric(series, errors='coerce')


def _is_living(series):
    """Признак «жилое»: числа > 0 (как в ноутбуке); текст «да/yes/true/1» — тоже жилое."""
    try:
        return series.fillna(0).astype(float) > 0          # как в ноутбуке
    except (ValueError, TypeError):
        txt = series.astype(str).str.strip().str.lower()
        num = pd.to_numeric(series, errors='coerce')
        return (num.fillna(0) > 0) | txt.isin(['да', 'yes', 'true', 'жилое', 'жилой'])


def builtin_premises(n_K, n_OD, footprint, s0, share):
    """Встроенные помещения жилого дома (метод, шаг 4, п. 4).

        B = min(n · s0, β · S),   n = n_К + n_ОД,
        B_К = B · n_К / n,  B_ОД = B · n_ОД / n,
    где S — площадь застройки дома, s0 — площадь одного помещения, β — предельная доля первого этажа.
    Возвращает (B, B_К, B_ОД) — массивы по домам.
    """
    n_K = np.asarray(n_K, float); n_OD = np.asarray(n_OD, float); n = n_K + n_OD
    B = np.minimum(n * s0, share * np.asarray(footprint, float))
    with np.errstate(invalid='ignore', divide='ignore'):
        BK = np.where(n > 0, B * n_K / np.where(n > 0, n, 1), 0.0)
    return B, BK, B - BK


def table_from_layers(L, cfg, P):
    """Шаги 2–4 для исходных слоёв.

    3. Здания и сервисы → точки → номер квартала.
    4. Поэтажная площадь A = S · этажность (нет этажности → storeys_default);
       встроенные помещения B (если builtin) — см. builtin_premises;
       жилая площадь — из поля, иначе (A − B) · k_liv; для домов с B > 0 — не больше (A − B) · k_liv;
       жители — из поля, иначе жилая площадь ÷ q (жители дома со встроенными помещениями не меняются);
       группа нежилого здания (S ≥ S_min) — building_group; NR_g = Σ A нежилых зданий группы g в квартале.
    При builtin = нет расчёт совпадает с ноутбуком до введения встроенных помещений.
    """
    blocks = L['blocks']
    report = {'кварталов': len(blocks)}
    allxy = np.vstack([r for p in blocks['polys'] for q in p for r in q]); lo, hi = allxy.min(0) - 50, allxy.max(0) + 50

    # --- сервисы
    s = L['services']
    s = s[(s.x >= lo[0]) & (s.x <= hi[0]) & (s.y >= lo[1]) & (s.y <= hi[1])].reset_index(drop=True)
    s['block'] = assign_points(s[['x', 'y']].to_numpy(), list(blocks['polys']))
    report['сервисов в кварталах'] = int((s.block >= 0).sum())
    report['сервисов вне кварталов (не учтены)'] = int((s.block < 0).sum()) + int(len(L['services']) - len(s))
    report['типы без группы'] = sorted(s.loc[s.group == 'не используется', 'service_type'].unique().tolist())
    for g, name in [('школа', 'школ'), ('сад', 'детских садов')]:
        m = (s.block >= 0) & (s.group == g)
        report[f'{name} без числа мест (принято 0 мест)'] = int((m & s.capacity.isna()).sum())

    # --- здания
    bdf, bpolys = L['buildings'], L['bpolys']
    if len(bdf) == 0:
        raise DataError('В слое зданий нет полигонов.')
    ip = np.array([inner_point(p) for p in bpolys])
    inbox = (ip[:, 0] >= lo[0]) & (ip[:, 0] <= hi[0]) & (ip[:, 1] >= lo[1]) & (ip[:, 1] <= hi[1])
    bdf = bdf[inbox].reset_index(drop=True); bpolys = [p for p, k in zip(bpolys, inbox) if k]; ip = ip[inbox]
    bdf['block'] = assign_points(ip, list(blocks['polys'])) if len(ip) else np.zeros(0, int)
    sel = bdf.block >= 0; bdf = bdf[sel].reset_index(drop=True); bpolys = [p for p, k in zip(bpolys, sel) if k]
    report['зданий в кварталах'] = len(bdf)
    f = cfg['fields']
    if f.get('footprint') in bdf:
        bdf['footprint'] = _num(bdf[f['footprint']])
        report['зданий без площади застройки (не учтены)'] = int(bdf['footprint'].isna().sum())
    else:
        bdf['footprint'] = [poly_area(p) for p in bpolys]
        report['площадь застройки'] = 'по контуру зданий (поля нет)'
    bdf['living'] = _is_living(bdf[f['is_living']]) if f.get('is_living') in bdf else False
    st = _num(bdf[f['storeys']]) if f.get('storeys') in bdf else pd.Series(np.nan, index=bdf.index)
    st = st.where(st > 0)
    report['зданий без этажности'] = int(st.isna().sum())
    st = st.fillna(P['storeys_default'])   # нет этажности — считаем по умолчанию (1 этаж)
    bdf['floor_area'] = bdf['footprint'] * st

    # --- сервисы К, ОД, П для привязки к зданиям
    fs = s[s.group.isin(FUNCS)].reset_index(drop=True)

    # --- встроенные помещения в жилых домах
    bdf['B'] = 0.0; bdf['B_К'] = 0.0; bdf['B_ОД'] = 0.0
    if P.get('builtin'):
        res = bdf.living.to_numpy() & (st.to_numpy() >= P['builtin_min_storeys'])
        res_idx = np.where(res)[0]
        kod = fs[fs.group.isin(['К', 'ОД'])].reset_index(drop=True)
        if len(res_idx) and len(kod):
            own = assign_points(kod[['x', 'y']].to_numpy(), [bpolys[i] for i in res_idx])
            nK = np.zeros(len(bdf)); nOD = np.zeros(len(bdf))
            for o, g in zip(own, kod.group):
                if o >= 0:
                    (nK if g == 'К' else nOD)[res_idx[o]] += 1
            B, BK, BOD = builtin_premises(nK, nOD, bdf['footprint'].fillna(0).to_numpy(), P['builtin_s0'], P['builtin_share'])
            bdf['B'], bdf['B_К'], bdf['B_ОД'] = B, BK, BOD
        report['жилых домов со встроенными помещениями'] = int((bdf['B'] > 0).sum())
        report['встроенная площадь К, м²'] = int(round(bdf['B_К'].sum()))
        report['встроенная площадь ОД, м²'] = int(round(bdf['B_ОД'].sum()))
    else:
        report['встроенные помещения'] = 'не учитываются (builtin: нет)'

    k_liv = P['k_liv']
    if f.get('living_area') in bdf:
        la = _num(bdf[f['living_area']])
        report['жилых домов без жилой площади (оценка A·k_liv)'] = int((la.isna() & bdf.living).sum())
        liv0 = la.fillna(bdf['floor_area'] * k_liv)
        liv = la.fillna((bdf['floor_area'] - bdf['B']) * k_liv)
        cap = (bdf['floor_area'] - bdf['B']) * k_liv
        liv = liv.where(~(bdf['B'] > 0), np.minimum(liv, cap))
    else:
        liv0 = bdf['floor_area'] * k_liv
        liv = (bdf['floor_area'] - bdf['B']) * k_liv
        report['жилая площадь'] = 'оценка A·k_liv (поля нет)'
    bdf['living_area'] = liv
    bdf.loc[~bdf.living, 'living_area'] = 0
    if f.get('population') in bdf:
        pp = _num(bdf[f['population']])
        report['зданий без числа жителей (принято 0)'] = int((pp.isna() & bdf.living).sum())
        bdf['pop'] = pp.fillna(0)
        report['нежилых зданий с жителями в поле (учтены как есть)'] = int(((~bdf.living) & (bdf['pop'] > 0)).sum())
    else:
        # жители дома не меняются из-за встроенных помещений: считаются от жилой площади без B
        liv0 = liv0.where(bdf.living, 0)
        bdf['pop'] = liv0 / P['q']
        report['жители'] = 'оценка: жилая площадь ÷ q (поля нет)'

    # --- группа нежилого здания: сервисы внутри контура (П > ОД > К), иначе зона квартала
    nr = (~bdf.living) & (bdf['footprint'] >= P['S_min'])
    report[f'нежилых зданий меньше S_min (не учтены)'] = int(((~bdf.living) & ~(bdf['footprint'] >= P['S_min'])).sum())
    nr_idx = np.where(nr)[0]
    owner = assign_points(fs[['x', 'y']].to_numpy(), [bpolys[i] for i in nr_idx]) if len(nr_idx) else np.full(len(fs), -1)
    found = defaultdict(set)
    for o, g in zip(owner, fs.group):
        if o >= 0: found[nr_idx[o]].add(g)
    rules = cfg.get('zone_rules', [])
    bdf['group'] = None
    how = {'по сервисам': 0, 'по зоне': 0, 'X': 0}
    for i in nr_idx:
        gs = found.get(i, set())
        g = building_group(gs, blocks.at[bdf.at[i, 'block'], 'zone'], rules)
        bdf.at[i, 'group'] = g
        how['по сервисам' if gs else ('X' if g == 'X' else 'по зоне')] += 1
    report['нежилых зданий: группа по сервисам / по зоне / X'] = f'{how["по сервисам"]} / {how["по зоне"]} / {how["X"]}'

    # --- сводим в таблицу кварталов
    t = blocks[['block_id', 'zone', 'area', 'cx', 'cy']].copy()
    t['pop'] = bdf.groupby('block')['pop'].sum().reindex(t.index).fillna(0)
    t['liv'] = bdf.groupby('block')['living_area'].sum().reindex(t.index).fillna(0)
    for g in FUNCS + ['X']:
        t['nr_' + g] = bdf[bdf.group == g].groupby('block')['floor_area'].sum().reindex(t.index).fillna(0)
    for g in ['К', 'ОД']:
        t['встр_' + g] = bdf.groupby('block')['B_' + g].sum().reindex(t.index).fillna(0)
        t['nr_' + g] = t['nr_' + g] + t['встр_' + g]
    for g in FUNCS:
        t['n_' + g] = s[(s.block >= 0) & (s.group == g)].groupby('block').size().reindex(t.index).fillna(0).astype(int)
    for g, col in [('школа', 'cap_school'), ('сад', 'cap_kinder')]:
        t[col] = s[(s.block >= 0) & (s.group == g)].groupby('block')['capacity'].sum().reindex(t.index).fillna(0)
    pts = {g: s.loc[s.group == g, ['x', 'y']].to_numpy() for g in ['метро', 'остановка']}
    pts['производство'] = s.loc[(s.group == 'П') & (s.block < 0), ['x', 'y']].to_numpy()
    return finish_table(t, L, P, pts, report)


def table_from_table(L, cfg, P, groups):
    """Шаги 2–4, если таблица кварталов уже собрана (данные Гатчины): берутся готовые жители,
    площади и число сервисов; нежилая площадь относится к группе по назначению квартала.
    Встроенные помещения в этом режиме не считаются: нет слоя зданий."""
    blocks = L['blocks']
    f = cfg['fields']; t = blocks[['block_id', 'zone', 'area', 'cx', 'cy']].copy()
    for key in ('population', 'living_area', 'non_living_area'):
        if f.get(key) not in blocks:
            raise DataError(f'В таблице кварталов нет поля «{f.get(key)}» (fields.{key}).')
    t['pop'] = _num(blocks[f['population']]).fillna(0)
    t['liv'] = _num(blocks[f['living_area']]).fillna(0)
    nonres = _num(blocks[f['non_living_area']]).fillna(0)
    grp = [zone_group(z, cfg.get('zone_rules', [])) for z in blocks['zone']]
    for g in FUNCS + ['X']:
        t['nr_' + g] = np.where(np.array(grp) == g, nonres, 0.0)
    t['встр_К'] = 0.0; t['встр_ОД'] = 0.0
    for g in FUNCS:
        cols = [cfg['count_prefix'] + s for s, gg in groups.items() if gg == g and cfg['count_prefix'] + s in blocks]
        t['n_' + g] = blocks[cols].fillna(0).sum(axis=1).astype(int) if cols else 0
    t['cap_school'] = _num(blocks.get(cfg['capacity_prefix'] + 'school', 0)).fillna(0)
    t['cap_kinder'] = _num(blocks.get(cfg['capacity_prefix'] + 'kindergarten', 0)).fillna(0)
    report = {'кварталов': len(t), 'режим': 'готовая таблица кварталов',
              'встроенные помещения': 'не считаются (нет слоя зданий)'}
    empty = np.zeros((0, 2))
    return finish_table(t, L, P, {'метро': empty, 'остановка': empty, 'производство': empty}, report)


def finish_table(t, L, P, pts, report):
    """Общая часть шага 4.

        jobs = nr_К/a_К + nr_ОД/a_ОД + nr_П/a_П + nr_X/a_X;
        «функция g есть», если n_g > 0 или nr_g > 0;
        K_ref = Σ jobs / Σ pop по всем кварталам (справочно).
    """
    t['jobs'] = t['nr_К'] / P['a_К'] + t['nr_ОД'] / P['a_ОД'] + t['nr_П'] / P['a_П'] + t['nr_X'] / P['a_X']
    for g in FUNCS:
        t['есть_' + g] = (t['n_' + g] > 0) | (t['nr_' + g] > 0)
    report['жителей'] = int(round(t['pop'].sum())); report['рабочих мест (оценка)'] = int(round(t['jobs'].sum()))
    report['K_ref — рабочих мест на жителя в среднем'] = round(float(t['jobs'].sum() / t['pop'].sum()), 3) if t['pop'].sum() > 0 else None
    blocks = L['blocks']
    return {'table': t, 'polys': list(blocks['polys']), 'geom': BlockGeometry(list(blocks['polys'])),
            'orig': list(blocks['_g']), 'proj': L['frame']['proj'], 'pts': pts, 'report': report, 'epsg': L['epsg'],
            'crs_notes': L.get('crs_notes', [])}


def build_table(L, cfg, P, groups):
    """Таблица кварталов в нужном режиме («слои» или «таблица»)."""
    if L['mode'] == 'layers':
        return table_from_layers(L, cfg, P)
    if L['mode'] == 'table':
        return table_from_table(L, cfg, P, groups)
    raise DataError(f'Неизвестный режим подготовки «{L["mode"]}». Допустимо: layers (слои) или table (таблица).')
