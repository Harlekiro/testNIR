"""Школы и сады в вариантах: выбор способа расчёта без участия пользователя (пункт 3).

Пользователь запускает обычный Python (ноутбук или командную строку). Порядок:
  1. blocksnet установлен в этом Python и матрица есть — точный расчёт здесь же (provision_bn);
  2. рядом есть отдельное окружение с blocksnet (переменная MIXUSE_BLOCKSNET_PYTHON или
     %USERPROFILE%\\venvs\\blocksnet311\\Scripts\\python.exe — его создаёт подготовить_город.bat) — точный расчёт
     выполняется там: программа сама передаёт ему данные и забирает результат;
  3. есть сохранённый точный расчёт «как есть» (data/<код>/access/provision_walk.json) — оценка (provision_estimate);
  4. иначе — запасной расчёт 4.7.3 (prov = None).
Переменная MIXUSE_PROVISION: auto (по умолчанию), estimate — только оценка, fallback — только запасной расчёт.
Модуль не импортирует blocksnet.
"""
import json
import os
import subprocess
import sys
import tempfile

import yaml


def blocksnet_python():
    """Путь к Python отдельного окружения с blocksnet или None."""
    cand = [os.environ.get('MIXUSE_BLOCKSNET_PYTHON'),
            os.path.join(os.path.expanduser('~'), 'venvs', 'blocksnet311', 'Scripts', 'python.exe'),
            os.path.join(os.path.expanduser('~'), 'venvs', 'blocksnet311', 'bin', 'python')]
    for p in cand:
        if p and os.path.exists(p) and os.path.abspath(p) != os.path.abspath(sys.executable):
            return p
    return None


_CFG_KEYS = ('name', 'title', 'mode', 'rules', 'blocks', 'block_id_field', 'buildings', 'services', 'service_type_field',
             'zones', 'zone_field', 'zone_rules', 'block_zone_field', 'count_prefix', 'capacity_prefix', 'fields',
             'territory', 'params', 'scenarios', 'service_groups', 'capacity_field', 'param_sources')


def _plain(v):
    """Значение настроек → то, что понимает YAML (кортежи → списки, числа numpy → числа)."""
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if hasattr(v, 'item'):
        return v.item()
    return v


def delegate(cfg, T_ids, E_ids, values, near=None, timeout=3600):
    """Точный расчёт вариантов в отдельном окружении с blocksnet (команда provision-variants). Возвращает prov."""
    py = blocksnet_python()
    if not py:
        raise RuntimeError('нет отдельного окружения с blocksnet')
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with tempfile.TemporaryDirectory() as d:
        raw = {k: _plain(cfg[k]) for k in _CFG_KEYS if cfg.get(k) is not None}
        raw['params'] = {k: v for k, v in raw.get('params', {}).items()}
        # data/<код>/access/ — от корня проекта: настройки кладём в configs/ временной папки не можем, поэтому
        # передаём корень явно; пути к слоям — абсолютные
        cfg_path = os.path.join(d, 'cfg.yaml')
        with open(cfg_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(raw, f, allow_unicode=True)
        job = {'territory': [int(i) for i in T_ids], 'environment': [int(i) for i in E_ids], 'near': near,
               'access_root': os.path.dirname(os.path.dirname(cfg['_path'])) if str(cfg.get('_path', '')).endswith('.yaml') else root,
               'values': {n: {'N': float(o['N']), 'd': o['d']} for n, o in values.items()}}
        job_path, out_path = os.path.join(d, 'job.json'), os.path.join(d, 'out.json')
        with open(job_path, 'w', encoding='utf-8') as f:
            json.dump(job, f, ensure_ascii=False)
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONPATH=root + os.pathsep + os.environ.get('PYTHONPATH', ''))
        r = subprocess.run([py, '-m', 'mixuse', 'provision-variants', cfg_path, job_path, out_path],
                           capture_output=True, timeout=timeout, env=env, cwd=root)
        if r.returncode != 0 or not os.path.exists(out_path):
            tail = (r.stdout + r.stderr).decode('utf-8', 'replace').strip().splitlines()[-3:]
            raise RuntimeError('окружение с blocksnet не посчитало: ' + ' / '.join(tail))
        return json.load(open(out_path, encoding='utf-8'))


def school_provision(cfg, city, T_ids, det, near=None, say=print):
    """Выбирает способ расчёта школ и садов (1–4). Возвращает (prov или None, пояснение для отчёта)."""
    t = city['table']
    E_ids = t['block_id'].iloc[det['E']].astype(int).tolist()
    notes = []
    mode = os.environ.get('MIXUSE_PROVISION', 'auto')      # auto | estimate | fallback (тесты эталонов — fallback)
    if mode == 'fallback':
        return None, 'Школы и сады — запасной расчёт 4.7.3 (MIXUSE_PROVISION=fallback).'
    from . import provision_bn as pb
    try:                                                                     # 1. blocksnet здесь
        if mode == 'estimate':
            raise pb.BlocksnetError('выбрана оценка (MIXUSE_PROVISION=estimate)')
        pb.require_blocksnet()
        mx, _ = pb.load_matrix(cfg, t['block_id'].tolist())
        return pb.variant_provision(city, mx, T_ids, E_ids, det['values'], near=near), None
    except pb.BlocksnetError as e:
        notes.append(str(e).split('.')[0])
    if mode == 'auto' and blocksnet_python():                                # 2. отдельное окружение
        try:
            say('Школы и сады: точный расчёт в окружении с blocksnet…')
            return delegate(cfg, T_ids, E_ids, det['values'], near), None
        except Exception as e:                                               # noqa: BLE001 — сообщаем и идём дальше
            notes.append(f'окружение с blocksnet: {e}')
    from .provision_estimate import load_page_data, estimate_variants        # 3. оценка
    try:
        pdat = load_page_data(cfg, city)
    except ValueError as e:
        pdat = None
        notes.append(str(e))
    if pdat:
        prov = estimate_variants(pdat, det['T'], list(det['E']), det['values'], t['area'].to_numpy())
        return prov, ('Школы и сады — оценка по сохранённому точному расчёту blocksnet «как есть» '
                      f'(точный расчёт вариантов недоступен: {"; ".join(notes)}).')
    return None, f'Школы и сады — запасной расчёт 4.7.3 (раздел 12 не использован: {"; ".join(notes)}).'
