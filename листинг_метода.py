# ================================================================================================
# ЛИСТИНГ. Метод сравнения сочетаний функций при изменении назначения территории
# Ноутбук: метод_сравнения_вариантов.ipynb. Python 3.10+; библиотеки: numpy, pandas, matplotlib.
#
# Порядок работы: эксперт заполняет анкету данных (блок 0) → проверка данных → таблица кварталов (шаги 1–4)
# → сравнение вариантов для территории (шаги 5–6) → проверка устойчивости (шаг 7)
# → карта и слой для QGIS (шаг 8) → файл для веб-страницы (шаг 9).
# ================================================================================================


# ################################################################################################
# БЛОК 0. АНКЕТА ДАННЫХ
# Пути к слоям пользователя, имена полей, номера кварталов территории. Единственная часть,
# которую заполняет эксперт.
# ################################################################################################

# ===== ШАГ 0. ВАШИ ДАННЫЕ — заполняется только эта ячейка =====
ДАННЫЕ = dict(
    название='Мой город',
    код='moy_gorod',                  # короткое имя для файлов результатов (латиницей, без пробелов)
    режим='слои',                     # 'слои' — кварталы, здания и сервисы отдельными слоями
                                      # 'таблица' — к кварталам уже присоединены здания и сервисы (см. пример Гатчины)
    кварталы=dict(
        файл='data/moy_gorod/кварталы.geojson',
        поле_номера='block_id',       # поле с номером квартала; None — пронумеровать по порядку
    ),
    здания=dict(
        файл='data/moy_gorod/здания.geojson',
        поле_жилое='is_living',       # жилое ли здание: 1/0, True/False, да/нет
        поле_этажность='storeys',     # число этажей; если пусто — 1 этаж
        поле_площадь_застройки=None,  # None — по контуру здания
        поле_жилая_площадь=None,      # None — поэтажная площадь × k_liv
        поле_жители=None,             # None — жилая площадь ÷ q
    ),
    сервисы=dict(
        файл='data/moy_gorod/сервисы',   # папка (один файл = один тип), один файл или список: ['…/сервисы', '…/промышленность']
        поле_типа=None,               # для одного файла: 'type' или список полей OSM ['amenity', 'shop', 'office', 'tourism']
        поле_мест='capacity',         # число мест у школ и детских садов
    ),
    зоны=dict(                        # необязательно: если зон нет, оставьте файл=None
        файл=None,
        поле_кода=None,
        правила=[('ТП', 'П'), ('ТД', 'ОД')],   # нежилое здание без сервисов: код зоны начинается с «ТП» → П, «ТД» → ОД, иначе прочее
    ),
    территория=[],                    # номера кварталов, где меняется назначение, например [322, 323, 377]
)
ТАБЛИЦА_ГРУПП = 'таблица_групп_сервисов.csv'


# ################################################################################################
# БЛОК 0А. ПРИМЕРЫ ЗАПОЛНЕНИЯ
# Анкета для Васильевского острова (режим «слои») и Гатчины (режим «таблица»).
# ПРИМЕР = None — считаются данные из блока 0.
# ################################################################################################

ПРИМЕР = None    # None — ваши данные из шага 0; 'spb', 'vysotsk' или 'gatchina' — пример

ПРИМЕРЫ = {
    'spb': dict(
        название='Санкт-Петербург, Васильевский остров', код='spb', режим='слои',
        кварталы=dict(файл='data/spb_vasilievsky/blocks.geojson', поле_номера='block_id'),
        здания=dict(файл='data/spb_vasilievsky/buildings.geojson', поле_жилое='is_living', поле_этажность='storeys_count',
                    поле_площадь_застройки='building_area', поле_жилая_площадь='living_area', поле_жители='population_balanced'),
        сервисы=dict(файл='data/spb_vasilievsky/services', поле_типа=None, поле_мест='capacity'),
        зоны=dict(файл='data/spb_vasilievsky/functional_zones.geojson', поле_кода='functional_zone', правила=[('ТП', 'П'), ('ТД', 'ОД')]),
        территория=[8346, 9366, 2059],          # промзона у наб. Макарова
    ),
    'gatchina': dict(
        название='Гатчина', код='gatchina', режим='таблица',
        кварталы=dict(файл='data/gatchina/blocks_with_services.gpkg', поле_номера='block_id'),
        готовая_таблица=dict(поле_жители='population', поле_жилая_площадь='living_area', поле_нежилая_площадь='non_living_area',
                             поле_зоны='land_use', префикс_числа='count_', префикс_мест='capacity_',
                             правила=[('LandUse.INDUSTRIAL', 'П'), ('LandUse.BUSINESS', 'ОД')]),
        территория=[322, 323, 377],             # промзона
    ),
    'vysotsk': dict(
        название='Высоцк', код='vysotsk', режим='слои',
        кварталы=dict(файл='data/vysotsk/кварталы.geojson', поле_номера=None),   # кварталы пересохранены в EPSG:4326, номер — по порядку
        здания=dict(файл='data/vysotsk/здания.geojson', поле_жилое='is_living', поле_этажность='number_of_floors',
                    поле_площадь_застройки='footprint_area', поле_жилая_площадь='living_area', поле_жители='population'),
        сервисы=dict(файл=['data/vysotsk/сервисы', 'data/vysotsk/промышленность'], поле_типа=None, поле_мест='capacity'),
        зоны=dict(файл='data/vysotsk/зоны.geojson', поле_кода='Зона', правила=[('Производственная', 'П'), ('Общественно-деловая', 'ОД')]),
        территория=[362, 387, 392],             # производственные кварталы у жилой застройки (пример)
    ),
}


# ################################################################################################
# БЛОК 0Б. ПАРАМЕТРЫ МЕТОДА И ВАРИАНТЫ
# КИТ, радиусы R и r, нормы; варианты — доли поэтажной площади Ж, К, ОД, П.
# ################################################################################################

P = dict(
    kit=1.4,            # КИТ: поэтажная площадь / площадь территории
    R=800,              # радиус окружения, м
    r=500,              # радиус пешей доступности функции, м
    q=30,               # м² жилой площади на человека
    k_liv=0.7,          # доля жилой площади в поэтажной
    a_К=35, a_ОД=20, a_П=70, a_X=50,   # м² поэтажной площади на одно рабочее место
    n_school=110, n_kinder=60,          # мест в школах и детских садах на 1000 жителей
    S_min=200,          # нежилые здания меньше этой площади застройки не учитываются, м²
    storeys_default=1,  # этажность, если она не указана
    builtin=True,       # учитывать встроенные помещения: сервисы К и ОД внутри контура жилого дома
    builtin_s0=100,     # площадь одного встроенного помещения, м² (допущение; проверка 50 и 300)
    builtin_share=0.5,  # встроенные помещения занимают не больше этой доли первого этажа (уличная сторона)
    builtin_min_storeys=2,   # правило применяется к жилым домам не ниже стольких этажей
)
SCN = {   # доли поэтажной площади, %: Ж — жильё, К — торговля и услуги, ОД — общественно-деловая, П — производство
    'С0 Ж+К':  {'Ж': 85, 'К': 15, 'ОД': 0,  'П': 0},
    'С1 Ж+ОД': {'Ж': 60, 'К': 10, 'ОД': 30, 'П': 0},
    'С2 ОД+П': {'Ж': 0,  'К': 10, 'ОД': 40, 'П': 50},
    'С3 Ж+П':  {'Ж': 50, 'К': 10, 'ОД': 0,  'П': 40},
}
OUT = 'results'


