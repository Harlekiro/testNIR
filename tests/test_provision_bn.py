"""Этап 8.3: матрица доступности (ТЗ 12.3). Тесты без blocksnet — проверка соответствия кварталов и загрузка готовой
матрицы; сама матрица строится командой `python -m mixuse access` в окружении с blocksnet (Python 3.11)."""
import glob
import os
import re

import numpy as np
import pandas as pd
import pytest

from conftest import ROOT
from mixuse.config import load_config
from mixuse.blocks import load_blocks
from mixuse import provision_bn as pb


def test_only_provision_bn_imports_blocksnet():
    """ТЗ 3, 12.3: тяжёлые зависимости — только в provision_bn.py; ядро без них работает."""
    heavy = re.compile(r'^\s*(import|from)\s+(blocksnet|geopandas|shapely|networkx|iduedu)\b', re.M)
    for path in glob.glob(os.path.join(ROOT, 'mixuse', '*.py')):
        if os.path.basename(path) != 'provision_bn.py':
            assert not heavy.search(open(path, encoding='utf-8').read()), path


def test_missing_blocksnet_message():
    try:
        import blocksnet  # noqa: F401
        pytest.skip('blocksnet установлен')
    except ImportError:
        with pytest.raises(pb.BlocksnetError, match='pip install -e .\\[blocksnet\\]'):
            pb.require_blocksnet()


def test_check_matrix_correspondence():
    ids = [0, 1, 2]
    mx = pd.DataFrame(np.zeros((3, 3)), index=ids, columns=ids)
    assert pb.check_matrix(mx, {}, ids) == []
    assert pb.check_matrix(mx, {}, [0, 2, 1])                                  # другой порядок
    assert pb.check_matrix(mx.iloc[:2, :2], {}, ids)                          # другое число кварталов
    assert pb.check_matrix(mx, {'sha256 слоя кварталов': 'a'}, ids, 'b')       # другой файл кварталов
    assert pb.check_matrix(pd.DataFrame(np.zeros((2, 2)), index=[5, 5], columns=[5, 5]), {}, [5, 5])   # повторы


def test_access_dir():
    cfg = load_config(os.path.join(ROOT, 'configs', 'vysotsk.yaml'))
    assert pb.access_dir(cfg) == os.path.join(ROOT, 'data', 'vysotsk', 'access')


@pytest.mark.parametrize('code', ['vysotsk', 'gatchina_layers', 'spb_full'])
def test_saved_matrix_matches_blocks(code):
    """8.3: готовая матрица построена по тем же кварталам mixuse (число, порядок, номера, файл кварталов)."""
    cfg = load_config(os.path.join(ROOT, 'configs', f'{code}.yaml'))
    if not os.path.exists(pb.matrix_paths(cfg)[0]) or not os.path.exists(cfg['blocks']):
        pytest.skip(f'нет матрицы или данных набора {code}')
    ids = load_blocks(cfg)[0]['block_id'].tolist()
    mx, meta = pb.load_matrix(cfg, ids)
    assert mx.shape == (len(ids), len(ids))
    assert meta['граф'] == 'walk' and meta['blocksnet'] == pb.BLOCKSNET_VERSION and meta['единицы'] == 'минуты'
    v = mx.to_numpy(dtype=float)
    assert (np.diag(v) == 0).all() and np.isfinite(v).all() and (v >= 0).all()


# ---------- этап 8.4: обеспеченность «как есть» (нужен blocksnet: окружение Python 3.11) ----------

def _need_blocksnet():
    try:
        pb.require_blocksnet()
    except pb.BlocksnetError:
        pytest.skip('blocksnet не установлен (запускайте в окружении с Python 3.11)')


def test_algorithm_by_hand():
    """Три квартала: A — 1 000 жителей, мест нет; B — 100 мест в 10 мин от A; C — 50 мест в 25 мин от A.
    Норма 120 на 1 000 → спрос A = 120. Порог 15 мин, max_depth = 2 (до 30 мин):
    в пределах порога — 100 детей в B; за порогом — 20 детей в C; обеспеченность 100 / 120 = 83,3 %, вообще — 100 %."""
    _need_blocksnet()
    from loguru import logger
    from blocksnet.analysis.provision import competitive_provision
    logger.remove()
    ids = [0, 1, 2]
    mx = pd.DataFrame([[0, 10, 25], [10, 0, 30], [25, 30, 0]], index=ids, columns=ids, dtype=float)
    df = pd.DataFrame({'population': [1000, 0, 0], 'capacity': [0, 100, 50]}, index=ids)
    res, _ = competitive_provision(df, mx, 15, demand=120, max_depth=2)
    within, anyway, demand = pb.provision_share(res)
    assert demand == 120 and within == pytest.approx(100 / 120 * 100) and anyway == pytest.approx(100)


def test_vysotsk_as_is():
    """Высоцк «как есть» (пешеходная матрица, нормы blocksnet, max_depth = 2) — как в разведке 8.1."""
    _need_blocksnet()
    from mixuse.blocks import load_layers, build_table
    cfg = load_config(os.path.join(ROOT, 'configs', 'vysotsk.yaml'))
    if not os.path.exists(cfg['blocks']):
        pytest.skip('нет данных Высоцка')
    city = build_table(load_layers(cfg, cfg['_groups']), cfg, cfg['params'], cfg['_groups'])
    mx, _ = pb.load_matrix(cfg, city['table']['block_id'].tolist())
    rep, blocks = pb.as_is_report(cfg, city, mx, cfg['territory'])
    s, k = rep['Школы'], rep['Сады']
    assert (s['мест на 1000 жителей'], s['порог, мин'], k['мест на 1000 жителей'], k['порог, мин']) == (120, 15.0, 61, 7.0)
    assert (s['весь набор: в пределах доступности, %'], s['весь набор: получили место вообще, %']) == (88.7, 90.1)
    assert (k['весь набор: в пределах доступности, %'], k['весь набор: получили место вообще, %']) == (63.5, 92.1)
    assert (k['окружение: в пределах доступности, %'], k['окружение: получили место вообще, %']) == (69.0, 100.0)
    for c in (s, k):                                         # 12.8: не больше min(100 %; места ÷ спрос)
        assert c['весь набор: в пределах доступности, %'] <= c['проверка 12.8: не больше min(100 %; места ÷ спрос), %']
