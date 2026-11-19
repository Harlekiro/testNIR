"""Обеспеченность школами и детскими садами через blocksnet (ТЗ, раздел 12).

Единственный модуль пакета, который импортирует blocksnet (и geopandas, shapely, networkx). Ядро mixuse без него
работает как раньше. Устанавливается отдельно: pip install -e .[blocksnet] (Python 3.11, см. pyproject.toml).

Этап 8.3 — матрица доступности:
  * матрица строится по кварталам mixuse того же набора, в том же порядке и с теми же номерами (ТЗ 12.3):
    индекс и столбцы матрицы — block_id таблицы кварталов;
  * граф — пешеходный (решение автора 19.11.2026, ТЗ 8.2), из OpenStreetMap через iduedu (нужен интернет);
  * время — в минутах между точками на поверхности кварталов (representative_point, как в blocksnet);
  * матрица сохраняется в data/<код>/access/ и при расчёте вариантов не пересчитывается; рядом — описание
    (версия blocksnet, вид графа, число кварталов, контрольная сумма слоя кварталов), по которому
    load_matrix проверяет, что матрица построена на тех же кварталах.
"""
import hashlib
import json
import os
import time

import numpy as np
import pandas as pd

BLOCKSNET_VERSION = '1.0.0.dev1'      # закреплено в pyproject.toml (ТЗ 12.3)
GRAPH_TYPE = 'walk'                   # решение автора 19.11.2026: пешеходный граф для школ и садов
# Серверы Overpass для скачивания графа (по очереди при сбоях): основной и общедоступные зеркала
OVERPASS_URLS = ['https://overpass-api.de/api', 'https://overpass.kumi.systems/api', 'https://overpass.private.coffee/api']


class BlocksnetError(RuntimeError):
    """blocksnet не установлен или матрица не подходит — сообщение для пользователя."""


def require_blocksnet():
    """Импорт blocksnet с понятной ошибкой и проверкой закреплённой версии."""
    try:
        import blocksnet  # noqa: F401
        from importlib.metadata import version
    except ImportError:
        raise BlocksnetError('blocksnet не установлен. Он нужен только для обеспеченности школами и садами (раздел 12). '
                             'Установите в отдельное окружение с Python 3.11: pip install -e .[blocksnet]')
    v = version('blocksnet')
    if v != BLOCKSNET_VERSION:
        raise BlocksnetError(f'Установлен blocksnet {v}, а закреплена версия {BLOCKSNET_VERSION} (pyproject.toml). '
                             f'Поставьте закреплённую: pip install blocksnet=={BLOCKSNET_VERSION}')
    return v


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def access_dir(cfg):
    """Папка матриц набора: data/<код>/access/ в корне проекта (рядом с папкой configs/)."""
    root = os.path.dirname(os.path.dirname(cfg['_path'])) if cfg.get('_path', '').endswith('.yaml') else os.getcwd()
    return os.path.join(root, 'data', cfg['name'], 'access')


def blocks_gdf(cfg):
    """Кварталы mixuse как GeoDataFrame в исходной системе координат слоя; индекс — block_id (порядок mixuse)."""
    import geopandas as gpd
    from shapely.geometry import Polygon, MultiPolygon
    from .blocks import load_blocks
    df, frame, _ = load_blocks(cfg)
    geoms = [MultiPolygon([Polygon(p[0], p[1:]) for p in g[1]]) for g in df['_g']]
    crs = f'EPSG:{frame["epsg"]}' if frame['epsg'] else 'EPSG:4326'
    gdf = gpd.GeoDataFrame({'block_id': df['block_id'].astype(int).to_numpy()}, geometry=geoms, crs=crs)
    gdf.index = gdf['block_id']
    gdf.index.name = None
    return gdf


class _Peak:
    """Время и пиковая память процесса за блок (для отчёта 8.3)."""
    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, *a):
        self.sec = time.time() - self.t0
        try:
            import psutil
            p = psutil.Process()
            mi = p.memory_info()
            self.mem = getattr(mi, 'peak_wset', None) or mi.rss
        except ImportError:
            self.mem = None