# ################################################################################################
# БЛОК 1. СЛУЖЕБНЫЕ ФУНКЦИИ: ЧТЕНИЕ СЛОЁВ И ГЕОМЕТРИЯ
# Чтение GeoJSON/GeoPackage, перевод в метры, площади, «точка в полигоне», расстояния.
# ################################################################################################

# ===== СЛУЖЕБНЫЕ ФУНКЦИИ (менять не нужно) =====
import json, os, sqlite3, struct, math
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
        import re
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


# ################################################################################################
# БЛОК 2. ТАБЛИЦА ГРУПП И ПРОВЕРКА ДАННЫХ
# Чтение таблицы групп сервисов, перевод анкеты в настройки, проверка слоёв до расчёта.
# ################################################################################################

# ===== ТАБЛИЦА ГРУПП И ПРОВЕРКА ДАННЫХ =====
FUNCS = ['К', 'ОД', 'П']
GROUPS_ALLOWED = ['К', 'ОД', 'П', 'школа', 'детский_сад', 'метро', 'остановка', 'нет']



# --- Читает таблицу групп (CSV, открывается в Excel): тип сервиса → группа (К, ОД, П, школа,
#     детский_сад, метро, остановка, нет). Тип ищется по столбцу «тип», затем по тегам OSM из «тег_OSM».
#     Группа в таблице задана по коду ВРИ: К — 3.3, 4.2, 4.3, 4.4, 4.6; ОД — 3.2.3, 3.5.2, 3.6.1, 3.8, 4.1, 4.5, 4.7; П — 6.x.
def load_group_table(path):
    """Таблица групп: какой тип сервиса к какой группе относится. Ключ — значение «тип» и теги из «тег_OSM»."""
    if not os.path.exists(path):
        raise FileNotFoundError(f'Нет таблицы групп сервисов: {path}. Она лежит рядом с ноутбуком (таблица_групп_сервисов.csv).')
    t = pd.read_csv(path, sep=None, engine='python', encoding='utf-8-sig', dtype=str).fillna('')
    t.columns = [c.strip() for c in t.columns]
    miss = {'тип', 'группа'} - set(t.columns)
    if miss:
        raise ValueError(f'В таблице групп нет столбцов: {", ".join(sorted(miss))}. Нужны столбцы «тип» и «группа».')
    bad = t[~t['группа'].str.strip().isin(GROUPS_ALLOWED)]
    if len(bad):
        raise ValueError('В таблице групп неизвестные группы: ' + ', '.join(f'{r.тип} → «{r.группа}»' for r in bad.itertuples())
                         + '. Допустимо: ' + ', '.join(GROUPS_ALLOWED))
    groups = {}
    for r in t.itertuples():
        groups[r.тип.strip()] = r.группа.strip()
    for r in t.itertuples():       # теги OSM — второй способ найти тип
        for tag in str(getattr(r, 'тег_OSM', '')).split(','):
            if tag.strip():
                groups.setdefault(tag.strip(), r.группа.strip())
    return groups



# --- Переводит анкету шага 0 (пути к слоям и имена полей) во внутренние настройки.
def cfg_from_form(Д):
    """Переводит анкету шага 0 во внутренние настройки."""
    q, b, s, z, tb = Д.get('кварталы') or {}, Д.get('здания') or {}, Д.get('сервисы') or {}, Д.get('зоны') or {}, Д.get('готовая_таблица') or {}
    return dict(
        name=Д.get('название', ''), code=Д.get('код', 'город'), mode=Д.get('режим', 'слои'),
        blocks=q.get('файл'), block_id_field=q.get('поле_номера'),
        buildings=b.get('файл'),
        fields=dict(is_living=b.get('поле_жилое'), storeys=b.get('поле_этажность'), footprint=b.get('поле_площадь_застройки'),
                    living_area=b.get('поле_жилая_площадь'), population=b.get('поле_жители')),
        services=s.get('файл'), service_type_field=s.get('поле_типа'), capacity_field=s.get('поле_мест'),
        zones=z.get('файл'), zone_field=z.get('поле_кода'), zone_rules=list(z.get('правила') or []),
        table=dict(population=tb.get('поле_жители'), living_area=tb.get('поле_жилая_площадь'), non_living_area=tb.get('поле_нежилая_площадь'),
                   zone_field=tb.get('поле_зоны'), count_prefix=tb.get('префикс_числа', 'count_'), capacity_prefix=tb.get('префикс_мест', 'capacity_'),
                   zone_rules=list(tb.get('правила') or [])),
        territory=[int(i) for i in Д.get('территория') or []],
    )


_CACHE = {}

# --- Читает слой один раз: проверка данных и расчёт используют один результат.
def read_cached(path):
    """Читает слой один раз за сеанс (проверка и расчёт используют один и тот же результат)."""
    key = (path, os.path.getmtime(path))
    if key not in _CACHE:
        _CACHE[key] = read_layer(path)
    return _CACHE[key]



# --- Признак «жилое здание»: жилыми считаются значения 1, True, да, yes.
def truthy(col):
    """Признак «жилое»: 1/0, True/False, да/нет, yes/no."""
    s = col.astype(str).str.strip().str.lower()
    return s.isin(['1', '1.0', 'true', 'да', 'yes', 'y', 'жилое', 'жилой'])



# --- Тип сервиса: имя файла (папка «один файл — один тип»), значение поля типа
#     или для выгрузки OSM — «поле=значение» первого непустого поля тега (например, amenity=school).
def service_type_of(df, field, fallback):
    """Тип сервиса: имя файла; значение поля; для списка полей OSM — «поле=значение» первого непустого поля."""
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


def service_files(src):
    """Файлы сервисов: путь или список путей; папка → все .geojson/.gpkg в ней (тип = имя файла)."""
    out = []
    for p in (src if isinstance(src, (list, tuple)) else [src]):
        if os.path.isdir(p):
            out += [(os.path.join(p, x), True) for x in sorted(os.listdir(p)) if x.endswith(('.geojson', '.gpkg'))]
        else:
            out.append((p, False))
    return out



