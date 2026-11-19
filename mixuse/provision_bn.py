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
        for attempt in range(retries):
            try:
                graph = get_accessibility_graph(territory, graph_type)
                break
            except net_errors as e:                      # только сеть и сервер Overpass — повторяем
                say(f'  граф: попытка {attempt + 1} не удалась ({type(e).__name__}: {str(e)[:150]})')
                if attempt == retries - 1:
                    raise BlocksnetError(f'Не удалось скачать граф {graph_type} из OpenStreetMap: {e}. '
                                         'Проверьте интернет и повторите позже.')
                time.sleep(60 * 2 ** attempt)
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