def build_matrix(cfg, graph_type=GRAPH_TYPE, retries=4, say=print):
    """Строит граф и матрицу доступности по кварталам mixuse набора cfg. Возвращает (матрица, описание).

    Граф скачивается из OpenStreetMap (iduedu); публичный сервер бывает перегружен — до retries попыток
    с паузами 1, 2, 4 минуты."""
    v = require_blocksnet()
    import geopandas as gpd
    import requests
    from shapely.geometry import MultiPoint
    from blocksnet.relations import get_accessibility_graph, calculate_accessibility_matrix
    gdf = blocks_gdf(cfg)
    utm = gdf.estimate_utm_crs()
    blocks = gdf.to_crs(utm)
    n_invalid = int((~blocks.is_valid).sum())
    say(f'Кварталов: {len(blocks)} (геометрически некорректных — {n_invalid}); граф: {graph_type}; '
        f'система координат расчёта: EPSG:{utm.to_epsg()}')
    # Территория графа — выпуклая оболочка кварталов (так делает и blocksnet: union_all().convex_hull), но по вершинам:
    # объединение некорректных полигонов (самопересечения) падает, а оболочка вершин — та же самая и строится всегда.
    hull = MultiPoint([c for g in blocks.geometry for part in g.geoms for c in part.exterior.coords]).convex_hull
    territory = gpd.GeoDataFrame(geometry=[hull], crs=blocks.crs)
    net_errors = (requests.exceptions.RequestException, ConnectionError, TimeoutError)
    # Большую территорию osmnx скачивает частями: квадраты ~7 × 7 км, ожидание ответа до 10 мин; каждый ответ
    # кэшируется в data/<код>/access/osm_cache — повторная попытка продолжает с места обрыва, а не начинает заново.
    import osmnx as ox
    ox.settings.max_query_area_size = 50 * 1000 * 1000
    ox.settings.requests_timeout = 600
    ox.settings.use_cache = True
    ox.settings.cache_folder = os.path.join(access_dir(cfg), 'osm_cache')
    with _Peak() as pg:
        attempt = 0
        while True:                                      # retries = 0 — пробовать, пока сервер не ответит
            ox.settings.overpass_url = OVERPASS_URLS[attempt % len(OVERPASS_URLS)]   # основной сервер и зеркала по очереди
            try:
                graph = get_accessibility_graph(territory, graph_type)
                break
            except net_errors as e:                      # только сеть и сервер Overpass — повторяем
                attempt += 1
                cached = len(os.listdir(ox.settings.cache_folder)) if os.path.isdir(ox.settings.cache_folder) else 0
                wait = min(120 * 2 ** (attempt - 1), 1800)
                say(f'  граф: попытка {attempt} ({ox.settings.overpass_url}) не удалась ({type(e).__name__}: {str(e)[:100]}); '
                    f'сохранено частей: {cached}; {time.strftime("%H:%M")}, следующая через {wait // 60} мин')
                if retries and attempt >= retries:
                    raise BlocksnetError(f'Не удалось скачать граф {graph_type} из OpenStreetMap: {e}. '
                                         'Проверьте интернет и повторите позже: скачанные части сохранены.')
                time.sleep(wait)
    say(f'  граф: узлов {graph.number_of_nodes()}, рёбер {graph.number_of_edges()}; {pg.sec:.0f} с')
    # Точка квартала — точка на поверхности (representative_point, как в blocksnet); у некорректного контура, если
    # точка не строится, — по исправленной копии контура (make_valid). Номера и геометрия кварталов mixuse не меняются.
    pts, n_fixed = [], 0
    for geom in blocks.geometry:
        try:
            pts.append(geom.representative_point())
        except Exception:
            pts.append(geom.buffer(0).representative_point() if geom.buffer(0).area > 0 else geom.centroid)
            n_fixed += 1
    with _Peak() as pm:
        b = gpd.GeoDataFrame(geometry=pts, index=blocks.index, crs=blocks.crs).to_crs(graph.graph['crs'])
        mx = calculate_accessibility_matrix(b, graph)
    say(f'  матрица {mx.shape[0]} × {mx.shape[1]}, {mx.dtypes.iloc[0]}; {pm.sec:.0f} с')
    vals = mx.to_numpy(dtype=float)
    meta = {
        'набор': cfg['name'], 'blocksnet': v, 'граф': graph_type, 'единицы': 'минуты',
        'кварталов': int(len(mx)), 'block_id': [int(i) for i in mx.index],
        'слой кварталов': os.path.basename(cfg['blocks']), 'sha256 слоя кварталов': file_sha256(cfg['blocks']),
        'построено': time.strftime('%Y-%m-%d %H:%M'),
        'граф: узлов / рёбер': [graph.number_of_nodes(), graph.number_of_edges()],
        'время: граф, с': round(pg.sec), 'время: матрица, с': round(pm.sec),
        'память процесса, МБ': None if pm.mem is None else round(pm.mem / 2 ** 20),
        'время в пути, мин: медиана / макс': [round(float(np.nanmedian(vals)), 1), round(float(np.nanmax(vals)), 1)],
        'пар без пути (NaN или inf)': int((~np.isfinite(vals)).sum()),
        'кварталов с некорректной геометрией (точка — по исправленному контуру)': [n_invalid, n_fixed],
    }
    return mx, meta