# --- ШАГ 0б. Проверка данных до расчёта: есть ли файлы и поля из анкеты, уникальны ли номера кварталов,
#     есть ли кварталы территории, сколько жилых зданий и зданий без этажности, какие типы сервисов
#     попали в группы и какие не найдены в таблице, есть ли места у школ и садов, одна ли система координат.
#     При ошибках расчёт останавливается с подсказкой.
def check_inputs(cfg, groups):
    """Шаг 0б. Проверка до расчёта: файлы, поля, системы координат, типы сервисов, номера территории."""
    errors, warns = [], []
    ok = lambda m: print('  ✓ ' + m)
    def err(m): errors.append(m); print('  ✕ ' + m)
    def warn(m): warns.append(m); print('  ! ' + m)
    def need_field(df, name, what, required=True):
        if name is None:
            return False
        if name in df.columns:
            return True
        (err if required else warn)(f'{what}: нет поля «{name}». Поля слоя: {", ".join(map(str, df.columns[:25]))}')
        return False
    crs_seen = {}
    def open_layer(path, what, kinds):
        if not path:
            err(f'{what}: путь не указан'); return None
        if not os.path.exists(path):
            err(f'{what}: файл не найден — {path}'); return None
        try:
            df, g, geo = read_cached(path)
        except Exception as e:
            err(f'{what}: файл не читается — {e}'); return None
        n_ok = sum(1 for k, _ in g if k in kinds)
        epsg = df.attrs.get('epsg')
        crs = 'градусы (EPSG:4326)' if geo else f'EPSG:{epsg}'
        print(f'{what}: {path}\n  объектов {len(df)}, из них {"полигонов" if "poly" in kinds else "точек и полигонов"} {n_ok}; координаты: {crs}')
        if epsg == 3857:
            err(f'{what}: Web Mercator (EPSG:3857) искажает расстояния в 1,7–2 раза — пересохраните в EPSG:4326 или UTM')
        if n_ok == 0:
            err(f'{what}: нет объектов нужного типа ({"полигоны" if kinds == ("poly",) else "точки или полигоны"})')
        crs_seen[what] = 'градусы' if geo else epsg
        return df

    # 1. Кварталы
    q = open_layer(cfg['blocks'], 'Кварталы', ('poly',))
    if q is not None:
        f = cfg['block_id_field']
        if f is None:
            warn('Кварталы: поле номера не задано — номера по порядку 0, 1, 2…')
        elif need_field(q, f, 'Кварталы'):
            ids = pd.to_numeric(q[f], errors='coerce')
            if ids.isna().any() or (ids % 1 != 0).any():
                err(f'Кварталы: в поле «{f}» есть пустые или нецелые номера ({int(ids.isna().sum())})')
            elif ids.duplicated().any():
                err(f'Кварталы: номера повторяются, например {ids[ids.duplicated()].astype(int).head(5).tolist()}')
            else:
                ok(f'номера кварталов уникальны (поле «{f}»)')
            miss = [i for i in cfg['territory'] if i not in set(ids.dropna().astype(int))]
            if not cfg['territory']:
                err('Территория: не заданы номера кварталов (ключ «территория»)')
            elif miss:
                err(f'Территория: кварталов {miss} нет в слое')
            else:
                ok(f'территория: {len(cfg["territory"])} кв. найдены')

    if cfg['mode'] == 'таблица':
        tb = cfg['table']
        if q is not None:
            for k, what in [('population', 'жители'), ('living_area', 'жилая площадь'), ('non_living_area', 'нежилая площадь'), ('zone_field', 'зона')]:
                if need_field(q, tb[k], f'Готовая таблица ({what})', required=k != 'zone_field'):
                    ok(f'поле «{tb[k]}» — {what}')
            cnt = [c for c in q.columns if str(c).startswith(tb['count_prefix'])]
            types = [c[len(tb['count_prefix']):] for c in cnt]
            known = {t: groups[t] for t in types if t in groups}
            unknown = [t for t in types if t not in groups]
            for g in FUNCS:
                lst = ', '.join(t for t, gg in known.items() if gg == g)
                (ok if lst else warn)(f'группа {g}: ' + (lst or 'нет типов сервисов — наличие функции определяется только по нежилой площади'))
            if unknown:
                warn('типов нет в таблице групп (не учитываются): ' + ', '.join(unknown))
            for t in ['school', 'kindergarten']:
                if tb['capacity_prefix'] + t not in q.columns:
                    warn(f'нет поля «{tb["capacity_prefix"] + t}» — вместимость примется равной 0')
    else:
        # 2. Здания
        b = open_layer(cfg['buildings'], 'Здания', ('poly',))
        if b is not None:
            fl = cfg['fields']
            if need_field(b, fl['is_living'], 'Здания (жилое)'):
                n_liv = int(truthy(b[fl['is_living']]).sum())
                (ok if n_liv else err)(f'жилых зданий: {n_liv} из {len(b)} (поле «{fl["is_living"]}»; жилыми считаются 1, True, да)')
            if need_field(b, fl['storeys'], 'Здания (этажность)'):
                st = pd.to_numeric(b[fl['storeys']], errors='coerce')
                share = float((~(st > 0)).mean())
                (warn if share > 0.2 else ok)(f'этажность не указана у {share:.0%} зданий — для них 1 этаж')
            for k, what in [('footprint', 'площадь застройки'), ('living_area', 'жилая площадь'), ('population', 'жители')]:
                if fl[k] is None:
                    print(f'  · {what}: поле не задано — {"по контуру" if k == "footprint" else "поэтажная площадь × k_liv" if k == "living_area" else "жилая площадь ÷ q"}')
                elif need_field(b, fl[k], f'Здания ({what})', required=False):
                    ok(f'{what}: поле «{fl[k]}»')
        # 3. Сервисы
        src = cfg['services']
        srcs = src if isinstance(src, (list, tuple)) else [src]
        missing = [p for p in srcs if not p or not os.path.exists(p)]
        if not src or missing:
            err(f'Сервисы: {"путь не указан" if not src else "не найдено — " + ", ".join(map(str, missing))}')
        else:
            files = service_files(src)
            print(f'Сервисы: {", ".join(srcs)}\n  файлов {len(files)}' + (' (в папке: тип = имя файла)' if any(f for _, f in files) else ''))
            if not files:
                err('Сервисы: нет файлов .geojson или .gpkg')
            types, caps = defaultdict(int), defaultdict(lambda: [0, 0])
            for path, in_folder in files:
                df, g, geo = read_cached(path)
                c = 'градусы' if geo else df.attrs.get('epsg')
                if crs_seen.get('Сервисы', c) != c:
                    err(f'Сервисы: файл {os.path.basename(path)} в другой системе координат ({c})')
                crs_seen['Сервисы'] = c
                fld = None if in_folder else cfg['service_type_field']
                if fld is not None:
                    flist = fld if isinstance(fld, (list, tuple)) else [fld]
                    if not any(x in df for x in flist):
                        err(f'Сервисы: нет поля типа {flist}. Поля: {", ".join(map(str, df.columns[:25]))}'); continue
                tt = service_type_of(df, fld, os.path.splitext(os.path.basename(path))[0])
                capf = cfg['capacity_field']
                cap = pd.to_numeric(df[capf], errors='coerce') if capf and capf in df else pd.Series(np.nan, index=df.index)
                for t, c in zip(tt, cap):
                    types[t] += 1
                    if groups.get(t) in ('школа', 'детский_сад'):
                        caps[groups[t]][0] += 1; caps[groups[t]][1] += int(c > 0) if c == c else 0
            for g in FUNCS + ['метро', 'остановка']:
                lst = [f'{t} ({n})' for t, n in sorted(types.items()) if groups.get(t) == g]
                (ok if lst else warn)(f'группа {g}: ' + (', '.join(lst) if lst else 'нет объектов'))
            for g, what in [('школа', 'школ'), ('детский_сад', 'детских садов')]:
                n, with_cap = caps[g]
                if n == 0:
                    warn(f'{what}: нет ни одного объекта — места примутся равными 0')
                else:
                    (ok if with_cap == n else warn)(f'{what}: {n}, с числом мест — {with_cap}' + ('' if with_cap == n else ' (без мест считаются как 0 мест)'))
            unknown = sorted((t for t in types if t not in groups and t), key=lambda t: -types[t])
            if unknown:
                warn('типов нет в таблице групп — не учитываются: ' + ', '.join(f'{t} ({types[t]})' for t in unknown[:30])
                     + ('…' if len(unknown) > 30 else '') + '. Если тип нужен — добавьте строку в таблицу групп.')
            ignored = sorted(t for t in types if groups.get(t) == 'нет')
            if ignored:
                print('  · не учитываются по таблице групп (группа «нет»): ' + ', '.join(ignored))
        # 4. Зоны
        if cfg['zones']:
            z = open_layer(cfg['zones'], 'Зоны', ('poly',))
            if z is not None and need_field(z, cfg['zone_field'], 'Зоны'):
                codes = z[cfg['zone_field']].astype(str)
                hit = {p: int(codes.str.startswith(p).sum()) for p, _ in cfg['zone_rules']}
                ok('правила зон: ' + ', '.join(f'«{p}…» → {g}: {hit[p]} зон' for p, g in cfg['zone_rules']))
        else:
            print('Зоны: не заданы — нежилые здания без сервисов пойдут в «прочее» (X)')
    if len(set(map(str, crs_seen.values()))) > 1:
        err('Слои в разных системах координат: ' + ', '.join(f'{k} — {v}' for k, v in crs_seen.items()) + '. Сохраните все слои в одной системе: в QGIS правый щелчок по слою → «Экспорт» → «Сохранить объекты как…» → СК EPSG:4326.')
    print()
    if errors:
        raise RuntimeError(f'Ошибок: {len(errors)}. Исправьте анкету в шаге 0 или слои и запустите снова. Чтобы проверить ноутбук на примере, поставьте ПРИМЕР = \'spb\'.')
    print(f'Проверка пройдена. Предупреждений: {len(warns)}. Можно запускать расчёт.')


