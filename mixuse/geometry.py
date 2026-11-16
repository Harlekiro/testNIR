"""Чтение слоёв и простая геометрия.

Функции чтения GeoJSON/GeoPackage, локальной проекции, площади, «точки в полигоне» и расстояний
перенесены из ноутбука без изменений (блок «Служебные функции»): от них зависят числа на границах
полигонов. Новое в этом файле — только приведение слоёв в разных системах координат к одной
(раздел «Системы координат» в конце), в ноутбуке его не было.
"""
import json, os, re, sqlite3, struct, math
from collections import defaultdict
import numpy as np
import pandas as pd

# ---------- чтение GeoJSON и GeoPackage ----------

# --- Переводит геометрию объекта GeoJSON в списки координат: полигон → кольца контуров, точка → пара координат.
def _rings_from_geojson(geom):
    t = geom['type']; c = geom['coordinates']
    if t == 'Polygon':
        return 'poly', [[np.asarray(r, float)[:, :2] for r in c]]
    if t == 'MultiPolygon':
        return 'poly', [[np.asarray(r, float)[:, :2] for r in p] for p in c]
    if t == 'Point':
        return 'point', np.asarray(c[:2], float)
    if t == 'MultiPoint':
        return 'point', np.asarray(c[0][:2], float)
    return None, None


# --- Разбирает двоичную запись геометрии (WKB), в которой GeoPackage хранит контуры.
def _wkb(b, o):
    e = '<' if b[o] == 1 else '>'
    t = struct.unpack(e + 'I', b[o + 1:o + 5])[0]; o += 5
    base = (t & 0x0FFFFFFF) % 1000
    dim = 2 + (1 if (t & 0x80000000) or (t & 0x0FFFFFFF) // 1000 in (1, 3) else 0) \
            + (1 if (t & 0x40000000) or (t & 0x0FFFFFFF) // 1000 in (2, 3) else 0)
    if base == 1:
        v = struct.unpack(e + '%dd' % dim, b[o:o + 8 * dim]); return ('point', np.array(v[:2])), o + 8 * dim
    if base == 3:
        nr = struct.unpack(e + 'I', b[o:o + 4])[0]; o += 4; rings = []
        for _ in range(nr):
            n = struct.unpack(e + 'I', b[o:o + 4])[0]; o += 4
            v = np.frombuffer(b[o:o + 8 * dim * n], dtype=e + 'f8').reshape(n, dim)[:, :2]; o += 8 * dim * n
            rings.append(v.astype(float))
        return ('poly', [rings]), o
    if base in (4, 6):
        n = struct.unpack(e + 'I', b[o:o + 4])[0]; o += 4; parts = []
        for _ in range(n):
            (k, g), o = _wkb(b, o); parts.append(g)
        if base == 4:
            return ('point', parts[0]), o
        return ('poly', [p for g in parts for p in g]), o
    raise ValueError('тип геометрии не поддерживается: %d' % base)


# --- Пропускает служебный заголовок геометрии GeoPackage и передаёт её в _wkb.
def _gpkg_geom(blob):
    b = bytes(blob); flags = b[3]; env = (flags >> 1) & 7
    off = 8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[env]
    return _wkb(b, off)[0]


# --- Читает слой GeoJSON или GeoPackage.
#     Вход: путь к файлу. Выход: таблица атрибутов, список геометрий, признак «координаты в градусах».
def read_layer(path):
    """Читает GeoJSON или GeoPackage. Возвращает таблицу атрибутов, список геометрий и признак «координаты в градусах»."""
    if path.lower().endswith('.gpkg'):
        con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        table, srs = con.execute("select table_name, srs_id from gpkg_contents where data_type='features'").fetchone()
        gcol = con.execute('select column_name from gpkg_geometry_columns where table_name=?', (table,)).fetchone()[0]
        cur = con.execute(f'select * from "{table}"'); cols = [d[0] for d in cur.description]
        props, geoms = [], []
        for row in cur:
            d = dict(zip(cols, row)); g = d.pop(gcol)
            props.append(d); geoms.append(_gpkg_geom(g) if g is not None else (None, None))
        geographic = srs in (4326, 4258); epsg = srs
    else:
        fc = json.load(open(path, encoding='utf-8'))
        props = [f.get('properties') or {} for f in fc['features']]
        geoms = [_rings_from_geojson(f['geometry']) if f.get('geometry') else (None, None) for f in fc['features']]
        crs = json.dumps(fc.get('crs', ''))
        geographic = ('4326' in crs) or ('CRS84' in crs) or crs in ('""', '')
        m = re.search(r'EPSG::?(\d+)', crs); epsg = 4326 if geographic else (int(m.group(1)) if m else None)
    df = pd.DataFrame(props); df.attrs['epsg'] = epsg
    return df, geoms, geographic


# --- Переводит градусы в метры относительно центра территории:
#       x = (долгота − долгота₀) × 111 320 × cos(широта₀),  y = (широта − широта₀) × 110 540.
#     В пределах города ошибка меньше 0,5 %. QGIS: «Перепроецировать слой».
class LocalProjection:
    """Перевод градусов в метры (локальная проекция вокруг центра территории; ошибка < 0,5 % в пределах города)."""
    def __init__(self, lon0, lat0):
        self.lon0, self.lat0 = lon0, lat0
        self.kx = 111320 * math.cos(math.radians(lat0)); self.ky = 110540
    def xy(self, a):
        a = np.asarray(a, float)
        return np.column_stack(((a[..., 0] - self.lon0) * self.kx, (a[..., 1] - self.lat0) * self.ky)) if a.ndim == 2 \
            else np.array([(a[0] - self.lon0) * self.kx, (a[1] - self.lat0) * self.ky])


# --- Применяет LocalProjection ко всем геометриям слоя.
def project(geoms, proj):
    out = []
    for k, g in geoms:
        if k == 'poly':
            out.append(('poly', [[proj.xy(r) for r in p] for p in g]))
        elif k == 'point':
            out.append(('point', proj.xy(g)))
        else:
            out.append((None, None))
    return out

# ---------- простая геометрия ----------

# --- Площадь контура по формуле Гаусса: S = ½·Σ(xᵢ·yᵢ₊₁ − xᵢ₊₁·yᵢ).
def ring_area(r):
    x, y = r[:, 0], r[:, 1]
    return 0.5 * (np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1]))