def matrix_paths(cfg, graph_type=GRAPH_TYPE):
    d = access_dir(cfg)
    return os.path.join(d, f'matrix_{graph_type}.pickle'), os.path.join(d, f'matrix_{graph_type}.json')


def save_matrix(cfg, mx, meta, graph_type=GRAPH_TYPE):
    pm, pj = matrix_paths(cfg, graph_type)
    os.makedirs(os.path.dirname(pm), exist_ok=True)
    mx.to_pickle(pm)
    with open(pj, 'w', encoding='utf-8') as f:
        json.dump({k: v for k, v in meta.items() if k != 'block_id'}, f, ensure_ascii=False, indent=1)
    return pm, pj


def check_matrix(mx, meta, block_ids, blocks_sha=None):
    """Проверка соответствия кварталов (ТЗ 12.3, 8.3): индекс и столбцы матрицы — те же номера кварталов в том же
    порядке, что в таблице mixuse; слой кварталов тот же. Возвращает список несоответствий (пустой — всё верно)."""
    errs = []
    ids = [int(i) for i in block_ids]
    if list(map(int, mx.index)) != ids:
        errs.append(f'номера строк матрицы не совпадают с кварталами mixuse ({len(mx.index)} против {len(ids)})')
    if list(map(int, mx.columns)) != ids:
        errs.append('номера столбцов матрицы не совпадают с кварталами mixuse')
    if len(set(ids)) != len(ids):
        errs.append('номера кварталов повторяются — соответствие не взаимно однозначно')
    if blocks_sha and meta.get('sha256 слоя кварталов') not in (None, blocks_sha):
        errs.append('матрица построена по другому файлу кварталов (контрольная сумма не совпадает)')
    return errs


def load_matrix(cfg, block_ids, graph_type=GRAPH_TYPE):
    """Готовая матрица набора с проверкой соответствия кварталов. Без blocksnet (только pandas)."""
    pm, pj = matrix_paths(cfg, graph_type)
    if not os.path.exists(pm):
        raise BlocksnetError(f'Нет матрицы доступности {pm}. Постройте её: python -m mixuse access {cfg["_path"]}')
    mx = pd.read_pickle(pm)
    meta = json.load(open(pj, encoding='utf-8')) if os.path.exists(pj) else {}
    errs = check_matrix(mx, meta, block_ids, file_sha256(cfg['blocks']))
    if errs:
        raise BlocksnetError('Матрица доступности не подходит к кварталам набора: ' + '; '.join(errs) +
                             f'. Постройте заново: python -m mixuse access {cfg["_path"]}')
    return mx, meta


# ================================================================================================
# ЭТАП 8.4: ОБЕСПЕЧЕННОСТЬ «КАК ЕСТЬ» (ТЗ 12.2, 12.4, 12.8)
# ================================================================================================

MAX_DEPTH = 2          # решение автора 19.11.2026: искать место до двойного порога («получили место вообще»)
# тип blocksnet → (группа таблицы групп, столбец мест в таблице кварталов, подпись)
SERVICES = {'school': ('школа', 'cap_school', 'Школы'), 'kindergarten': ('детский_сад', 'cap_kinder', 'Сады')}


