"""Проверка входных данных и проверки чувствительности (шаги 7 и 7б)."""
import os

import pandas as pd

from .geometry import read_layer, describe_crs
from .compare import compare
from .scenarios import validate_scenarios
from .blocks import table_from_layers

_MERCATOR = (3857, 900913, 3395)


# ================================================================================================
# ПРОВЕРКА ДАННЫХ (команда check)
# ================================================================================================

def _layer_info(path):
    df, geoms, geographic = read_layer(path)
    kinds = pd.Series([g[0] for g in geoms], dtype=object).value_counts().to_dict()
    return df, kinds, geographic, df.attrs.get('epsg')


def _service_files(src):
    if os.path.isdir(src):
        return [os.path.join(src, x) for x in sorted(os.listdir(src)) if x.lower().endswith(('.geojson', '.gpkg'))]
    return [src]


def check_config(cfg):
    """Проверяет настройки и слои до расчёта. Возвращает (ошибки, предупреждения, сведения).

    Ошибки останавливают расчёт; предупреждения — нет, но их стоит прочитать.
    """
    err, warn, info = [], [], []
    mode = cfg.get('mode', 'layers')
    if mode not in ('layers', 'table'):
        err.append(f'mode: «{mode}» — допустимо layers (отдельные слои) или table (готовая таблица кварталов).')
        return err, warn, info
    err += validate_scenarios(cfg.get('scenarios'))
    fields = cfg.get('fields') or {}

    def need_file(key, label):
        p = cfg.get(key)
        if not p:
            err.append(f'Не указан слой «{label}» ({key}:).')
            return None
        if not os.path.exists(p):
            err.append(f'Слой «{label}» не найден: {p}')
            return None
        return p

    crs = {}
    # --- кварталы
    p = need_file('blocks', 'кварталы')
    if p:
        df, kinds, geo, epsg = _layer_info(p)
        crs['кварталы'] = (epsg, geo)
        info.append(f'кварталы: {len(df)} объектов ({kinds.get("poly", 0)} полигонов), {describe_crs(epsg, geo)}')
        if not kinds.get('poly'):
            err.append('В слое кварталов нет полигонов.')
        idf = cfg.get('block_id_field')
        if idf and idf not in df:
            warn.append(f'В слое кварталов нет поля номера «{idf}» — номер квартала будет равен порядку в файле (0, 1, 2…).')
        elif not idf:
            info.append('номер квартала — порядок в файле (0, 1, 2…), поле номера не задано')
        elif df[idf].duplicated().any():
            err.append(f'Номера кварталов в поле «{idf}» повторяются.')
        if mode == 'table':
            for key in ('population', 'living_area', 'non_living_area'):
                if fields.get(key) not in df:
                    err.append(f'В таблице кварталов нет поля «{fields.get(key)}» (fields.{key}).')
            if cfg.get('block_zone_field') and cfg['block_zone_field'] not in df:
                err.append(f'В таблице кварталов нет поля зоны «{cfg["block_zone_field"]}».')
            for key in ('count_prefix', 'capacity_prefix'):
                if not cfg.get(key):
                    err.append(f'Для режима table нужен параметр {key}.')
    # --- зоны
    if cfg.get('zones'):
        p = need_file('zones', 'зоны')
        if p:
            df, kinds, geo, epsg = _layer_info(p)
            crs['зоны'] = (epsg, geo)
            info.append(f'зоны: {len(df)} объектов, {describe_crs(epsg, geo)}')
            zf = cfg.get('zone_field')
            if zf not in df:
                err.append(f'В слое зон нет поля «{zf}» (zone_field). Есть поля: {", ".join(map(str, df.columns))}')
            else:
                codes = sorted(df[zf].dropna().astype(str).unique())
                rules = cfg.get('zone_rules') or []
                if not rules:
                    warn.append('Правила зон не заданы (zone_rules:): все нежилые здания без сервисов получат группу X.')
                for prefix, grp in rules:
                    if not any(c.startswith(prefix) for c in codes):
                        warn.append(f'Правило зон «{prefix}… → {grp}» не подходит ни к одному коду зоны.')
                hit = {c: next((g for pr, g in rules if c.startswith(pr)), 'X') for c in codes}
                info.append('зона → группа нежилого здания без сервисов:\n      ' + '\n      '.join(f'{c} → {g}' for c, g in hit.items()))
    elif mode == 'layers':
        warn.append('Слой зон не задан: нежилые здания без сервисов получат группу X.')
    # --- здания и сервисы
    if mode == 'layers':
        p = need_file('buildings', 'здания')
        if p:
            df, kinds, geo, epsg = _layer_info(p)
            crs['здания'] = (epsg, geo)
            info.append(f'здания: {len(df)} объектов ({kinds.get("poly", 0)} полигонов), {describe_crs(epsg, geo)}')
            if not fields.get('is_living') or fields['is_living'] not in df:
                err.append(f'В слое зданий нет поля «жилое» («{fields.get("is_living")}», fields.is_living). '
                           f'Есть поля: {", ".join(map(str, df.columns))}')
            for key, label, default in [('footprint', 'площадь застройки', 'будет считаться по контуру здания'),
                                        ('storeys', 'этажность', f'все здания — {cfg["params"]["storeys_default"]} этаж'),
                                        ('living_area', 'жилая площадь', 'оценка A·k_liv'),
                                        ('population', 'жители', 'оценка жилая площадь ÷ q')]:
                fld = fields.get(key)
                if fld and fld not in df:
                    warn.append(f'В слое зданий нет поля «{fld}» ({label}, fields.{key}): {default}.')
                elif not fld:
                    warn.append(f'Поле «{label}» не указано (fields.{key}): {default}.')
        srcs = cfg.get('services')
        srcs = srcs if isinstance(srcs, (list, tuple)) else ([srcs] if srcs else [])
        if not srcs:
            err.append('Не указаны сервисы (services:).')
        groups = cfg['_groups']
        for src in srcs:
            if not os.path.exists(src):
                err.append(f'Сервисы не найдены: {src}')
                continue
            files = _service_files(src)
            if not files:
                err.append(f'В папке сервисов {src} нет файлов .geojson / .gpkg.')
                continue
            types = []
            for fp in files:
                df, kinds, geo, epsg = _layer_info(fp)
                crs[f'сервисы {os.path.basename(fp)}'] = (epsg, geo)
                types.append(os.path.splitext(os.path.basename(fp))[0])
            if os.path.isdir(src):
                used = [t for t in types if t in groups]
                none = [t for t in types if t not in groups]
                info.append(f'сервисы {src}: {len(files)} файлов; с группой: '
                            + (', '.join(f'{t} → {groups[t]}' for t in used) or 'нет'))
                if none:
                    warn.append(f'Типы сервисов без группы (не учитываются): {", ".join(none)}. '
                                f'Чтобы учесть — добавьте их в таблицу групп (service_groups:).')
                for t in ('school', 'kindergarten'):
                    fp = [x for x in files if os.path.splitext(os.path.basename(x))[0] == t]
                    if fp:
                        df, *_ = _layer_info(fp[0])
                        if 'capacity' not in df:
                            warn.append(f'У объектов «{t}» нет поля capacity: число мест будет 0.')
                        else:
                            n = int(pd.to_numeric(df['capacity'], errors='coerce').isna().sum())
                            if n:
                                warn.append(f'У {n} объектов «{t}» не указано число мест: принято 0.')
            elif cfg.get('service_type_field', 'service_type') not in _layer_info(src)[0]:
                err.append(f'В файле сервисов {src} нет поля типа «{cfg.get("service_type_field", "service_type")}».')
    # --- системы координат
    systems = {}
    for name, (epsg, geo) in crs.items():
        if not geo and epsg in _MERCATOR:
            err.append(f'Слой «{name}» в EPSG:{epsg} (веб-Меркатор) — площади и расстояния искажены. '
                       f'Перепроецируйте в QGIS в EPSG:4326 или в зону UTM.')
        systems.setdefault(describe_crs(epsg, geo), []).append(name)
    if len(systems) > 1:
        bad = [k for k in systems if not (k.startswith('градусы') or k.startswith('UTM'))]
        msg = 'Слои в разных системах координат: ' + '; '.join(
            f'{k} — {", ".join(v[:3])}{" и ещё " + str(len(v) - 3) if len(v) > 3 else ""}' for k, v in systems.items())
        if bad:
            err.append(msg + '. Программа пересчитывает только градусы и зоны UTM; остальные слои перепроецируйте в QGIS.')
        else:
            warn.append(msg + '. Программа сама приведёт их к системе кварталов (градусы ↔ UTM).')
    # --- параметры и территория
    for k, v in cfg['params'].items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0:
            err.append(f'Параметр {k} = {v}: должен быть неотрицательным.')
    if not cfg.get('territory'):
        warn.append('Территория не задана (territory:). Команда compare попросит её указать.')
    return err, warn, info


