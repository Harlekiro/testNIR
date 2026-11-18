"""Сохранение результатов: CSV, слой GeoJSON для QGIS, JSON для страницы, карта PNG, отчёт.

Имена файлов и столбцов — как в results/ ноутбука.
"""
import json
import os

import numpy as np
import pandas as pd



def out_path(out_dir, code, suffix):
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f'{code}_{suffix}')


def blocks_csv(city, path):
    """Таблица кварталов (results/<код>_таблица_кварталов.csv), округление до 0,1."""
    city['table'].drop(columns=['cx', 'cy']).round(1).to_csv(path, index=False, encoding='utf-8-sig')
    return path


def table_csv(df, path, index=True):
    df.to_csv(path, index=index, encoding='utf-8-sig')
    return path


def report_txt(lines, path):
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return path


def _geom(g):
    return {'type': 'MultiPolygon', 'coordinates': [[r.tolist() for r in p] for p in g[1]]}


def blocks_geojson(city, path, det=None, SCN=None):
    """Слой кварталов для QGIS в исходной системе координат кварталов.
    Если передано сравнение — поля «территория», «окружение», «доступ <вариант>» (+1 появились, −1 пропали)."""
    inT = set(det['T']) if det else set(); inE = set(det['E'].tolist()) if det else set()
    feats = []
    for k, row in city['table'].iterrows():
        props = {c: (None if pd.isna(row[c]) else (bool(row[c]) if isinstance(row[c], (bool, np.bool_)) else (row[c] if isinstance(row[c], str) else float(row[c]))))
                 for c in ['block_id', 'zone', 'area', 'pop', 'jobs', 'есть_К', 'есть_ОД', 'есть_П', 'cap_school', 'cap_kinder']}
        if det:
            props['территория'] = k in inT; props['окружение'] = k in inE
            for s in SCN:
                props['доступ ' + s.split()[0]] = det['effect'][s].get(k, 0)
        feats.append({'type': 'Feature', 'properties': props, 'geometry': _geom(city['orig'][k])})
    crs = 'urn:ogc:def:crs:OGC:1.3:CRS84' if city['epsg'] in (4326, None) else f'urn:ogc:def:crs:EPSG::{city["epsg"]}'
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'crs': {'type': 'name', 'properties': {'name': crs}}, 'features': feats},
                  f, ensure_ascii=False)
    return path


# параметры, которые не нужны странице (она пересчитывает только шаги 5–6)
_WEB_SKIP = ('S_min', 'storeys_default', 'builtin', 'builtin_s0', 'builtin_share', 'builtin_min_storeys')


def web_json(city, cfg, path):
    """Шаг 9. Файл данных для страницы «Конструктор смешанности» (формат ноутбука v4, format_version 1)."""
    proj = city['proj']
    P, SCN = cfg['params'], cfg['scenarios']
    origin = [proj.lon0, proj.lat0, proj.kx, proj.ky] if proj else [0, 0, 1, 1]   # как перевести координаты контуров в метры
    web = {'format': 'konstruktor-smeshannosti', 'format_version': 1,
           'meta': {'city': cfg.get('title') or cfg['name'], 'source': 'метод_сравнения_вариантов.ipynb, шаг 9',
                    'blocks_crs': 'градусы' if proj else f'EPSG:{city["epsg"]}'},
           'params': {k: v for k, v in P.items() if k not in _WEB_SKIP}, 'scenarios': SCN,
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
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(web, f, ensure_ascii=False, separators=(',', ':'))
    return path


def map_png(city, det, show, R, title, path):
    """Шаг 8. Карта в файл PNG (командная строка: без окна на экране)."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig = map_figure(city, det, show, R, title)
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


def map_figure(city, det, show, R, title):
    """Шаг 8. Рисунок карты: территория — фиолетовая, окружение обведено; зелёный — функции появились,
    оранжевый — пропали. Возвращает рисунок matplotlib (ноутбук показывает его и сохраняет)."""
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.patches import Patch
    eff = det['effect'][show]; inT = set(det['T']); inE = set(det['E'].tolist())
    verts, face, edge, lw = [], [], [], []
    for k, polys in enumerate(city['polys']):
        e = eff.get(k, 0)
        fc = '#4b3f8f' if k in inT else ('#3f9e5f' if e > 0 else '#f0a030' if e < 0 else ('#e8e4d8' if k in inE else '#f4f4f2'))
        for p in polys:
            verts.append(p[0]); face.append(fc); edge.append('#333333' if k in inE else '#bbbbbb'); lw.append(0.8 if k in inE else 0.3)
    fig, ax = plt.subplots(figsize=(9, 8))
    ax.add_collection(PolyCollection(verts, facecolors=face, edgecolors=edge, linewidths=lw))
    allxy = np.vstack(verts); ax.set_xlim(allxy[:, 0].min(), allxy[:, 0].max()); ax.set_ylim(allxy[:, 1].min(), allxy[:, 1].max())
    ax.set_aspect('equal'); ax.axis('off')
    ax.legend(handles=[Patch(color='#4b3f8f', label='территория'), Patch(facecolor='#e8e4d8', edgecolor='#333333', label=f'окружение {R:g} м'),
                       Patch(color='#3f9e5f', label='функции появились'), Patch(color='#f0a030', label='функции пропали')],
              loc='lower left', fontsize=9, frameon=False)
    ax.set_title(f'{title}: вариант {show}', fontsize=11)
    return fig
