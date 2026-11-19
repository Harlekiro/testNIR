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
