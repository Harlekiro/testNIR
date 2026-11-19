"""Пункт 3: школы и сады без участия пользователя — bn_bridge.school_provision выбирает способ расчёта."""
import os

import pytest

from conftest import ROOT
from mixuse.config import load_config
from mixuse.blocks import load_layers, build_table
from mixuse.compare import compare
from mixuse import bn_bridge
from mixuse.provision_estimate import load_page_data, estimate_variants


def _vysotsk():
    cfg = load_config(os.path.join(ROOT, 'configs', 'vysotsk.yaml'))
    if not os.path.exists(cfg['blocks']):
        pytest.skip('нет данных Высоцка')
    city = build_table(load_layers(cfg, cfg['_groups']), cfg, cfg['params'], cfg['_groups'])
    _, _, det = compare(city, cfg['territory'], cfg['params'], cfg['scenarios'])
    return cfg, city, det


def test_modes(monkeypatch):
    cfg, city, det = _vysotsk()
    monkeypatch.setenv('MIXUSE_PROVISION', 'fallback')
    prov, note = bn_bridge.school_provision(cfg, city, cfg['territory'], det, say=lambda *a: None)
    assert prov is None and '4.7.3' in note
    if load_page_data(cfg, city) is None:
        pytest.skip('нет сохранённого точного расчёта «как есть»')
    monkeypatch.setenv('MIXUSE_PROVISION', 'estimate')
    prov, note = bn_bridge.school_provision(cfg, city, cfg['territory'], det, say=lambda *a: None)
    assert prov['_source'].startswith('оценка') and 'оценка' in note


def test_delegation_equals_exact(monkeypatch):
    """Расчёт в отдельном окружении с blocksnet из обычного Python. На Высоцке оценка совпадает с blocksnet
    (тест 12.6), поэтому переданный расчёт сверяется с оценкой."""
    if not bn_bridge.blocksnet_python():
        pytest.skip('нет отдельного окружения с blocksnet')
    try:
        import blocksnet  # noqa: F401
        pytest.skip('blocksnet установлен в этом Python — передавать расчёт не нужно')
    except ImportError:
        pass
    cfg, city, det = _vysotsk()
    pdat = load_page_data(cfg, city)
    if pdat is None:
        pytest.skip('нет сохранённого точного расчёта «как есть»')
    monkeypatch.setenv('MIXUSE_PROVISION', 'auto')
    prov, note = bn_bridge.school_provision(cfg, city, cfg['territory'], det, say=lambda *a: None)
    assert note is None and prov['_source'].startswith('blocksnet')
    est = estimate_variants(pdat, det['T'], list(det['E']), det['values'], city['table']['area'].to_numpy())
    for scen in cfg['scenarios']:
        for key in ('school', 'kindergarten'):
            a, b = prov[scen][key], est[scen][key]
            assert (a['children'], a['provided']) == (b['children'], b['provided'])
            assert a['env_in'] == pytest.approx(b['env_in'])
