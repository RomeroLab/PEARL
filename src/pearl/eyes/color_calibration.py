import math
import numpy as np

def predict_mix_color(components: list[tuple[tuple[int, int, int], float]]) -> dict:
    if not components:
        raise ValueError('predict_mix_color: empty component list')
    for _, vol in components:
        if vol < 0:
            raise ValueError(f'predict_mix_color: negative volume {vol}')
    nonzero = [(rgb, vol) for rgb, vol in components if vol > 0]
    if not nonzero:
        raise ValueError('predict_mix_color: all volumes are zero')
    total = sum((vol for _, vol in nonzero))
    r_acc = g_acc = b_acc = 0.0
    for (r, g, b), vol in nonzero:
        frac = vol / total
        r_acc += r * frac
        g_acc += g * frac
        b_acc += b * frac
    rgb = (max(0, min(255, int(round(r_acc)))), max(0, min(255, int(round(g_acc)))), max(0, min(255, int(round(b_acc)))))
    bgr = (rgb[2], rgb[1], rgb[0])
    hex_code = ColorCalibrator.bgr_to_hex(bgr)
    hsv = ColorCalibrator.bgr_to_hsv(bgr)
    return {'rgb': rgb, 'hex': hex_code, 'hsv': hsv, 'v': hsv[2]}

class ColorCalibrator:

    @staticmethod
    def hex_to_rgb(hex_code: str) -> tuple[int, int, int]:
        h = hex_code.lstrip('#')
        if len(h) == 3:
            h = ''.join((c * 2 for c in h))
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    @staticmethod
    def bgr_to_lab(bgr: tuple[int, int, int]) -> tuple[float, float, float]:
        b, g, r = bgr

        def linearize(c: int) -> float:
            v = c / 255.0
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        rl, gl, bl = (linearize(r), linearize(g), linearize(b))
        x = rl * 0.4124564 + gl * 0.3575761 + bl * 0.1804375
        y = rl * 0.2126729 + gl * 0.7151522 + bl * 0.072175
        z = rl * 0.0193339 + gl * 0.119192 + bl * 0.9503041
        x /= 0.95047
        y /= 1.0
        z /= 1.08883

        def f(t: float) -> float:
            return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
        fx, fy, fz = (f(x), f(y), f(z))
        L = 116 * fy - 16
        a = 500 * (fx - fy)
        b_val = 200 * (fy - fz)
        return (round(L, 4), round(a, 4), round(b_val, 4))

    @staticmethod
    def delta_e(lab1: tuple[float, float, float], lab2: tuple[float, float, float]) -> float:
        return float(((lab1[0] - lab2[0]) ** 2 + (lab1[1] - lab2[1]) ** 2 + (lab1[2] - lab2[2]) ** 2) ** 0.5)

    @staticmethod
    def bgr_to_hsv(bgr: tuple[int, int, int]) -> tuple[float, float, float]:
        b, g, r = bgr
        rf, gf, bf = (r / 255.0, g / 255.0, b / 255.0)
        cmax = max(rf, gf, bf)
        cmin = min(rf, gf, bf)
        delta = cmax - cmin
        if delta == 0:
            h = 0.0
        elif cmax == rf:
            h = 60.0 * ((gf - bf) / delta % 6)
        elif cmax == gf:
            h = 60.0 * ((bf - rf) / delta + 2)
        else:
            h = 60.0 * ((rf - gf) / delta + 4)
        s = 0.0 if cmax == 0 else delta / cmax
        return (h, s, cmax)

    @staticmethod
    def bgr_to_hex(bgr: tuple[int, int, int]) -> str:
        b, g, r = bgr
        return f'#{r:02X}{g:02X}{b:02X}'