def service_settings(name):
    """Нормы из настроек blocksnet (решение автора 19.11.2026): мест на 1000 жителей, порог доступности (мин) и
    вместимость для учреждений без числа мест — наименьшая из каталога blocksnet (как impute_services)."""
    require_blocksnet()
    from blocksnet.config import service_types_config as c
    units = c.units
    return {'demand': int(c[name]['demand']), 'accessibility': float(c[name]['accessibility']),
            'impute_capacity': int(units[units.service_type == name].capacity.min())}


def block_capacity(city, group, impute):
    """Места по кварталам (в порядке таблицы кварталов): сумма мест учреждений квартала; у учреждения без числа мест —
    impute мест (ТЗ 8.2, решение автора). Возвращает (места, число учреждений с подставленной вместимостью)."""
    t = city['table']
    s = city['detail']['services']
    sel = (s['block'] >= 0) & (s['group'] == group)
    cap = s.loc[sel, 'capacity']
    n_imp = int(cap.isna().sum())
    per = cap.fillna(impute).groupby(s.loc[sel, 'block']).sum()
    return per.reindex(range(len(t))).fillna(0).round().astype(int).to_numpy(), n_imp


def provision(city, mx, name, population=None, capacity=None, factor=1.0, max_depth=MAX_DEPTH):
    """Обеспеченность одним типом учреждений по всему набору — competitive_provision blocksnet без изменений (12.2).

    population, capacity — по кварталам в порядке таблицы (по умолчанию — жители и места «как есть»);
    factor — множитель порога доступности (проверка 12.8: 0,5 / 1 / 1,5).
    Возвращает (таблица по кварталам blocksnet с индексом block_id, настройки)."""
    require_blocksnet()
    from loguru import logger
    from blocksnet.config import log_config
    from blocksnet.analysis.provision import competitive_provision
    logger.remove(); log_config.set_disable_tqdm(True)
    st = service_settings(name)
    t = city['table']
    group, col, _ = SERVICES[name]
    if capacity is None:
        capacity, st['учреждений без мест (подставлено)'] = block_capacity(city, group, st['impute_capacity'])
    pop = t['pop'].to_numpy() if population is None else np.asarray(population, float)
    df = pd.DataFrame({'population': pop, 'capacity': np.asarray(capacity, int)}, index=t['block_id'].astype(int).to_numpy())
    st['порог, мин'] = st['accessibility'] * factor
    res, links = competitive_provision(df, mx, st['порог, мин'], demand=st['demand'], max_depth=max_depth)
    st['_links'] = links
    return res, st


def provision_share(res, ids=None):
    """Обеспеченность группы кварталов (12.2, п. 5): в пределах доступности = обеспеченный в пределах порога спрос ÷
    весь спрос; «получили место вообще» — то же с местами за порогом (до max_depth × порога). В процентах."""
    r = res if ids is None else res.loc[list(ids)]
    d = r['demand'].sum()
    if d <= 0:
        return None, None, 0
    return 100 * r['demand_within'].sum() / d, 100 * (r['demand_within'].sum() + r['demand_without'].sum()) / d, int(d)