# ################################################################################################
# БЛОК 3. ФУНКЦИИ ШАГОВ МЕТОДА
# Шаги 1–4: таблица кварталов. Шаги 5–6: окружение и сравнение вариантов.
# ################################################################################################

# ===== ШАГИ МЕТОДА (функции) =====

# --- ШАГ 1. Кварталы: чтение, перевод в метры, площадь, центр;
#     зона — та, в которую попадает центр квартала.
def load_blocks(cfg):
    """Шаг 1. Кварталы: чтение, перевод в метры, площадь, центр, зона."""
    df, geoms, geographic = read_cached(cfg['blocks'])
    df = df.copy()
    epsg = df.attrs.get('epsg')
    idf = cfg.get('block_id_field')
    df['block_id'] = pd.to_numeric(df[idf]).astype(int) if idf and idf in df else np.arange(len(df))
    df['_g'] = geoms
    df = df[[g[0] == 'poly' for g in geoms]].copy()
    df = df.reset_index(drop=True)
    proj = None
    if geographic:
        xy = np.vstack([r for g in df['_g'] for p in g[1] for r in p])
        proj = LocalProjection(xy[:, 0].mean(), xy[:, 1].mean())
        df['polys'] = [project([g], proj)[0][1] for g in df['_g']]
    else:
        df['polys'] = [g[1] for g in df['_g']]
    df['area'] = [poly_area(p) for p in df['polys']]
    c = np.array([centroid(p) for p in df['polys']]); df['cx'], df['cy'] = c[:, 0], c[:, 1]
    df['zone'] = None
    if cfg.get('zones'):
        zdf, zg, zgeo = read_cached(cfg['zones'])
        zg = project(zg, proj) if (zgeo and proj) else zg
        zpolys = [g[1] if g[0] == 'poly' else [] for g in zg]
        k = assign_points(c, zpolys)
        df['zone'] = [zdf[cfg['zone_field']].iloc[i] if i >= 0 else None for i in k]
    elif cfg['mode'] == 'таблица' and cfg['table'].get('zone_field'):
        df['zone'] = df[cfg['table']['zone_field']]
    return df, proj, geographic, epsg



# --- Группа нежилого здания, внутри которого нет сервисов: по началу кода зоны квартала
#     (например, «ТП…» → П, «ТД…» → ОД), иначе X — прочее нежилое.
def zone_group(zone, rules):
    """Группа нежилого здания, внутри которого нет сервисов: по началу кода зоны квартала."""
    z = str(zone or '')
    for prefix, grp in rules:
        if z.startswith(prefix):
            return grp
    return 'X'



# --- ШАГ 2. Сервисы: чтение (папка «один файл — один тип» или один файл с полем типа),
#     точка для каждого объекта, группа по таблице групп.
def read_services(cfg, proj, groups):
    """Шаг 2. Сервисы: папка файлов (тип = имя файла) или один файл с полем типа; группа — по таблице групп."""
    frames = []
    for path, in_folder in service_files(cfg['services']):
        df, g, geo = read_cached(path)
        df = df.copy()
        fld = None if in_folder else cfg['service_type_field']
        df['service_type'] = service_type_of(df, fld, os.path.splitext(os.path.basename(path))[0]).values
        if geo and proj: g = project(g, proj)
        pts = [gg[1] if gg[0] == 'point' else (inner_point(gg[1]) if gg[0] == 'poly' else None) for gg in g]
        df['x'] = [p[0] if p is not None else np.nan for p in pts]; df['y'] = [p[1] if p is not None else np.nan for p in pts]
        capf = cfg['capacity_field']
        df['capacity'] = pd.to_numeric(df[capf], errors='coerce') if capf and capf in df else np.nan
        frames.append(df[['service_type', 'x', 'y', 'capacity']])
    s = pd.concat(frames, ignore_index=True).dropna(subset=['x', 'y'])
    s['group'] = s['service_type'].map(groups).fillna('нет в таблице')
    return s



