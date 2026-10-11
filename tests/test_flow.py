import copy

import pytest

import eternal_fishmod as app


def test_use_rod_clicks_upper_item_only(monkeypatch):
    settings = copy.deepcopy(app.CFG)
    settings.update({'rod_mode': 'fixed', 'rod_click_pos': [125, 260],
                     'use_click_pos': [205, 279], 'after_equip_delay': 0})
    monkeypatch.setattr(app, 'CFG', settings)
    monkeypatch.setattr(app, 'P', lambda x, y: (x, y))
    monkeypatch.setattr(app, 'scale', lambda: (1., 1.))
    monkeypatch.setattr(app, 'scroll_inventory', lambda _: None)
    monkeypatch.setattr(app, 'context_menu_open', lambda: (208, 315))
    monkeypatch.setattr(app, 'check_stop', lambda: 0)
    monkeypatch.setattr(app, 'nap', lambda _: None)
    monkeypatch.setattr(app, 'inventory_open', lambda: False)
    monkeypatch.setattr(app, 'log', lambda _: None)
    clicked = []
    monkeypatch.setattr(app, 'click_px', lambda x, y, *args, **kwargs: clicked.append((x, y, args)))
    app.use_rod()
    assert [(x, y) for x, y, _ in clicked] == [(125, 260), (205, 279)]
    assert clicked[0][2][0] == 'right'


def test_refuses_click_on_red_discard(monkeypatch):
    settings = copy.deepcopy(app.CFG)
    settings.update({'rod_mode': 'fixed', 'rod_click_pos': [125, 260],
                     'use_click_pos': [205, 317], 'menu_timeout': 1})
    monkeypatch.setattr(app, 'CFG', settings)
    monkeypatch.setattr(app, 'P', lambda x, y: (x, y))
    monkeypatch.setattr(app, 'scale', lambda: (1., 1.))
    monkeypatch.setattr(app, 'scroll_inventory', lambda _: None)
    monkeypatch.setattr(app, 'context_menu_open', lambda: (208, 315))
    monkeypatch.setattr(app, 'check_stop', lambda: 0)
    monkeypatch.setattr(app, 'nap', lambda _: None)
    monkeypatch.setattr(app, 'log', lambda _: None)
    clicked = []
    monkeypatch.setattr(app, 'click_px', lambda x, y, *args, **kwargs: clicked.append((x, y)))
    with pytest.raises(app.Fail, match='опасные координаты'):
        app.use_rod()
    assert clicked == [(125, 260)]