def as_is_report(cfg, city, mx, T_ids, R=None, factors=(0.5, 1.0, 1.5)):
    """Отчёт 8.4: обеспеченность «как есть» — весь набор и окружение территории; запасной расчёт 4.7.3 рядом (12.8);
    проверка «не больше min(100 %; места ÷ спрос)»; чувствительность к порогу × 0,5 / 1 / 1,5.
    Возвращает (сводная таблица, таблица по кварталам)."""
    from .compare import territory_indices, environment
    t = city['table']; P = cfg['params']
    T = territory_indices(t, T_ids)
    E, _, _ = environment(city, T, P['R'] if R is None else R)
    E_ids = t['block_id'].iloc[E].astype(int).tolist()
    rows, per_block = [], pd.DataFrame({'block_id': t['block_id'].astype(int).to_numpy()})
    for name, (group, col, label) in SERVICES.items():
        res, st = provision(city, mx, name)
        cap_all = int(res['capacity'].sum())
        all_in, all_any, dem_all = provision_share(res)
        env_in, env_any, dem_env = provision_share(res, E_ids)
        popE = t['pop'].iloc[E].sum(); popT = t['pop'].iloc[T].sum()
        capET = t[col].iloc[list(E) + T].sum()
        fb = {}
        for norm_name, n in [('нормы ТЗ', P['n_school'] if name == 'school' else P['n_kinder']),
                             ('нормы blocksnet', st['demand'])]:
            need = (popE + popT) * n / 1000
            fb[norm_name] = 100 * capET / need if need > 0 else None
        limit = min(100.0, 100 * cap_all / dem_all) if dem_all else None
        sens = {}
        for f in factors:
            r2, _ = provision(city, mx, name, factor=f) if f != 1.0 else (res, st)
            sens[f] = provision_share(r2, E_ids)[0]
        rows.append({
            'учреждения': label, 'мест на 1000 жителей': st['demand'], 'порог, мин': st['accessibility'],
            'граф': GRAPH_TYPE, 'max_depth': MAX_DEPTH,
            'учреждений без мест (подставлено мест)': f"{st['учреждений без мест (подставлено)']} ({st['impute_capacity']})",
            'мест всего': cap_all, 'спрос всего': dem_all,
            'весь набор: в пределах доступности, %': _r(all_in), 'весь набор: получили место вообще, %': _r(all_any),
            'проверка 12.8: не больше min(100 %; места ÷ спрос), %': _r(limit),
            'окружение: спрос': dem_env,
            'окружение: в пределах доступности, %': _r(env_in), 'окружение: получили место вообще, %': _r(env_any),
            'запасной расчёт 4.7.3 (окружение и территория), нормы ТЗ, %': _r(fb['нормы ТЗ']),
            'запасной расчёт 4.7.3, нормы blocksnet, %': _r(fb['нормы blocksnet']),
            **{f'окружение: в пределах, порог × {f:g}, %'.replace('.', ','): _r(v) for f, v in sens.items()},
        })
        assert all_in is None or all_in <= limit + 1e-6, f'{label}: обеспеченность выше предела 12.8'
        r = res.reindex(per_block['block_id'])
        per_block[f'{label}: спрос'] = r['demand'].to_numpy()
        per_block[f'{label}: мест'] = r['capacity'].to_numpy()
        per_block[f'{label}: в пределах, %'] = np.round(100 * r['provision_strong'].to_numpy(dtype=float), 1)
        per_block[f'{label}: вообще, %'] = np.round(100 * r['provision_weak'].to_numpy(dtype=float), 1)
    per_block['окружение'] = per_block['block_id'].isin(E_ids)
    per_block['территория'] = per_block['block_id'].isin([int(i) for i in T_ids])
    return pd.DataFrame(rows).set_index('учреждения').T, per_block


def _r(v):
    return None if v is None else round(float(v), 1)


# ================================================================================================
# ЭТАП 8.5: ОБЕСПЕЧЕННОСТЬ В ВАРИАНТАХ (ТЗ 12.4, 12.5)
# ================================================================================================

def near_blocks(mx, T_ids, minutes):
    """Кварталы не дальше minutes от территории (по матрице, в обе стороны) — для ускорения 12.4."""
    a = mx.loc[list(T_ids)].min(axis=0)
    b = mx[list(T_ids)].min(axis=1)
    return [int(i) for i in mx.index if min(a[i], b[i]) <= minutes]