# --- ШАГИ 2–4, режим «слои».
#      3. Здания и сервисы → точки → номер квартала.
#      4. Поэтажная площадь A = площадь застройки × этажность (нет этажности → 1 этаж);
#         жилая площадь — из атрибута или A × k_liv; жители — из атрибута или жилая площадь / q;
#         встроенные помещения: в жилом доме (≥ 2 этажей) с сервисами К или ОД нежилой считается площадь
#         B = min(n · s0, доля · S), она делится между К и ОД пропорционально числу сервисов; жители не меняются;
#         группа нежилого здания (площадь застройки ≥ S_min): сервисы внутри контура, приоритет П → ОД → К,
#         иначе по зоне; NR_g = сумма A по нежилым зданиям группы g в квартале.
def prepare_from_layers(cfg, P, groups):
    """Шаги 2–4, режим «слои»: сервисы → группы, привязка к кварталам и зданиям, таблица кварталов."""
    blocks, proj, geographic, epsg = load_blocks(cfg)
    report = {'кварталов': len(blocks)}
    allxy = np.vstack([r for p in blocks['polys'] for q in p for r in q]); lo, hi = allxy.min(0) - 50, allxy.max(0) + 50

    # --- сервисы
    s = read_services(cfg, proj, groups)
    s = s[(s.x >= lo[0]) & (s.x <= hi[0]) & (s.y >= lo[1]) & (s.y <= hi[1])].reset_index(drop=True)
    s['block'] = assign_points(s[['x', 'y']].to_numpy(), list(blocks['polys']))
    report['сервисов в кварталах'] = int((s.block >= 0).sum())
    for g in FUNCS + ['школа', 'детский_сад']:
        report[f'  из них {g}'] = int(((s.block >= 0) & (s.group == g)).sum())

    # --- здания
    bdf, bg, bgeo = read_cached(cfg['buildings'])
    if bgeo and proj: bg = project(bg, proj)
    keep = [i for i, g in enumerate(bg) if g[0] == 'poly']
    bdf = bdf.iloc[keep].reset_index(drop=True); bpolys = [bg[i][1] for i in keep]
    ip = np.array([inner_point(p) for p in bpolys])
    inbox = (ip[:, 0] >= lo[0]) & (ip[:, 0] <= hi[0]) & (ip[:, 1] >= lo[1]) & (ip[:, 1] <= hi[1])
    bdf = bdf[inbox].reset_index(drop=True); bpolys = [p for p, k in zip(bpolys, inbox) if k]; ip = ip[inbox]
    bdf['block'] = assign_points(ip, list(blocks['polys']))
    sel = bdf.block >= 0; bdf = bdf[sel].reset_index(drop=True); bpolys = [p for p, k in zip(bpolys, sel) if k]
    report['зданий в кварталах'] = len(bdf)
    f = cfg['fields']
    bdf['footprint'] = pd.to_numeric(bdf[f['footprint']], errors='coerce').fillna(0) if f.get('footprint') in bdf else [poly_area(p) for p in bpolys]
    bdf['living'] = truthy(bdf[f['is_living']])
    st = pd.to_numeric(bdf[f['storeys']], errors='coerce') if f.get('storeys') in bdf else pd.Series(np.nan, index=bdf.index)
    st = st.where(st > 0)
    report['зданий без этажности (принят 1 этаж)'] = int(st.isna().sum())
    st = st.fillna(P['storeys_default'])
    bdf['floor_area'] = bdf['footprint'] * st

    # --- встроенные помещения жилого дома: B = min(n · s0, доля · S), где n — число сервисов К и ОД в контуре дома,
    #     s0 — площадь одного помещения, S — площадь застройки; B делится между К и ОД пропорционально числу сервисов
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
            n_srv = c['К'] + c['ОД']
            lim = bdf.at[i, 'footprint'] * P.get('builtin_share', 1.0)      # доступная часть первого этажа
            area = min(lim, n_srv * P['builtin_s0']) if P.get('builtin_s0') else lim
            capped += int(bool(P.get('builtin_s0')) and n_srv * P['builtin_s0'] > lim)
            for g in ['К', 'ОД']:
                bdf.at[i, 'bi_' + g] = area * c[g] / n_srv
        report['  домов, где площадь ограничена долей первого этажа'] = capped
        report['жилых домов со встроенными помещениями'] = len(cnt)
        report['  сервисов К и ОД в этих домах'] = int((own >= 0).sum())
        report['  встроенная площадь К / ОД, м²'] = f"{int(round(bdf['bi_К'].sum()))} / {int(round(bdf['bi_ОД'].sum()))}"
    res_floor = bdf['floor_area'] - bdf['bi_К'] - bdf['bi_ОД']       # поэтажная площадь без встроенных помещений
    if f.get('living_area') in bdf:
        bdf['living_area'] = pd.to_numeric(bdf[f['living_area']], errors='coerce').fillna(res_floor * P['k_liv'])
        has_bi = (bdf['bi_К'] + bdf['bi_ОД']) > 0                     # только дома со встроенными помещениями
        bdf['living_area'] = np.where(has_bi, np.minimum(bdf['living_area'], res_floor * P['k_liv']), bdf['living_area'])
    else:
        bdf['living_area'] = res_floor * P['k_liv']
    bdf.loc[~bdf.living, 'living_area'] = 0
    if f.get('population') in bdf:
        bdf['pop'] = pd.to_numeric(bdf[f['population']], errors='coerce').fillna(0)
    else:
        bdf['pop'] = bdf['living_area'] / P['q']
    bdf.loc[~bdf.living, 'pop'] = 0

    # --- группа нежилого здания: сервисы внутри контура (П > ОД > К), иначе зона квартала
    nr = (~bdf.living) & (bdf['footprint'] >= P['S_min'])
    nr_idx = np.where(nr)[0]
    fs = s[s.group.isin(FUNCS)].reset_index(drop=True)
    owner = assign_points(fs[['x', 'y']].to_numpy(), [bpolys[i] for i in nr_idx]) if len(nr_idx) else np.full(len(fs), -1)
    found = defaultdict(set)
    for o, g in zip(owner, fs.group):
        if o >= 0: found[nr_idx[o]].add(g)
    rules = cfg.get('zone_rules', [])
    bdf['group'] = None
    for i in nr_idx:
        gs = found.get(i, set())
        bdf.at[i, 'group'] = 'П' if 'П' in gs else 'ОД' if 'ОД' in gs else 'К' if 'К' in gs else zone_group(blocks.at[bdf.at[i, 'block'], 'zone'], rules)
    for g in FUNCS + ['X']:
        report[f'нежилых зданий в группе {g}'] = int((bdf.group == g).sum())

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
    return finish_table(t, blocks, P, proj, pts, report, epsg)



