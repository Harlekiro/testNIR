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
    elif mode == 'layers' and cfg.get('block_zone_field'):
        info.append(f'зона квартала — поле «{cfg["block_zone_field"]}» слоя кварталов')
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
                used = [t for t in types if groups.get(t, 'нет') != 'нет']
                none = [t for t in types if t not in groups]
                ignored = [t for t in types if groups.get(t) == 'нет']
                info.append(f'сервисы {src}: {len(files)} файлов; с группой: '
                            + (', '.join(f'{t} → {groups[t]}' for t in used) or 'нет'))
                if none:
                    warn.append(f'Типов нет в таблице групп (не учитываются): {", ".join(none)}. '
                                f'Чтобы учесть — добавьте строки в таблицу групп (тип; название; код_ВРИ; группа).')
                if ignored:
                    info.append('не учитываются по таблице групп (группа «нет»): ' + ', '.join(ignored))
                for t in [x for x in types if groups.get(x) in ('школа', 'детский_сад')]:
                    fp = [x for x in files if os.path.splitext(os.path.basename(x))[0] == t]
                    if fp:
                        df, *_ = _layer_info(fp[0])
                        capf = cfg.get('capacity_field', 'capacity')
                        if not capf or capf not in df:
                            warn.append(f'У объектов «{t}» нет поля числа мест «{capf}»: принято 0 мест.')
                        else:
                            n = int(pd.to_numeric(df[capf], errors='coerce').isna().sum())
                            if n:
                                warn.append(f'У {n} объектов «{t}» не указано число мест: принято 0.')
            else:
                fld = cfg.get('service_type_field')
                flist = fld if isinstance(fld, (list, tuple)) else [fld]
                if fld is None or not any(x in _layer_info(src)[0] for x in flist):
                    err.append(f'В файле сервисов {src} нет поля типа {fld} (service_type_field:).')
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
        elif cfg.get('rules', 'v5') == 'v5':
            err.append(msg + '. По правилу 4.1.2 все слои набора должны быть в одной системе координат: '
                       'сохраните их в QGIS в системе кварталов («Экспорт» → «Сохранить объекты как…»).')
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
# ШАГ 7. Проверка устойчивости: R = 500, 800, 1000 м; КИТ = 1,4; 2,0 (как в ноутбуке v4)
# ================================================================================================

def sensitivity(city, T, P, SCN, Rs=(500, 800, 1000), kits=(1.4, 2.0)):
    """Шаг 7. Сравнение повторяется при других R и КИТ: K окружения «как есть», изменение K
    в каждом варианте (K варианта − K как есть) и нехватка мест в школах.
    Таблица — как results/<код>_устойчивость.csv. Порядка вариантов нет."""
    rows = []
    for R in Rs:
        for kit in kits:
            tb, inf, _ = compare(city, T, dict(P, R=R, kit=kit), SCN)
            k = tb.loc['Работа на жителя K: окружение'].astype(float)
            sch = tb.loc['Школы: не хватает мест', list(SCN)]
            rows.append({'R, м': R, 'КИТ': kit, 'кварталов в окружении': inf['кварталов в окружении'],
                         'K окружения как есть': k['Как есть'],
                         **{f'изменение K {s.split()[0]}': round(k[s] - k['Как есть'], 2) for s in SCN},
                         **{f'школы: не хватает мест {s.split()[0]}': sch[s] for s in SCN}})
    return pd.DataFrame(rows)


# ================================================================================================
# ШАГ 7б. Встроенные помещения: без них и при s0 = 50, 100, 300 м²
# ================================================================================================

def builtin_sensitivity(L, cfg, P, T, SCN, s0_values=(50, 100, 300)):
    """Шаг 7б. Таблица кварталов и сравнение пересчитываются без встроенных помещений и при разных s0.

    Таблица — как results/<код>_встроенные.csv. В режиме «таблица» не считается (нет слоя зданий) — None.
    Имя столбца «K окружения Как» повторяет ноутбук (первое слово названия варианта «Как есть»).
    """
    if L['mode'] != 'layers':
        return None
    rows = []
    runs = [('без встроенных', dict(P, builtin=False))] + [(f's0 = {s0} м²', dict(P, builtin_s0=s0)) for s0 in s0_values]
    for name, pp in runs:
        c2 = table_from_layers(L, cfg, pp); t2 = c2['table']
        tb, inf, _ = compare(c2, T, pp, SCN)
        rows.append({'расчёт': name,
                     'встроенная площадь К, м²': int(round(t2['встр_К'].sum())), 'встроенная площадь ОД, м²': int(round(t2['встр_ОД'].sum())),
                     'рабочих мест': int(round(t2['jobs'].sum())), 'K_ref': round(float(t2['jobs'].sum() / t2['pop'].sum()), 3),
                     **{f'K окружения {s.split()[0]}': tb.loc['Работа на жителя K: окружение', s] for s in ['Как есть'] + list(SCN)}})
    return pd.DataFrame(rows)
