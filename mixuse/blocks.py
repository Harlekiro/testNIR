"""Шаги 1–4: таблица кварталов.

Файл разделён на две части:
  * чтение слоёв (load_*) — открывает файлы и приводит координаты к системе кварталов;
  * расчёт (table_from_layers, table_from_table, finish_table) — только формулы, без файлов и печати.
Расчёт повторяет листинг ноутбука v4 (16.11.2026). Добавлено: приведение слоёв в разных системах
координат к системе кварталов и счётчики допущений в отчёте.
Номера формул по `docs/метод.md` — [НУЖЕН ФАЙЛ: сверить, когда автор пришлёт документ].
"""
import os
from collections import defaultdict

import numpy as np
import pandas as pd

from .geometry import (read_layer, LocalProjection, project, poly_area, centroid, inner_point,
                       assign_points, BlockGeometry, to_frame, check_crs)
from .groups import FUNCS, NOT_IN_TABLE, zone_group, building_group


class DataError(ValueError):
    """Ошибка во входных данных — сообщение для пользователя."""


# ================================================================================================
# ЧТЕНИЕ СЛОЁВ
# ================================================================================================

def load_blocks(cfg):
    """Шаг 1. Кварталы: чтение, перевод в метры, площадь, центр; зона — та, в которую попадает центр.

    Дополнительно возвращает frame — систему координат кварталов, к которой приводятся остальные слои,
    и список выполненных пересчётов координат.
    """
    df, geoms, geographic = read_layer(cfg['blocks'])
    epsg = df.attrs.get('epsg')
    check_crs(epsg, geographic, 'кварталы')
    idf = cfg.get('block_id_field')
    df['block_id'] = pd.to_numeric(df[idf]).astype(int) if idf and idf in df else np.arange(len(df))
    df['_g'] = geoms
    df = df[[g[0] == 'poly' for g in geoms]].copy()
    if len(df) == 0:
        raise DataError(f'В слое кварталов {cfg["blocks"]} нет полигонов.')
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


def service_files(src):
    """Файлы сервисов: путь или список путей; папка → все .geojson/.gpkg в ней (тип = имя файла)."""
    out = []
    for p in (src if isinstance(src, (list, tuple)) else [src]):
        if os.path.isdir(p):
            out += [(os.path.join(p, x), True) for x in sorted(os.listdir(p)) if x.endswith(('.geojson', '.gpkg'))]
        else:
            out.append((p, False))
    return out


def service_type_of(df, field, fallback):
    """Тип сервиса: имя файла (папка «один файл — один тип»); значение поля; для списка полей OSM —
    «поле=значение» первого непустого поля (например, amenity=school)."""
    if field is None:
        return pd.Series(fallback, index=df.index)
    if isinstance(field, (list, tuple)):
        out = pd.Series('', index=df.index)
        for f in field:
            if f in df:
                v = df[f].astype(str).where(df[f].notna() & (df[f].astype(str).str.len() > 0), '')
                out = out.where(out != '', np.where(v != '', f + '=' + v, ''))
        return out
    return df[field].astype(str)


def load_services(cfg, frame, groups):
    """Шаг 2. Сервисы: точка для каждого объекта, тип, число мест, группа по таблице групп."""
    frames, notes = [], []
    capf = cfg.get('capacity_field', 'capacity')
    for path, in_folder in service_files(cfg['services']):
        df, g, geo = read_layer(path)
        df = df.copy()
        name = os.path.splitext(os.path.basename(path))[0]
        fld = None if in_folder else cfg.get('service_type_field')
        if fld is not None and not any(x in df for x in (fld if isinstance(fld, (list, tuple)) else [fld])):
            raise DataError(f'В файле сервисов {path} нет поля типа {fld}. Укажите service_type_field в настройках.')
        df['service_type'] = service_type_of(df, fld, name).values
        g, note = to_frame(g, df.attrs.get('epsg'), geo, frame, f'сервисы {name}')
        if note: notes.append(note)
        pts = [gg[1] if gg[0] == 'point' else (inner_point(gg[1]) if gg[0] == 'poly' else None) for gg in g]
        df['x'] = [p[0] if p is not None else np.nan for p in pts]; df['y'] = [p[1] if p is not None else np.nan for p in pts]
        df['capacity'] = pd.to_numeric(df[capf], errors='coerce') if capf and capf in df else np.nan
        df['name'] = df['name'].astype(str).where(df['name'].notna(), '') if 'name' in df else ''
        frames.append(df[['service_type', 'x', 'y', 'capacity', 'name']])
    if not frames:
        raise DataError(f'Сервисы не найдены: {cfg["services"]}')
    s = pd.concat(frames, ignore_index=True).dropna(subset=['x', 'y'])
    s['group'] = s['service_type'].map(groups).fillna(NOT_IN_TABLE)
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