# --- ШАГИ 2–4, режим «таблица» (данные Гатчины): готовые жители и площади по кварталу;
#     нежилая площадь относится к группе по зоне квартала; число сервисов и мест — по столбцам count_/capacity_
#     и таблице групп.
def prepare_from_table(cfg, P, groups):
    """Шаги 2–4, режим «таблица»: к кварталам уже присоединены здания и сервисы (как в данных Гатчины)."""
    blocks, proj, geographic, epsg = load_blocks(cfg)
    f = cfg['table']; t = blocks[['block_id', 'zone', 'area', 'cx', 'cy']].copy()
    t['pop'] = pd.to_numeric(blocks[f['population']], errors='coerce').fillna(0)
    t['liv'] = pd.to_numeric(blocks[f['living_area']], errors='coerce').fillna(0)
    nonres = pd.to_numeric(blocks[f['non_living_area']], errors='coerce').fillna(0)
    grp = np.array([zone_group(z, f['zone_rules']) for z in blocks['zone']])
    for g in FUNCS + ['X']:
        t['nr_' + g] = np.where(grp == g, nonres, 0.0)
    for g in FUNCS:
        cols = [c for c in blocks.columns if str(c).startswith(f['count_prefix']) and groups.get(str(c)[len(f['count_prefix']):]) == g]
        t['n_' + g] = blocks[cols].apply(pd.to_numeric, errors='coerce').fillna(0).sum(axis=1).astype(int) if cols else 0
    for g, col in [('школа', 'cap_school'), ('детский_сад', 'cap_kinder')]:
        cols = [c for c in blocks.columns if str(c).startswith(f['capacity_prefix']) and groups.get(str(c)[len(f['capacity_prefix']):]) == g]
        t[col] = blocks[cols].apply(pd.to_numeric, errors='coerce').fillna(0).sum(axis=1) if cols else 0.0
    report = {'кварталов': len(t), 'режим': 'готовая таблица кварталов (нежилая площадь — по зоне квартала)'}
    return finish_table(t, blocks, P, proj, {'метро': np.zeros((0, 2)), 'остановка': np.zeros((0, 2))}, report, epsg)



# --- Общая часть шага 4: рабочие места J = NR_К/a_К + NR_ОД/a_ОД + NR_П/a_П + NR_X/a_X;
#     «функция есть», если в квартале есть сервис этой группы или нежилая площадь этой группы;
#     K_ref = все рабочие места / все жители загруженной территории.
def finish_table(t, blocks, P, proj, pts, report, epsg):
    """Рабочие места и наличие функций — общая часть для обоих режимов."""
    t['jobs'] = t['nr_К'] / P['a_К'] + t['nr_ОД'] / P['a_ОД'] + t['nr_П'] / P['a_П'] + t['nr_X'] / P['a_X']
    for g in FUNCS:
        t['есть_' + g] = (t['n_' + g] > 0) | (t['nr_' + g] > 0)
    report['жителей'] = int(round(t['pop'].sum())); report['рабочих мест (оценка)'] = int(round(t['jobs'].sum()))
    report['K_ref — рабочих мест на жителя в среднем'] = round(float(t['jobs'].sum() / t['pop'].sum()), 3)
    report['мест в школах / детских садах'] = f"{int(t['cap_school'].sum())} / {int(t['cap_kinder'].sum())}"
    return {'table': t, 'polys': list(blocks['polys']), 'geom': BlockGeometry(list(blocks['polys'])),
            'orig': list(blocks['_g']), 'proj': proj, 'pts': pts, 'report': report, 'epsg': epsg}



# --- ШАГИ 5–6. Вход: таблица кварталов, номера кварталов территории, параметры, варианты.
#      5. Окружение E — кварталы, центр которых не дальше R от границы территории.
#      6. Для каждого варианта:
#         F = площадь × КИТ;  N = F × доля Ж × k_liv / q;  J = F × Σ(доля группы / площадь на место);
#         K = (рабочие места E + J) / (жители E + N), сравнивается с K_ref;
#         доступ: была ли функция в радиусе r у жилого квартала E «до» и есть ли «после»
#           (в варианте на территории — только новые функции); считаются жители, получившие и потерявшие её;
#         школы и сады: потребность = (жители E + N) × норма / 1000; обеспеченность = места в E / потребность;
#           не хватает мест = потребность − места (если больше 0); ученики с территории = N × норма / 1000.
#     Выход: таблица сравнения, сводка об окружении, данные для карты.
def compare(city, T_ids, P, SCN):
    """Шаги 5–6: окружение территории и сравнение вариантов. Возвращает таблицу сравнения и данные для карты."""
    t = city['table']; n = len(t); G = city['geom']
    T = [int(np.where(t.block_id == i)[0][0]) for i in T_ids]; inT = np.zeros(n, bool); inT[T] = True
    C = t[['cx', 'cy']].to_numpy()
    distT = np.min([dist_points_to_polys(C, city['polys'][k]) for k in T], axis=0)
    E = np.where(~inT & (distT <= P['R']))[0]
    S = t.area.iloc[T].sum(); F = S * P['kit']
    popE, jobsE = t['pop'].iloc[E].sum(), t['jobs'].iloc[E].sum()
    Kref = t['jobs'].sum() / t['pop'].sum()
    popA, jobsA = t['pop'].sum(), t['jobs'].sum()                    # все загруженные кварталы
    popT0, jobsT0 = t['pop'].iloc[T].sum(), t['jobs'].iloc[T].sum()  # территория в нынешнем виде
    pres = {g: t['есть_' + g].to_numpy() for g in FUNCS}
    near = {b: G.dist_from_point(*C[b]) <= P['r'] for b in E if t['pop'].iloc[b] > 0}
    Tpolys = [p for k in T for p in city['polys'][k]]
    rows, effect = {}, {}
    for name, sh in [('Как есть', None)] + list(SCN.items()):
        if sh is None:
            N, J, d = t['pop'].iloc[T].sum(), t['jobs'].iloc[T].sum(), None
            capS = t.cap_school.iloc[list(E) + T].sum(); capK = t.cap_kinder.iloc[list(E) + T].sum()
        else:
            tot = sum(sh.values()); d = {k: v / tot for k, v in sh.items()}
            N = F * d['Ж'] * P['k_liv'] / P['q']
            J = F * (d['К'] / P['a_К'] + d['ОД'] / P['a_ОД'] + d['П'] / P['a_П'])
            capS, capK = t.cap_school.iloc[E].sum(), t.cap_kinder.iloc[E].sum()   # существующее на территории сносится
        K = (jobsE + J) / (popE + N)
        Kall = (jobsA - jobsT0 + J) / (popA - popT0 + N)             # то же по всем загруженным кварталам
        acc, eff = {}, {}
        if d is not None:
            for g in FUNCS:
                gain = lost = 0.0
                for b, nb in near.items():
                    before = bool((nb & pres[g]).any())
                    after = bool((nb & pres[g] & ~inT).any()) or (d[g] > 0 and distT[b] <= P['r'])
                    if not before and after: gain += t['pop'].iloc[b]; eff[b] = eff.get(b, 0) + 1
                    if before and not after: lost += t['pop'].iloc[b]; eff[b] = eff.get(b, 0) - 1
                acc[g] = (gain, lost)
        effect[name] = eff
        needS, needK = (popE + N) * P['n_school'] / 1000, (popE + N) * P['n_kinder'] / 1000
        rows[name] = {
            'Жители на территории N': int(round(N)), 'Рабочие места на территории J': int(round(J)),
            'Изменение рабочих мест к нынешним': '—' if d is None else int(round(J - jobsT0)),
            'Доля нежилых площадей, %': '' if d is None else round(100 * (1 - d['Ж'])),
            'Работа на жителя K: окружение': round(float(K), 2), 'Работа на жителя K: все данные': round(float(Kall), 2),
            **{f'Доступ к {g}: получают / теряют, жителей': ('—' if d is None else f'+{acc[g][0]:,.0f} / −{acc[g][1]:,.0f}'.replace(',', ' ')) for g in FUNCS},
            'Школы: ученики с территории': int(round(N * P['n_school'] / 1000)),
            'Школы: обеспеченность окружения, %': int(round(100 * capS / needS)) if needS > 0 else '',
            'Школы: не хватает мест': int(round(max(0.0, needS - capS))),
            'Сады: дети с территории': int(round(N * P['n_kinder'] / 1000)),
            'Сады: обеспеченность окружения, %': int(round(100 * capK / needK)) if needK > 0 else '',
            'Сады: не хватает мест': int(round(max(0.0, needK - capK))),
        }
    out = pd.DataFrame(rows)
    info = {'кварталов на территории': len(T), 'площадь территории, га': round(float(S) / 1e4, 1), 'поэтажная площадь F, м²': int(round(F)),
            'кварталов в окружении': len(E), 'жителей в окружении': int(round(popE)), 'рабочих мест в окружении': int(round(jobsE)),
            'K_ref': round(float(Kref), 3)}
    if len(city['pts']['метро']): info['до метро, м'] = int(round(dist_points_to_polys(city['pts']['метро'], Tpolys).min()))
    if len(city['pts']['остановка']): info['до остановки, м'] = int(round(dist_points_to_polys(city['pts']['остановка'], Tpolys).min()))
    return out, info, {'T': T, 'E': E, 'effect': effect}


