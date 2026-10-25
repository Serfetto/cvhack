"""Огонь без нейросети: цвет пламени + мерцание между кадрами одной камеры.

Пиксель-кандидат — яркий и красно-оранжевый: R > G > B, R выше порога, а насыщенность тем выше,
чем темнее пиксель (правило Chen et al., 2004). Цвета мало: так же выглядят оранжевый жилет,
погрузчик, тёплая лампа. Пламя отличает мерцание — яркость кандидатов меняется от кадра к кадру
внутри области, а жилет и лампа либо неподвижны, либо сдвигаются целиком (меняются только края).
Поэтому для каждой камеры хранится предыдущий кадр и сглаженная карта мерцания.

На выходе — рамки областей огня в долях кадра, score 0.5 — мерцание на пороге, 1.0 — вдвое выше.
Подтверждение во времени и фильтр «огонь на человеке» — в сценарии `fire`.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class _CamState:
    gray: np.ndarray
    flicker: np.ndarray


class FireFinder:
    def __init__(self, width: int = 320, r_min: int = 170, sat_k: float = 1.0, diff_min: int = 14,
                 alpha: float = 0.6, flicker_min: float = 0.2, min_area: float = 0.0004, global_change: float = 0.35):
        self.width = width                # кадр уменьшается до этой ширины: ~1–3 мс на CPU
        self.r_min = r_min                # минимальный красный канал пламени
        self.sat_k = sat_k                # S ≥ (255 − R) · sat_k
        self.diff_min = diff_min          # изменение яркости между кадрами, которое считается мерцанием
        self.alpha = alpha                # сглаживание карты мерцания (доля старого значения)
        self.flicker_min = flicker_min    # средняя доля мерцающих пикселей в области огня
        self.min_area = min_area          # минимальная площадь области, доля кадра
        self.global_change = global_change  # изменился весь кадр (экспозиция, сдвиг камеры) — кадр пропускаем
        self.state: dict[str, _CamState] = {}

    def color_mask(self, small: np.ndarray) -> np.ndarray:
        b, g, r = (small[..., i].astype(np.int16) for i in range(3))
        s = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)[..., 1].astype(np.int16)
        return (r >= self.r_min) & (r >= g) & (g > b) & (s >= (255 - r) * self.sat_k)

    def find(self, image_bgr: np.ndarray, key: str = "_") -> list[dict]:
        h, w = image_bgr.shape[:2]
        sw = min(self.width, w)
        small = cv2.resize(image_bgr, (sw, max(1, round(h * sw / w))), interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (3, 3), 0)

        st = self.state.get(key)
        if st is None or st.gray.shape != gray.shape:
            self.state[key] = _CamState(gray, np.zeros(gray.shape, np.float32))
            return []
        changed = cv2.absdiff(gray, st.gray) >= self.diff_min
        st.gray = gray
        if changed.mean() > self.global_change:
            st.flicker[:] = 0
            return []
        st.flicker *= self.alpha
        st.flicker += (1 - self.alpha) * changed

        color = self.color_mask(small).astype(np.uint8)
        color = cv2.morphologyEx(color, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, labels, stats, _ = cv2.connectedComponentsWithStats(color, connectivity=8)
        sh, sw = gray.shape
        min_px = self.min_area * sh * sw
        out = []
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if area < min_px:
                continue
            flick = float(st.flicker[labels == i].mean())
            if flick < self.flicker_min:
                continue
            out.append({"cls": "fire", "bbox": [x / sw, y / sh, (x + bw) / sw, (y + bh) / sh],
                        "score": round(min(1.0, flick / (2 * self.flicker_min)), 3)})
        return out