# ================================================================================================
# ШАГ 7. Проверка устойчивости: R = 500, 800, 1000 м; КИТ = 1,4; 2,0 (как в ноутбуке)
# ================================================================================================

def sensitivity(city, T, P, SCN, Rs=(500, 800, 1000), kits=(1.4, 2.0)):
    """Шаг 7. Сравнение повторяется при других R и КИТ. Таблица — как results/<код>_устойчивость.csv."""
    rows = []
    for R in Rs:
        for kit in kits:
            tb, inf, _ = compare(city, T, dict(P, R=R, kit=kit), SCN)
            dev = tb.loc['Отклонение от среднего |K−K_ref|', list(SCN)].astype(float)
            sch = tb.loc['Школы: свободно (+) / не хватает (−), мест', list(SCN)]
            rows.append({'R, м': R, 'КИТ': kit, 'кварталов в окружении': inf['кварталов в окружении'],
                         'порядок по близости K к среднему': ' < '.join(s.split()[0] for s in dev.sort_values().index),
                         **{f'|K−K_ref| {s.split()[0]}': dev[s] for s in SCN},
                         **{f'школы {s.split()[0]}': sch[s] for s in SCN}})
    return pd.DataFrame(rows)


# ================================================================================================
# ШАГ 7б. Встроенные помещения: без них и при s0 = 50, 100, 300 м²
# ================================================================================================