# ################################################################################################
# БЛОК 4. ЗАПУСК ПРОВЕРКИ ДАННЫХ
# Выбирает анкету (свою или пример), читает таблицу групп, печатает отчёт проверки.
# ################################################################################################

import time
Д = ПРИМЕРЫ[ПРИМЕР] if ПРИМЕР else ДАННЫЕ
cfg = cfg_from_form(Д)
GROUPS = load_group_table(ТАБЛИЦА_ГРУПП)
print(f'Набор данных: {cfg["name"]} (режим «{cfg["mode"]}»)\n')
check_inputs(cfg, GROUPS)


# ################################################################################################
# БЛОК 5. ЗАПУСК ШАГОВ 1–4
# Строит таблицу кварталов, печатает отчёт о загрузке, сохраняет results/<код>_таблица_кварталов.csv.
# ################################################################################################

os.makedirs(OUT, exist_ok=True)
КОД = cfg['code']; t0 = time.time()
city = prepare_from_layers(cfg, P, GROUPS) if cfg['mode'] == 'слои' else prepare_from_table(cfg, P, GROUPS)
print(f'Подготовка заняла {time.time() - t0:.0f} с')
for k, v in city['report'].items():
    print(f'  {k}: {v}')
tab = city['table']
tab.drop(columns=['cx', 'cy']).round(1).to_csv(f'{OUT}/{КОД}_таблица_кварталов.csv', index=False, encoding='utf-8-sig')
tab[['block_id', 'zone', 'area', 'pop', 'jobs', 'есть_К', 'есть_ОД', 'есть_П', 'cap_school', 'cap_kinder']].round(0).head(8)


# ################################################################################################
# БЛОК 6. ЗАПУСК ШАГОВ 5–6
# Сравнивает варианты для территории, сохраняет results/<код>_сравнение_вариантов.csv.
# ################################################################################################

T = cfg['territory']
table, info, det = compare(city, T, P, SCN)
for k, v in info.items():
    print(f'{k}: {v}')
table.to_csv(f'{OUT}/{КОД}_сравнение_вариантов.csv', encoding='utf-8-sig')
table


# ################################################################################################
# БЛОК 7. ШАГ 7 — ПРОВЕРКА УСТОЙЧИВОСТИ
# Повторяет сравнение при R = 500/800/1000 м и КИТ = 1,4/2,0: K окружения «как есть», изменение K
# в каждом варианте и нехватка мест в школах. Сохраняет results/<код>_устойчивость.csv.
# ################################################################################################

rows = []
for R in [500, 800, 1000]:
    for kit in [1.4, 2.0]:
        tb, inf, _ = compare(city, T, dict(P, R=R, kit=kit), SCN)
        k = tb.loc['Работа на жителя K: окружение'].astype(float)
        sch = tb.loc['Школы: не хватает мест', list(SCN)]
        rows.append({'R, м': R, 'КИТ': kit, 'кварталов в окружении': inf['кварталов в окружении'],
                     'K окружения как есть': k['Как есть'],
                     **{f'изменение K {s.split()[0]}': round(k[s] - k['Как есть'], 2) for s in SCN},
                     **{f'школы: не хватает мест {s.split()[0]}': sch[s] for s in SCN}})
stab = pd.DataFrame(rows)
stab.to_csv(f'{OUT}/{КОД}_устойчивость.csv', index=False, encoding='utf-8-sig')
stab

# ################################################################################################
# БЛОК 7Б. ШАГ 7б — ПРОВЕРКА ДОПУЩЕНИЯ О ВСТРОЕННЫХ ПОМЕЩЕНИЯХ
# Таблица кварталов и сравнение вариантов пересчитываются без встроенных помещений и при s0 = 50, 100, 300 м².
# Сохраняет results/<код>_встроенные.csv. Только для режима «слои».
# ################################################################################################