def truthy(col):
    """Признак «жилое»: жилыми считаются 1, True, да, yes (как в ноутбуке)."""
    s = col.astype(str).str.strip().str.lower()
    return s.isin(['1', '1.0', 'true', 'да', 'yes', 'y', 'жилое', 'жилой'])


def builtin_premises(n_K, n_OD, footprint, s0, share):
    """Встроенные помещения одного жилого дома (метод, шаг 4, п. 4).

        B = min(n · s0, β · S),   n = n_К + n_ОД;    B_g = B · n_g / n,
    где S — площадь застройки, s0 — площадь одного помещения, β — предельная доля первого этажа.
    Если s0 не задано (0 или None) — B = β · S. Возвращает (B_К, B_ОД, ограничено_долей_этажа).
    """
    n = n_K + n_OD
    lim = footprint * share
    area = min(lim, n * s0) if s0 else lim
    return area * n_K / n, area * n_OD / n, bool(s0) and n * s0 > lim


def table_from_layers(L, cfg, P):
    """Шаги 2–4, режим «слои».

    3. Здания и сервисы → точки → номер квартала.
    4. Поэтажная площадь A = S · этажность (нет этажности → storeys_default);
       встроенные помещения B (если builtin) — builtin_premises;
       жилая площадь — из поля, иначе (A − B) · k_liv; для домов с B > 0 — не больше (A − B) · k_liv;
       жители — из поля, иначе жилая площадь ÷ q; у нежилых зданий жителей и жилой площади нет;
       группа нежилого здания (S ≥ S_min) — building_group; NR_g = Σ A нежилых зданий группы g в квартале.
    """
    blocks = L['blocks']
    report = {'кварталов': len(blocks)}
    allxy = np.vstack([r for p in blocks['polys'] for q in p for r in q]); lo, hi = allxy.min(0) - 50, allxy.max(0) + 50

    # --- сервисы
    s = L['services']
    n_all = len(s)
    s = s[(s.x >= lo[0]) & (s.x <= hi[0]) & (s.y >= lo[1]) & (s.y <= hi[1])].reset_index(drop=True)
    s['block'] = assign_points(s[['x', 'y']].to_numpy(), list(blocks['polys']))
    report['сервисов в кварталах'] = int((s.block >= 0).sum())
    for g in FUNCS + ['школа', 'детский_сад']:
        report[f'  из них {g}'] = int(((s.block >= 0) & (s.group == g)).sum())
    report['сервисов вне кварталов (не учтены)'] = int((s.block < 0).sum()) + (n_all - len(s))
    report['типы не из таблицы групп (не учтены)'] = sorted(s.loc[s.group == NOT_IN_TABLE, 'service_type'].unique().tolist())
    for g, what in [('школа', 'школ'), ('детский_сад', 'детских садов')]:
        report[f'{what} без числа мест (принято 0 мест)'] = int(((s.block >= 0) & (s.group == g) & s.capacity.isna()).sum())

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
        fp = pd.to_numeric(bdf[f['footprint']], errors='coerce')
        report['зданий без площади застройки (принято 0)'] = int(fp.isna().sum())
        bdf['footprint'] = fp.fillna(0)
    else:
        bdf['footprint'] = [poly_area(p) for p in bpolys]
        report['площадь застройки'] = 'по контуру зданий (поле не задано)'
    bdf['living'] = truthy(bdf[f['is_living']])
    st = pd.to_numeric(bdf[f['storeys']], errors='coerce') if f.get('storeys') in bdf else pd.Series(np.nan, index=bdf.index)
    st = st.where(st > 0)
    bdf['storeys_missing'] = st.isna()                               # для отчёта о данных (4.2.2)
    bdf['storeys_one'] = st == 1                                      # указан 1 этаж (для отчёта о данных)
    report['зданий без этажности (принят 1 этаж)'] = int(st.isna().sum())
    st = st.fillna(P['storeys_default'])
    bdf['floor_area'] = bdf['footprint'] * st

    # --- встроенные помещения жилых домов
    bdf['bi_К'] = 0.0; bdf['bi_ОД'] = 0.0
    if P.get('builtin', True):
        res_idx = np.where((bdf.living & (st >= P.get('builtin_min_storeys', 2))).to_numpy())[0]
        bs = s[s.group.isin(['К', 'ОД'])].reset_index(drop=True)
        own = assign_points(bs[['x', 'y']].to_numpy(), [bpolys[i] for i in res_idx]) if len(res_idx) and len(bs) else np.full(len(bs), -1)
        cnt = defaultdict(lambda: {'К': 0, 'ОД': 0})
        for o, g in zip(own, bs.group):
            if o >= 0: cnt[res_idx[o]][g] += 1
        capped = 0
        for i, c in cnt.items():
            bK, bOD, cap = builtin_premises(c['К'], c['ОД'], bdf.at[i, 'footprint'], P.get('builtin_s0'), P.get('builtin_share', 1.0))
            bdf.at[i, 'bi_К'], bdf.at[i, 'bi_ОД'] = bK, bOD
            capped += int(cap)
        report['  домов, где площадь ограничена долей первого этажа'] = capped
        report['жилых домов со встроенными помещениями'] = len(cnt)
        report['  сервисов К и ОД в этих домах'] = int((own >= 0).sum())
        report['  встроенная площадь К / ОД, м²'] = f"{int(round(bdf['bi_К'].sum()))} / {int(round(bdf['bi_ОД'].sum()))}"
    else:
        report['встроенные помещения'] = 'не учитываются (builtin: нет)'
    res_floor = bdf['floor_area'] - bdf['bi_К'] - bdf['bi_ОД']       # поэтажная площадь без встроенных помещений
    if f.get('living_area') in bdf:
        la = pd.to_numeric(bdf[f['living_area']], errors='coerce')
        report['жилых домов без жилой площади (оценка (A − B)·k_liv)'] = int((la.isna() & bdf.living).sum())
        bdf['living_area'] = la.fillna(res_floor * P['k_liv'])
        has_bi = (bdf['bi_К'] + bdf['bi_ОД']) > 0                     # только дома со встроенными помещениями
        bdf['living_area'] = np.where(has_bi, np.minimum(bdf['living_area'], res_floor * P['k_liv']), bdf['living_area'])
    else:
        bdf['living_area'] = res_floor * P['k_liv']
        report['жилая площадь'] = 'оценка (A − B)·k_liv (поле не задано)'
    bdf.loc[~bdf.living, 'living_area'] = 0
    if f.get('population') in bdf:
        pp = pd.to_numeric(bdf[f['population']], errors='coerce')
        bdf['pop_missing'] = pp.isna() & bdf.living                 # для отчёта о данных (4.2.3)
        report['жилых домов без числа жителей (принято 0)'] = int((pp.isna() & bdf.living).sum())
        report['нежилых зданий с жителями в поле (обнулены)'] = int(((~bdf.living) & (pp.fillna(0) > 0)).sum())
        bdf['pop'] = pp.fillna(0)
    else:
        bdf['pop'] = bdf['living_area'] / P['q']
        report['жители'] = 'оценка: жилая площадь ÷ q (поле не задано)'
    bdf.loc[~bdf.living, 'pop'] = 0

    # --- группа нежилого здания: сервисы внутри контура (П > ОД > К), иначе зона квартала
    nr = (~bdf.living) & (bdf['footprint'] >= P['S_min'])
    report['нежилых зданий меньше S_min (не учтены)'] = int(((~bdf.living) & ~nr).sum())
    nr_idx = np.where(nr)[0]
    fs = s[s.group.isin(FUNCS)].reset_index(drop=True)
    owner = assign_points(fs[['x', 'y']].to_numpy(), [bpolys[i] for i in nr_idx]) if len(nr_idx) else np.full(len(fs), -1)
    found = defaultdict(set)
    for o, g in zip(owner, fs.group):
        if o >= 0: found[nr_idx[o]].add(g)
    rules = cfg.get('zone_rules', [])
    bdf['group'] = None
    by_service = 0
    for i in nr_idx:
        gs = found.get(i, set())
        by_service += bool(gs)
        bdf.at[i, 'group'] = building_group(gs, blocks.at[bdf.at[i, 'block'], 'zone'], rules)
    for g in FUNCS + ['X']:
        report[f'нежилых зданий в группе {g}'] = int((bdf.group == g).sum())
    report['  из них группа по сервисам внутри / по зоне или X'] = f'{by_service} / {len(nr_idx) - by_service}'

    # --- сводим в таблицу кварталов
    t = blocks[['block_id', 'zone', 'area', 'cx', 'cy']].copy()
    t['pop'] = bdf.groupby('block')['pop'].sum().reindex(t.index).fillna(0)
    t['liv'] = bdf.groupby('block')['living_area'].sum().reindex(t.index).fillna(0)
    for g in FUNCS + ['X']:
        t['nr_' + g] = bdf[bdf.group == g].groupby('block')['floor_area'].sum().reindex(t.index).fillna(0)
    for g in ['К', 'ОД']:                                   # встроенные помещения жилых домов
        t['встр_' + g] = bdf.groupby('block')['bi_' + g].sum().reindex(t.index).fillna(0)
        t['nr_' + g] = t['nr_' + g] + t['встр_' + g]
    for g in FUNCS:
        t['n_' + g] = s[(s.block >= 0) & (s.group == g)].groupby('block').size().reindex(t.index).fillna(0).astype(int)
    for g, col in [('школа', 'cap_school'), ('детский_сад', 'cap_kinder')]:
        t[col] = s[(s.block >= 0) & (s.group == g)].groupby('block')['capacity'].sum().reindex(t.index).fillna(0)
    pts = {g: s.loc[s.group == g, ['x', 'y']].to_numpy() for g in ['метро', 'остановка']}
    city = finish_table(t, L, P, pts, report)
    city['detail'] = {'buildings': bdf, 'bpolys': bpolys, 'services': s, 'services_all': L['services']}   # здания и сервисы для отчёта о данных
    return city