def builtin_sensitivity(L, cfg, P, T_ids, SCN, s0_values=(50, 100, 300)):
    """Шаг 7б. Таблица кварталов пересчитывается без встроенных помещений и при разных s0.

    Формат таблицы предварительный: эталона `_встроенные.csv` нет — [УТОЧНИТЬ У АВТОРА].
    В режиме «таблица» не считается (нет слоя зданий) — возвращает None.
    """
    if L['mode'] != 'layers':
        return None
    rows = []
    runs = [('без встроенных', dict(P, builtin=False))] + \
           [(f's0 = {s0} м²', dict(P, builtin=True, builtin_s0=s0)) for s0 in s0_values]
    for label, PP in runs:
        city = table_from_layers(L, cfg, PP)
        t, rep = city['table'], city['report']
        row = {'расчёт': label,
               'жилых домов со встроенными': rep.get('жилых домов со встроенными помещениями', 0),
               'встроенная площадь К, м²': int(round(t['встр_К'].sum())),
               'встроенная площадь ОД, м²': int(round(t['встр_ОД'].sum())),
               'рабочих мест': int(round(t['jobs'].sum())),
               'K_ref': rep['K_ref — рабочих мест на жителя в среднем']}
        if T_ids:
            tb, inf, _ = compare(city, T_ids, PP, SCN)
            row['рабочих мест в окружении'] = inf['рабочих мест в окружении']
            for name in tb.columns:
                row[f'K {name.split()[0] if name != "Как есть" else "как есть"}'] = tb.loc['Работа на жителя K', name]
        rows.append(row)
    return pd.DataFrame(rows)
