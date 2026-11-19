"""Файлы регионов OpenStreetMap (.osm.pbf) для графа без сервера Overpass (пункт 5).

Выгрузки openstreetmap.fr по субъектам РФ — обычные файлы: скачиваются целиком, докачиваются после обрыва
и лежат в data/osm/. Ссылку можно открыть и в браузере, а файл положить в data/osm/ вручную.
"""
import os
import time

BASE = 'https://download.openstreetmap.fr/extracts/russia/northwestern_federal_district/'
REGIONS = {
    'saint_petersburg': BASE + 'saint_petersburg-latest.osm.pbf',
    'leningrad_oblast': BASE + 'leningrad_oblast-latest.osm.pbf',
}
DEFAULT = ('saint_petersburg', 'leningrad_oblast')     # Петербург, Гатчина и Высоцк


def download(url, path, say=print, attempts=1000, pause=15):
    """Скачивает файл с докачкой: недокачанный хранится как <файл>.part; после обрыва — продолжение с места обрыва."""
    import requests
    part = path + '.part'
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    total = None
    for attempt in range(attempts):
        have = os.path.getsize(part) if os.path.exists(part) else 0
        try:
            h = {'User-Agent': 'mixuse/0.9 (urban research; OSM extract download)'}
            if have:
                h['Range'] = f'bytes={have}-'
            with requests.get(url, stream=True, timeout=120, headers=h) as r:
                if r.status_code == 416:                       # уже всё скачано
                    break
                r.raise_for_status()
                total = have + int(r.headers.get('content-length', 0)) if r.status_code == 206 else int(r.headers.get('content-length', 0))
                with open(part, 'ab' if r.status_code == 206 else 'wb') as f:
                    t0, last = time.time(), time.time()
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        if time.time() - last > 60:
                            done = f.tell()
                            say(f'  {os.path.basename(path)}: {done / 2**20:.0f} из {total / 2**20:.0f} МБ')
                            last = time.time()
            if total and os.path.getsize(part) >= total:
                break
        except Exception as e:                                 # noqa: BLE001 — сеть: подождать и продолжить
            say(f'  обрыв ({type(e).__name__}); скачано {(os.path.getsize(part) if os.path.exists(part) else 0) / 2**20:.0f} МБ; '
                f'продолжу через {pause} с')
            time.sleep(pause)
    os.replace(part, path)
    return path


def fetch(root, regions=DEFAULT, say=print):
    """Скачивает недостающие файлы регионов в <root>/data/osm/. Возвращает пути."""
    out = []
    for reg in regions:
        if reg not in REGIONS:
            raise ValueError(f'Неизвестный регион «{reg}». Есть: {", ".join(REGIONS)}.')
        path = os.path.join(root, 'data', 'osm', os.path.basename(REGIONS[reg]))
        if os.path.exists(path):
            say(f'  {os.path.basename(path)} — уже есть')
        else:
            say(f'  скачиваю {REGIONS[reg]} …')
            download(REGIONS[reg], path, say=say)
        out.append(path)
    return out