def table_from_table(L, cfg, P, groups):
    """Шаги 2–4, режим «таблица» (данные Гатчины): готовые жители и площади по кварталу;
    нежилая площадь относится к группе по зоне квартала; число сервисов и мест — по столбцам
    count_/capacity_ и таблице групп. Встроенные помещения не считаются: нет слоя зданий."""
    blocks = L['blocks']
    f = cfg['fields']; t = blocks[['block_id', 'zone', 'area', 'cx', 'cy']].copy()
    for key in ('population', 'living_area', 'non_living_area'):
        if f.get(key) not in blocks:
            raise DataError(f'В таблице кварталов нет поля «{f.get(key)}» (fields.{key}).')
    t['pop'] = pd.to_numeric(blocks[f['population']], errors='coerce').fillna(0)
    t['liv'] = pd.to_numeric(blocks[f['living_area']], errors='coerce').fillna(0)
    nonres = pd.to_numeric(blocks[f['non_living_area']], errors='coerce').fillna(0)
    grp = np.array([zone_group(z, cfg.get('zone_rules', [])) for z in blocks['zone']])
    for g in FUNCS + ['X']:
        t['nr_' + g] = np.where(grp == g, nonres, 0.0)
    cp, kp = cfg.get('count_prefix', 'count_'), cfg.get('capacity_prefix', 'capacity_')
    for g in FUNCS:
        cols = [c for c in blocks.columns if str(c).startswith(cp) and groups.get(str(c)[len(cp):]) == g]
        t['n_' + g] = blocks[cols].apply(pd.to_numeric, errors='coerce').fillna(0).sum(axis=1).astype(int) if cols else 0
    for g, col in [('школа', 'cap_school'), ('детский_сад', 'cap_kinder')]:
        cols = [c for c in blocks.columns if str(c).startswith(kp) and groups.get(str(c)[len(kp):]) == g]
        t[col] = blocks[cols].apply(pd.to_numeric, errors='coerce').fillna(0).sum(axis=1) if cols else 0.0
    report = {'кварталов': len(t), 'режим': 'готовая таблица кварталов (нежилая площадь — по зоне квартала)',
              'встроенные помещения': 'не считаются (нет слоя зданий)'}
    empty = np.zeros((0, 2))
    return finish_table(t, L, P, {'метро': empty, 'остановка': empty}, report)


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
    report['мест в школах / детских садах'] = f"{int(t['cap_school'].sum())} / {int(t['cap_kinder'].sum())}"
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