def variant_provision(city, mx, T_ids, E_ids, values, near=None):
    """Обеспеченность «как есть» и в каждом варианте (12.4) по всему набору (или по кварталам не дальше
    near × порога от территории — ускорение 12.4).

    Вариант: жители территории заменяются на N (4.6.4), распределённые по кварталам территории пропорционально
    площади; места школ и садов территории обнуляются (4.6.3). values — det['values'] из compare_v5.
    Возвращает {вариант: {'school'|'kindergarten': показатели 12.5}}."""
    t = city['table']
    ids = t['block_id'].astype(int).to_numpy()
    pos = {b: k for k, b in enumerate(ids)}
    Tpos = [pos[int(i)] for i in T_ids]
    area = t['area'].to_numpy()[Tpos]
    out = {}
    base_cap = {}
    for name, (group, col, label) in SERVICES.items():
        st = service_settings(name)
        base_cap[name] = block_capacity(city, group, st['impute_capacity'])[0]
    for scen, o in values.items():
        pop = t['pop'].to_numpy().astype(float).copy()
        out[scen] = {}
        for name in SERVICES:
            cap = base_cap[name].copy()
            if o['d'] is not None:                                   # вариант: замена застройки территории
                pop[Tpos] = o['N'] * area / area.sum()
                cap[Tpos] = 0
            if near:
                st = service_settings(name)
                keep = near_blocks(mx, T_ids, near * st['accessibility'])
                sel = np.isin(ids, keep)
                sub = mx.loc[keep, keep]
                sub_city = {'table': t[sel].reset_index(drop=True)}
                res, st = provision(sub_city, sub, name, population=pop[sel], capacity=cap[sel])
            else:
                res, st = provision(city, mx, name, population=pop, capacity=cap)
            env_in, env_any, _ = provision_share(res, [i for i in E_ids if i in res.index])
            rT = res.loc[[int(i) for i in T_ids]]
            out[scen][name] = {'env_in': env_in, 'env_any': env_any,
                               'children': int(rT['demand'].sum()), 'provided': int(rT['demand_within'].sum()),
                               'provided_any': int((rT['demand_within'] + rT['demand_without']).sum()),
                               'norm': st['demand'], 'threshold': st['accessibility']}
    for scen in out:                                                  # изменение обеспеченности окружения, п. п.
        for name in SERVICES:
            v, b = out[scen][name]['env_in'], out['Как есть'][name]['env_in']
            out[scen][name]['delta'] = None if v is None or b is None else v - b
    out['_source'] = ('blocksnet: competitive_provision, пешеходная матрица, нормы blocksnet (раздел 12)'
                      + (f'; кварталы не дальше {near:g} порогов от территории (12.4)' if near else ''))
    return out


# ================================================================================================
# ДАННЫЕ ДЛЯ СТРАНИЦЫ И БЫСТРОЙ ОЦЕНКИ (пункт 4; provision_estimate)
# ================================================================================================

def page_data(city, mx):
    """Точный расчёт blocksnet «как есть» в виде, нужном быстрой оценке (provision_estimate) и странице.
    Номера — строки таблицы кварталов. Пары «дети → учреждение» — только к кварталам с местами и не дальше
    двух порогов (ТЗ 12.6). Время — минуты, с точностью 0,1."""
    t = city['table']
    ids = t['block_id'].astype(int).to_numpy()
    pos = {int(b): k for k, b in enumerate(ids)}
    M = mx.loc[ids, ids].to_numpy(dtype=float)
    out = {'blocksnet': BLOCKSNET_VERSION, 'граф': GRAPH_TYPE, 'max_depth': MAX_DEPTH}
    for name in SERVICES:
        res, st = provision(city, mx, name)
        r = res.reindex(ids)
        thr = st['accessibility']
        links = []
        for (src, dst), v in st['_links']['value'].items():
            if v > 0:
                i, j = pos[int(src)], pos[int(dst)]
                links.append([i, j, int(v), int(M[i, j] <= thr), round(float(M[i, j]), 1)])
        fac = np.where(r['capacity'].to_numpy() > 0)[0]
        ii, jj = np.where(M[:, fac] <= 2 * thr)
        pairs = [[int(i), int(fac[j]), round(float(M[i, fac[j]]), 1)] for i, j in zip(ii, jj)]
        out[name] = {
            'norm': st['demand'], 'threshold': thr, 'impute_capacity': st['impute_capacity'],
            'capacity': r['capacity'].astype(int).tolist(), 'demand': r['demand'].astype(int).tolist(),
            'within': r['demand_within'].astype(int).tolist(), 'without': r['demand_without'].astype(int).tolist(),
            'free': r['capacity_left'].astype(int).tolist(), 'links': links, 'pairs': pairs,
        }
    return out


def save_page_data(cfg, city, pdat):
    """Сохраняет точный расчёт «как есть» для оценки и страницы: data/<код>/access/provision_<граф>.json.
    Рядом — номера кварталов, контрольная сумма слоя кварталов и число жителей: по ним проверяется, что данные
    подходят к таблице кварталов (provision_estimate.load_page_data)."""
    t = city['table']
    meta = {'block_id': t['block_id'].astype(int).tolist(), 'sha256 слоя кварталов': file_sha256(cfg['blocks']),
            'жителей': int(round(t['pop'].sum())), 'построено': time.strftime('%Y-%m-%d %H:%M')}
    path = os.path.join(access_dir(cfg), f'provision_{GRAPH_TYPE}.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(dict(pdat, meta=meta), f, ensure_ascii=False, separators=(',', ':'))
    return path