# --- Площадь полигона = площадь внешнего контура − площади дырок. QGIS: $area.
def poly_area(polys):
    return sum(abs(ring_area(p[0])) - sum(abs(ring_area(h)) for h in p[1:]) for p in polys)


# --- Центр тяжести полигона. QGIS: «Центроиды».
def centroid(polys):
    A = cx = cy = 0.0
    for p in polys:
        r = p[0]; x, y = r[:, 0], r[:, 1]
        c = x[:-1] * y[1:] - x[1:] * y[:-1]; a = c.sum() / 2
        if abs(a) < 1e-9: continue
        A += a; cx += ((x[:-1] + x[1:]) * c).sum() / 6; cy += ((y[:-1] + y[1:]) * c).sum() / 6
    if abs(A) < 1e-9:
        r = polys[0][0]; return r[:, 0].mean(), r[:, 1].mean()
    return cx / A, cy / A


# --- Проверка «точка внутри полигона» методом луча: из точки проводится луч вправо;
#     если он пересекает границу нечётное число раз — точка внутри.
def points_in_polygon(px, py, polys):
    """Какие точки лежат внутри (много)угольника; дырки учитываются."""
    inside = np.zeros(len(px), bool)
    for p in polys:
        cnt = np.zeros(len(px), int)
        for r in p:
            x0, y0, x1, y1 = r[:-1, 0], r[:-1, 1], r[1:, 0], r[1:, 1]
            dy = np.where(y1 - y0 == 0, 1e-12, y1 - y0)
            cond = (y0[None, :] > py[:, None]) != (y1[None, :] > py[:, None])
            xint = (x1 - x0)[None, :] * (py[:, None] - y0[None, :]) / dy[None, :] + x0[None, :]
            cnt += (cond & (px[:, None] < xint)).sum(1)
        inside |= (cnt % 2 == 1)
    return inside


# --- Точка, гарантированно лежащая внутри полигона: центроид, а если он снаружи — середина
#     самого широкого внутреннего отрезка горизонтали. QGIS: «Точка на поверхности».
def inner_point(polys):
    """Точка на поверхности (как инструмент QGIS «Точка на поверхности»): центроид, а если он снаружи — середина самого широкого отрезка горизонтали."""
    big = max(polys, key=lambda p: abs(ring_area(p[0])))
    cx, cy = centroid([big])
    if points_in_polygon(np.array([cx]), np.array([cy]), [big])[0]:
        return np.array([cx, cy])
    r = big[0]; ym = (r[:, 1].min() + r[:, 1].max()) / 2; xs = []
    for ring in big:
        for (xa, ya), (xb, yb) in zip(ring[:-1], ring[1:]):
            if (ya > ym) != (yb > ym):
                xs.append(xa + (ym - ya) * (xb - xa) / (yb - ya))
    xs.sort()
    if len(xs) < 2: return r[0].copy()
    pairs = [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)]
    a, b = max(pairs, key=lambda q: q[1] - q[0])
    return np.array([(a + b) / 2, ym])


