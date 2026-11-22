"""Проверка 18.5: словарь зон zone_dictionary.csv без ручных правил относит кварталы трёх наборов к тем же группам
(П, ОД, прочее), что прежние ручные правила зон. Зона квартала — из эталонной таблицы кварталов tests/etalon/v5."""
import os

import pandas as pd
import pytest

from conftest import ETALON_V5
from mixuse.groups import zone_match, load_zone_dictionary

OLD_RULES = {
    'vysotsk': [('Производственная', 'П'), ('Общественно-деловая', 'ОД')],
    'gatchina_layers': [('LandUse.INDUSTRIAL', 'П'), ('LandUse.BUSINESS', 'ОД')],
    'spb_full': [('ТП', 'П'), ('ТД', 'ОД')],
}


@pytest.mark.parametrize('code', list(OLD_RULES))
def test_dictionary_matches_old_rules(code):
    path = os.path.join(ETALON_V5, code, f'{code}_таблица_кварталов.csv')
    t = pd.read_csv(path, encoding='utf-8-sig', dtype={'zone': str})
    zd = load_zone_dictionary()
    diff = {}
    for z in t['zone'].fillna('').unique():
        old = zone_match(z, OLD_RULES[code])[0]
        new, _, conflict = zone_match(z, [], zd)
        assert not conflict, z
        if old != new:
            diff[z] = (old, new)
    assert not diff, diff