if cfg['mode'] == 'слои':
    rows = []
    for name, pp in [('без встроенных', dict(P, builtin=False)), ('s0 = 50 м²', dict(P, builtin_s0=50)),
                     ('s0 = 100 м²', dict(P, builtin_s0=100)), ('s0 = 300 м²', dict(P, builtin_s0=300))]:
        c2 = prepare_from_layers(cfg, pp, GROUPS); t2 = c2['table']
        tb, inf, _ = compare(c2, T, pp, SCN)
        rows.append({'расчёт': name,
                     'встроенная площадь К, м²': int(round(t2['встр_К'].sum())), 'встроенная площадь ОД, м²': int(round(t2['встр_ОД'].sum())),
                     'рабочих мест': int(round(t2['jobs'].sum())), 'K_ref': round(float(t2['jobs'].sum() / t2['pop'].sum()), 3),
                     **{f'K окружения {s.split()[0]}': tb.loc['Работа на жителя K: окружение', s] for s in ['Как есть'] + list(SCN)}})
    bi = pd.DataFrame(rows)
    bi.to_csv(f'{OUT}/{КОД}_встроенные.csv', index=False, encoding='utf-8-sig')
    display(bi) if 'display' in globals() else print(bi.to_string(index=False))
else:
    print('Режим «таблица»: слоя зданий нет, встроенные помещения не учитываются.')



# ################################################################################################
# БЛОК 8. ШАГ 8 — КАРТА И СЛОЙ ДЛЯ QGIS
# Рисует территорию, окружение и изменение доступа; сохраняет PNG и GeoJSON для QGIS.
# ################################################################################################

import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
SHOW = 'С1 Ж+ОД'   # какой вариант показать на карте

eff = det['effect'][SHOW]; inT = set(det['T']); inE = set(det['E'].tolist())
verts, face, edge, lw = [], [], [], []
for k, polys in enumerate(city['polys']):
    e = eff.get(k, 0)
    fc = '#4b3f8f' if k in inT else ('#3f9e5f' if e > 0 else '#f0a030' if e < 0 else ('#e8e4d8' if k in inE else '#f4f4f2'))
    for p in polys:
        verts.append(p[0]); face.append(fc); edge.append('#333333' if k in inE else '#bbbbbb'); lw.append(0.8 if k in inE else 0.3)
fig, ax = plt.subplots(figsize=(9, 8))
ax.add_collection(PolyCollection(verts, facecolors=face, edgecolors=edge, linewidths=lw))
allxy = np.vstack([v for v in verts]); ax.set_xlim(allxy[:, 0].min(), allxy[:, 0].max()); ax.set_ylim(allxy[:, 1].min(), allxy[:, 1].max())
ax.set_aspect('equal'); ax.axis('off')
from matplotlib.patches import Patch
ax.legend(handles=[Patch(color='#4b3f8f', label='территория'), Patch(facecolor='#e8e4d8', edgecolor='#333333', label=f'окружение {P["R"]} м'),
                   Patch(color='#3f9e5f', label='функции появились'), Patch(color='#f0a030', label='функции пропали')],
          loc='lower left', fontsize=9, frameon=False)
ax.set_title(f'{cfg["name"]}: вариант {SHOW}', fontsize=11)
plt.savefig(f'{OUT}/{КОД}_карта_{SHOW.split()[0]}.png', dpi=150, bbox_inches='tight')
plt.show()

def to_geojson_geom(g):
    return {'type': 'MultiPolygon', 'coordinates': [[r.tolist() for r in p] for p in g[1]]}
feats = []
for k, row in city['table'].iterrows():
    props = {c: (None if pd.isna(row[c]) else (bool(row[c]) if isinstance(row[c], (bool, np.bool_)) else (row[c] if isinstance(row[c], str) else float(row[c]))))
             for c in ['block_id', 'zone', 'area', 'pop', 'jobs', 'есть_К', 'есть_ОД', 'есть_П', 'cap_school', 'cap_kinder']}
    props['территория'] = k in inT; props['окружение'] = k in inE
    for s in SCN:
        props['доступ ' + s.split()[0]] = det['effect'][s].get(k, 0)
    feats.append({'type': 'Feature', 'properties': props, 'geometry': to_geojson_geom(city['orig'][k])})
crs = 'urn:ogc:def:crs:OGC:1.3:CRS84' if city['epsg'] in (4326, None) else f'urn:ogc:def:crs:EPSG::{city["epsg"]}'
json.dump({'type': 'FeatureCollection', 'crs': {'type': 'name', 'properties': {'name': crs}}, 'features': feats},
          open(f'{OUT}/{КОД}_кварталы.geojson', 'w', encoding='utf-8'), ensure_ascii=False)
print('Слой для QGIS сохранён:', f'{OUT}/{КОД}_кварталы.geojson')


# ################################################################################################
# БЛОК 9. ШАГ 9 — ФАЙЛ ДАННЫХ ДЛЯ ВЕБ-СТРАНИЦЫ
# Сохраняет таблицу кварталов с контурами в формате, который читает страница «Конструктор
# смешанности». Страница по этому файлу сама пересчитывает шаги 5–6 при выборе территории.
# ################################################################################################

proj = city['proj']
origin = [proj.lon0, proj.lat0, proj.kx, proj.ky] if proj else [0, 0, 1, 1]   # как перевести координаты контуров в метры
web = {'format': 'konstruktor-smeshannosti', 'format_version': 1,
       'meta': {'city': cfg['name'], 'source': 'метод_сравнения_вариантов.ipynb, шаг 9', 'blocks_crs': 'градусы' if proj else f'EPSG:{city["epsg"]}'},
       'params': {k: v for k, v in P.items() if k not in ('S_min', 'storeys_default', 'builtin', 'builtin_s0', 'builtin_share', 'builtin_min_storeys')}, 'scenarios': SCN,
       'presets': [{'name': 'Территория из ноутбука', 'ids': [int(i) for i in cfg['territory']]}],
       'origin': origin, 'blocks': [],
       'pts': {'metro': np.round(city['pts']['метро'], 1).tolist(), 'stop': np.round(city['pts']['остановка'], 1).tolist()}}
for k, row in city['table'].iterrows():
    web['blocks'].append({
        'id': int(row['block_id']), 'zone': None if pd.isna(row['zone']) else str(row['zone']).replace('LandUse.', ''),
        'area': round(float(row['area'])), 'cx': round(float(row['cx']), 1), 'cy': round(float(row['cy']), 1),
        'pop': round(float(row['pop'])), 'liv': round(float(row['liv'])),
        'nrK': round(float(row['nr_К'])), 'nrOD': round(float(row['nr_ОД'])), 'nrP': round(float(row['nr_П'])), 'nrX': round(float(row['nr_X'])),
        'pK': int(row['n_К']), 'pOD': int(row['n_ОД']), 'pP': int(row['n_П']),
        'school': round(float(row['cap_school'])), 'kinder': round(float(row['cap_kinder'])),
        'g': [[np.round(r, 5 if proj else 1).tolist() for r in p] for p in city['orig'][k][1]],
    })
json.dump(web, open(f'{OUT}/{КОД}_для_страницы.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print('Файл для страницы:', f'{OUT}/{КОД}_для_страницы.json', '—', len(web['blocks']), 'кварталов')