# --- Привязка точек к полигонам: для каждой точки — номер полигона, внутри которого она лежит.
#     Для скорости точки раскладываются по сетке 300 × 300 м. QGIS: «Объединить атрибуты по расположению».
def assign_points(pts, polys_list, cell=300.0):
    """Для каждой точки — номер многоугольника, внутри которого она лежит (−1, если ни в одном). Аналог «Объединить атрибуты по расположению»."""
    res = np.full(len(pts), -1)
    if len(pts) == 0: return res
    gx = np.floor(pts[:, 0] / cell).astype(np.int64); gy = np.floor(pts[:, 1] / cell).astype(np.int64)
    grid = defaultdict(list)
    for i, key in enumerate(zip(gx.tolist(), gy.tolist())):
        grid[key].append(i)
    for k, polys in enumerate(polys_list):
        if not polys: continue
        allpts = np.vstack([p[0] for p in polys])
        x0, y0 = allpts.min(0); x1, y1 = allpts.max(0)
        cand = [i for cx in range(int(x0 // cell), int(x1 // cell) + 1) for cy in range(int(y0 // cell), int(y1 // cell) + 1) for i in grid.get((cx, cy), ())]
        if not cand: continue
        cand = np.array(cand); cand = cand[res[cand] == -1]
        if len(cand) == 0: continue
        sel = (pts[cand, 0] >= x0) & (pts[cand, 0] <= x1) & (pts[cand, 1] >= y0) & (pts[cand, 1] <= y1)
        cand = cand[sel]
        if len(cand) == 0: continue
        ins = points_in_polygon(pts[cand, 0], pts[cand, 1], polys)
        res[cand[ins]] = k
    return res


# --- Хранит отрезки границ всех кварталов и считает расстояние от точки до каждого квартала
#     (0, если точка внутри). Используется в шагах 5–6. QGIS: «Буфер» + «Выбрать по расположению».
class BlockGeometry:
    """Отрезки границ всех кварталов — для быстрых расстояний «точка → каждый квартал»."""
    def __init__(self, polys_list):
        a, b, owner = [], [], []
        for k, polys in enumerate(polys_list):
            for p in polys:
                for r in p:
                    a.append(r[:-1]); b.append(r[1:]); owner.append(np.full(len(r) - 1, k))
        self.a = np.vstack(a); self.b = np.vstack(b); owner = np.concatenate(owner)
        order = np.argsort(owner, kind='stable'); self.a, self.b, owner = self.a[order], self.b[order], owner[order]
        self.n = len(polys_list)
        self.starts = np.searchsorted(owner, np.arange(self.n))
        self.has = np.bincount(owner, minlength=self.n) > 0
    def dist_from_point(self, x, y):
        """Расстояние от точки до каждого квартала (0, если точка внутри)."""
        ax, ay, bx, by = self.a[:, 0], self.a[:, 1], self.b[:, 0], self.b[:, 1]
        dx, dy = bx - ax, by - ay; L = dx * dx + dy * dy; L[L == 0] = 1e-12
        t = np.clip(((x - ax) * dx + (y - ay) * dy) / L, 0, 1)
        d = np.hypot(ax + t * dx - x, ay + t * dy - y)
        dmin = np.minimum.reduceat(d, self.starts)
        ddy = np.where(by - ay == 0, 1e-12, by - ay)
        cross = ((ay > y) != (by > y)) & (x < (bx - ax) * (y - ay) / ddy + ax)
        inside = np.add.reduceat(cross.astype(int), self.starts) % 2 == 1
        out = np.where(inside, 0.0, dmin); out[~self.has] = np.inf
        return out


# --- Расстояние от каждой точки до полигона (0, если точка внутри).
def dist_points_to_polys(pts, polys):
    """Расстояние от каждой точки до (много)угольника (0 внутри)."""
    if len(pts) == 0: return np.zeros(0)
    d = np.full(len(pts), np.inf)
    for p in polys:
        for r in p:
            ax, ay, bx, by = r[:-1, 0], r[:-1, 1], r[1:, 0], r[1:, 1]
            dx, dy = bx - ax, by - ay; L = dx * dx + dy * dy; L[L == 0] = 1e-12
            px, py = pts[:, 0][:, None], pts[:, 1][:, None]
            t = np.clip(((px - ax) * dx + (py - ay) * dy) / L, 0, 1)
            d = np.minimum(d, np.hypot(ax + t * dx - px, ay + t * dy - py).min(1))
    d[points_in_polygon(pts[:, 0], pts[:, 1], polys)] = 0.0
    return d


# ================================================================================================
# Системы координат (новое; в ноутбуке не было)
# Пользовательские слои часто записаны в разных системах: например, кварталы в UTM (EPSG:32635),
# а здания и сервисы в градусах (EPSG:4326). Все слои приводятся к системе кварталов:
#   кварталы в градусах  → локальная проекция LocalProjection (как в ноутбуке);
#   кварталы в UTM       → остальные слои пересчитываются в ту же зону UTM.
# Пересчёт градусы ↔ UTM — формулы Крюгера (ряды по n до 4-й степени, точность — доли миллиметра).
# QGIS: «Перепроецировать слой». EPSG:3857 запрещён: в нём площади и расстояния искажены.
# ================================================================================================

class CRSError(ValueError):
    """Слои нельзя привести к одной системе координат."""


_A_WGS, _F_WGS = 6378137.0, 1 / 298.257223563
_N = _F_WGS / (2 - _F_WGS)
_AA = _A_WGS / (1 + _N) * (1 + _N ** 2 / 4 + _N ** 4 / 64)
_ALPHA = [_N / 2 - 2 * _N ** 2 / 3 + 5 * _N ** 3 / 16 + 41 * _N ** 4 / 180,
          13 * _N ** 2 / 48 - 3 * _N ** 3 / 5 + 557 * _N ** 4 / 1440,
          61 * _N ** 3 / 240 - 103 * _N ** 4 / 140,
          49561 * _N ** 4 / 161280]
_BETA = [_N / 2 - 2 * _N ** 2 / 3 + 37 * _N ** 3 / 96 - _N ** 4 / 360,
         _N ** 2 / 48 + _N ** 3 / 15 - 437 * _N ** 4 / 1440,
         17 * _N ** 3 / 480 - 37 * _N ** 4 / 840,
         4397 * _N ** 4 / 161280]
_DELTA = [2 * _N - 2 * _N ** 2 / 3 - 2 * _N ** 3 + 116 * _N ** 4 / 45,
          7 * _N ** 2 / 3 - 8 * _N ** 3 / 5 - 227 * _N ** 4 / 45,
          56 * _N ** 3 / 15 - 136 * _N ** 4 / 35,
          4279 * _N ** 4 / 630]
_K0 = 0.9996


def utm_zone(epsg):
    """Номер зоны UTM и полушарие по коду EPSG (32601–32660 — север, 32701–32760 — юг); иначе None."""
    if epsg is None:
        return None
    e = int(epsg)
    if 32601 <= e <= 32660:
        return e - 32600, True
    if 32701 <= e <= 32760:
        return e - 32700, False
    return None


def lonlat_to_utm(a, zone, north=True):
    """Градусы (долгота, широта) → метры UTM. a — массив формы (n, 2) или пара."""
    a = np.asarray(a, float); one = a.ndim == 1; a = np.atleast_2d(a)
    lam = np.radians(a[:, 0] - (zone * 6 - 183)); phi = np.radians(a[:, 1])
    c = 2 * math.sqrt(_N) / (1 + _N)
    t = np.sinh(np.arctanh(np.sin(phi)) - c * np.arctanh(c * np.sin(phi)))
    xi1 = np.arctan2(t, np.cos(lam)); eta1 = np.arctanh(np.sin(lam) / np.sqrt(1 + t * t))
    xi, eta = xi1.copy(), eta1.copy()
    for j, al in enumerate(_ALPHA, 1):
        xi += al * np.sin(2 * j * xi1) * np.cosh(2 * j * eta1)
        eta += al * np.cos(2 * j * xi1) * np.sinh(2 * j * eta1)
    out = np.column_stack((500000 + _K0 * _AA * eta, (0 if north else 1e7) + _K0 * _AA * xi))
    return out[0] if one else out


def utm_to_lonlat(a, zone, north=True):
    """Метры UTM → градусы (долгота, широта)."""
    a = np.asarray(a, float); one = a.ndim == 1; a = np.atleast_2d(a)
    xi = (a[:, 1] - (0 if north else 1e7)) / (_K0 * _AA); eta = (a[:, 0] - 500000) / (_K0 * _AA)
    xi1, eta1 = xi.copy(), eta.copy()
    for j, be in enumerate(_BETA, 1):
        xi1 -= be * np.sin(2 * j * xi) * np.cosh(2 * j * eta)
        eta1 -= be * np.cos(2 * j * xi) * np.sinh(2 * j * eta)
    chi = np.arcsin(np.sin(xi1) / np.cosh(eta1))
    phi = chi.copy()
    for j, de in enumerate(_DELTA, 1):
        phi += de * np.sin(2 * j * chi)
    lam = np.arctan2(np.sinh(eta1), np.cos(xi1))
    out = np.column_stack((np.degrees(lam) + (zone * 6 - 183), np.degrees(phi)))
    return out[0] if one else out


def _map_geoms(geoms, fn):
    out = []
    for k, g in geoms:
        if k == 'poly':
            out.append(('poly', [[fn(r) for r in p] for p in g]))
        elif k == 'point':
            out.append(('point', fn(g)))
        else:
            out.append((None, None))
    return out


def describe_crs(epsg, geographic):
    """Название системы координат простыми словами — для сообщений."""
    if geographic:
        return 'градусы (EPSG:4326)'
    z = utm_zone(epsg)
    if z:
        return f'UTM зона {z[0]}{"N" if z[1] else "S"} (EPSG:{epsg})'
    return f'EPSG:{epsg}' if epsg else 'неизвестная метрическая система'


def check_crs(epsg, geographic, name):
    """Останавливает расчёт, если слой в EPSG:3857 (искажает площади и расстояния)."""
    if not geographic and epsg in (3857, 900913, 3395):
        raise CRSError(f'Слой «{name}» записан в EPSG:{epsg} (веб-Меркатор). В нём площади и расстояния '
                       f'искажены примерно вдвое. Перепроецируйте слой в QGIS в EPSG:4326 или в зону UTM.')


def to_frame(geoms, epsg, geographic, frame, name='слой'):
    """Приводит геометрии слоя к системе кварталов.

    frame — описание системы кварталов: {'proj': LocalProjection или None, 'epsg': код, 'geographic': bool}.
    Если слой уже в системе кварталов — геометрии возвращаются без изменений (как в ноутбуке).
    Возвращает (геометрии, текст о пересчёте или None).
    """
    check_crs(epsg, geographic, name)
    proj = frame['proj']
    if geographic:
        if proj is not None:                      # кварталы в градусах — как в ноутбуке
            return project(geoms, proj), None
        z = utm_zone(frame['epsg'])
        if z:
            return _map_geoms(geoms, lambda r: lonlat_to_utm(r, *z)), f'«{name}»: градусы → {describe_crs(frame["epsg"], False)}'
        raise CRSError(f'Слой «{name}» в градусах, а кварталы в {describe_crs(frame["epsg"], False)}. '
                       f'Такой пересчёт программа не делает: перепроецируйте слой в QGIS в систему кварталов.')
    # слой в метрах
    if proj is None and (epsg == frame['epsg'] or epsg is None or frame['epsg'] is None):
        return geoms, None
    zs = utm_zone(epsg)
    if zs is None:
        raise CRSError(f'Слой «{name}» в {describe_crs(epsg, False)}, кварталы — в {describe_crs(frame["epsg"], frame["geographic"])}. '
                       f'Программа умеет пересчитывать только градусы и зоны UTM. Перепроецируйте слой в QGIS в систему кварталов.')
    if proj is not None:
        return _map_geoms(geoms, lambda r: proj.xy(utm_to_lonlat(r, *zs))), f'«{name}»: {describe_crs(epsg, False)} → метры (кварталы в градусах)'
    zt = utm_zone(frame['epsg'])
    if zt is None:
        raise CRSError(f'Слой «{name}» в {describe_crs(epsg, False)}, кварталы — в {describe_crs(frame["epsg"], False)}. '
                       f'Перепроецируйте слой в QGIS в систему кварталов.')
    return _map_geoms(geoms, lambda r: lonlat_to_utm(utm_to_lonlat(r, *zs), *zt)), \
        f'«{name}»: {describe_crs(epsg, False)} → {describe_crs(frame["epsg"], False)}'
