import cv2
import numpy as np

import eternal_fishmod as app


def test_context_menu_red_lower_item(monkeypatch):
    # Подобно предоставленному кадру: верхний пункт серый, нижний красный.
    img = np.zeros((110, 190, 3), dtype=np.uint8)
    img[20:48, 10:170] = (55, 55, 55)
    img[48:80, 10:170] = (25, 35, 220)
    monkeypatch.setattr(app, 'grab', lambda roi: img)
    monkeypatch.setattr(app, 'P', lambda x, y: (round(x), round(y)))
    monkeypatch.setattr(app, 'scale', lambda: (1., 1.))
    x, y = app.context_menu_open()
    assert 190 < x < 220
    assert y > app.CFG['menu_roi'][1] + 48
    assert y - app.CFG['menu_up'] < y - 8  # координата use обязательно выше
    img[:] = 0
    assert app.context_menu_open() is None


def test_menu_position_from_supplied_screenshot(monkeypatch):
    from pathlib import Path
    shot = Path(app.BASE_DIR) / '1791751384528-image.png'
    if not shot.exists():
        return
    frame = cv2.imread(str(shot))
    monkeypatch.setattr(app, 'grab', lambda roi: frame[roi[1]:roi[1]+roi[3], roi[0]:roi[0]+roi[2]])
    monkeypatch.setattr(app, 'P', lambda x, y: (round(x), round(y)))
    monkeypatch.setattr(app, 'scale', lambda: (1., 1.))
    center = app.context_menu_open()
    assert center is not None
    assert 185 <= center[0] <= 230 and 300 <= center[1] <= 335
    assert app.CFG['use_click_pos'][1] < center[1] - 8


def test_bundled_inventory_header_matches_supplied_frames():
    from pathlib import Path
    path = Path(app.TPL_DIR) / 'inv_header.png'
    template = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    assert template is not None
    for image, expected in [('1791751384528-image.png', True),
                            ('1791751385077-image.png', False)]:
        src = Path(app.BASE_DIR) / image
        if not src.exists():
            continue
        frame = cv2.imread(str(src), cv2.IMREAD_GRAYSCALE)
        roi = frame[20:130, 60:360]
        score = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED).max()
        assert (score > app.THR['inv_header']) == expected
