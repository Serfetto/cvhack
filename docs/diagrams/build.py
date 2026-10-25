"""Схемы решения для презентации: python docs/diagrams/build.py → docs/diagrams/NN-*.svg и NN-*.png.

Каждая схема — слайд 1920×1080. PNG рендерит headless Chrome со шрифтами Golos Text и JetBrains Mono
(Google Fonts) в двойном разрешении. SVG — исходник: без этих шрифтов в системе текст уйдёт в Segoe UI / Arial.
"""

from __future__ import annotations

import html
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parent
W, H = 1920, 1080
FONT = "'Golos Text', 'Segoe UI', Arial, sans-serif"
MONO = "'JetBrains Mono', Consolas, monospace"
FONTS_CSS = ("https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;500;600;700"
             "&family=JetBrains+Mono:wght@400;500;600&display=swap")

INK, TEXT, MUTED, GREY, LINE = "#17212F", "#3A4554", "#5B6676", "#7D8796", "#C3CBD6"
ZONE, ZONE_LINE = "#F3F6FA", "#DCE3EC"
BLUE, BLUE_SOFT = "#2F64D6", "#EAF0FC"
AMBER, AMBER_TEXT, AMBER_FILL, AMBER_LINE = "#B86E00", "#6B4A1A", "#FFF3DE", "#E8A33A"
AMBER_ZONE, AMBER_ZONE_LINE = "#FFF9EF", "#F2DDB5"
RED, RED_DARK, RED_SOFT = "#D33F35", "#B3261E", "#FDECEA"
ORANGE, YELLOW, GREEN, GREEN_SOFT = "#E0731F", "#B88A00", "#2E8B57", "#E5F3EA"

KINDS = {
    "svc": dict(fill="#FFFFFF", stroke=BLUE, title=INK, tag=BLUE, text=TEXT),
    "ctl": dict(fill="#FFFFFF", stroke="#A9B3C1", title=INK, tag=GREY, text=TEXT),
    "ext": dict(fill="#F6F7F9", stroke="#C9D0DA", title=INK, tag=GREY, text=TEXT),
    "dash": dict(fill="#FFFFFF", stroke="#A9B3C1", title=INK, tag=GREY, text=TEXT, dash="9 6"),
    "tpu": dict(fill=AMBER_FILL, stroke=AMBER_LINE, title=AMBER, tag=AMBER, text=AMBER_TEXT),
    "alert": dict(fill=RED_SOFT, stroke=RED, title=RED_DARK, tag=RED, text="#5B2A26"),
}

WARN: list[str] = []


def tw(s: str, size: float, mono: bool = False, weight: int = 400) -> float:
    """Грубая оценка ширины строки — только чтобы поймать текст, вылезающий из блока."""
    return len(s) * size * (0.6 if mono or weight >= 600 else 0.56)


def _pull(a, b, d):
    """Точка b, сдвинутая к a на d — чтобы остриё стрелки попало ровно в цель."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = (dx * dx + dy * dy) ** 0.5 or 1
    return b[0] - dx / n * d, b[1] - dy / n * d


class Svg:
    def __init__(self, name: str, label: str):
        self.name, self.label = name, label
        self.defs: dict[str, str] = {}
        self.body: list[str] = []

    def add(self, s: str) -> None:
        self.body.append(s)

    def rect(self, x, y, w, h, fill="#FFFFFF", stroke=None, sw=2, r=14, dash=None):
        a = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}"'
        if stroke:
            a += f' stroke="{stroke}" stroke-width="{sw}"'
        if dash:
            a += f' stroke-dasharray="{dash}"'
        self.add(a + "/>")

    def line(self, x1, y1, x2, y2, stroke=LINE, sw=1.5, dash=None):
        a = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}"'
        self.add(a + (f' stroke-dasharray="{dash}"' if dash else "") + "/>")

    def path(self, d, fill="none", stroke=INK, sw=2, dash=None):
        a = f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round"'
        self.add(a + (f' stroke-dasharray="{dash}"' if dash else "") + "/>")

    def circle(self, cx, cy, r, fill, stroke=None, sw=2):
        self.add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}"'
                 + (f' stroke="{stroke}" stroke-width="{sw}"' if stroke else "") + "/>")

    def text(self, x, y, s, size=18, weight=400, fill=INK, anchor="start", mono=False, ls=None, maxw=None):
        if maxw is not None and tw(s, size, mono, weight) > maxw:
            WARN.append(f"{self.name}: «{s}» ≈{tw(s, size, mono, weight):.0f}px > {maxw:.0f}px")
        extra = f' letter-spacing="{ls}"' if ls else ""
        if mono and s.startswith(" "):
            extra += ' xml:space="preserve" style="white-space:pre"'  # отступы в коде
        self.add(f'<text x="{x}" y="{y}" font-family="{MONO if mono else FONT}" font-size="{size}" '
                 f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{extra}>{html.escape(s, quote=False)}</text>')

    def label2(self, x, y, head, note=None, size=15, color=MUTED):
        """Подпись зоны: заглавная часть и пояснение строчными."""
        s = (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" fill="{color}">'
             f'<tspan font-weight="600" letter-spacing="1.6">{html.escape(head, quote=False)}</tspan>')
        if note:
            s += f'<tspan dx="14" font-weight="400">{html.escape(note, quote=False)}</tspan>'
        self.add(s + "</text>")

    def marker(self, color: str) -> str:
        mid = f"{self.name}-ah{color.strip('#')}"
        self.defs[mid] = (f'<marker id="{mid}" viewBox="0 0 14 12" refX="2" refY="6" markerWidth="14" '
                          f'markerHeight="12" markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
                          f'<path d="M0,0 L14,6 L0,12 z" fill="{color}"/></marker>')
        return mid

    def arrow(self, pts, color=BLUE, sw=3, dash=None, end=True, start=False,
              label=None, at=None, anchor="middle", lsize=16, lcolor=None, lweight=500, lmono=False):
        pts = [tuple(p) for p in pts]
        if end:
            pts[-1] = _pull(pts[-2], pts[-1], 12)
        if start:
            pts[0] = _pull(pts[1], pts[0], 12)
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        mid = self.marker(color)
        a = f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}" stroke-linejoin="round"'
        if dash:
            a += f' stroke-dasharray="{dash}"'
        if end:
            a += f' marker-end="url(#{mid})"'
        if start:
            a += f' marker-start="url(#{mid})"'
        self.add(a + "/>")
        if label:
            self.text(at[0], at[1], label, lsize, lweight, lcolor or color, anchor, mono=lmono)

    def render(self) -> str:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
                f'role="img" aria-label="{html.escape(self.label)}"><title>{html.escape(self.label)}</title>'
                f'<defs>{"".join(self.defs.values())}</defs><rect width="{W}" height="{H}" fill="#FFFFFF"/>'
                + "".join(self.body) + "</svg>")


# --- общие элементы ---------------------------------------------------------------------------

def header(s: Svg, eyebrow: str, title: str, sub: str) -> None:
    s.text(64, 78, eyebrow, 17, 600, BLUE, ls=2.5)
    s.text(64, 128, title, 44, 700, INK, maxw=W - 128)
    s.text(64, 168, sub, 22, 400, MUTED, maxw=W - 128)


def zone(s: Svg, x, y, w, h, head, note=None, fill=ZONE, stroke=ZONE_LINE, color=MUTED):
    s.rect(x, y, w, h, fill, stroke, 1.5, 20)
    s.label2(x + 24, y + 32, head, note, color=color)


def badge(s: Svg, xr, y, text, light=False):
    w = tw(text, 14, weight=600) + 22
    fill, fg = ("#FFFFFF", INK) if light else (INK, "#FFFFFF")
    s.rect(xr - w - 14, y - 14, w, 28, fill, INK if light else None, 1.5, 14)
    s.text(xr - w / 2 - 14, y + 5, text, 14, 600, fg, "middle")


def card(s: Svg, x, y, w, h, title, lines=(), tag=None, kind="svc", tsize=22, lsize=17, pad=20,
         tag_right=False, badge_text=None, tag_mono=True):
    k = KINDS[kind]
    s.rect(x, y, w, h, k["fill"], k["stroke"], 2, 14, k.get("dash"))
    inner = w - 2 * pad
    cy = y + pad + tsize * 0.78 + 2
    s.text(x + pad, cy, title, tsize, 600, k["title"], maxw=inner)
    if tag and tag_right:
        s.text(x + w - pad, cy, tag, 15, 500, k["tag"], "end", mono=tag_mono)
    elif tag:
        cy += 25
        s.text(x + pad, cy, tag, 15, 500, k["tag"], mono=tag_mono, maxw=inner)
    cy += 7
    for ln in lines:
        cy += lsize * 1.42
        s.text(x + pad, cy, ln, lsize, 400, k["text"], maxw=inner)
    if cy + 14 > y + h:
        WARN.append(f"{s.name}: «{title}» не влезает по высоте на {cy + 14 - y - h:.0f}px")
    if badge_text:
        badge(s, x + w, y, badge_text)


def cylinder(s: Svg, x, y, w, h, title, lines=(), ry=14):
    s.path(f"M{x},{y + ry} A{w / 2},{ry} 0 0 1 {x + w},{y + ry} L{x + w},{y + h - ry} "
           f"A{w / 2},{ry} 0 0 1 {x},{y + h - ry} Z", "#F6F7F9", "#AEB7C3", 2)
    s.path(f"M{x},{y + ry} A{w / 2},{ry} 0 0 0 {x + w},{y + ry}", "none", "#AEB7C3", 2)
    cx, cy = x + w / 2, y + 2 * ry + 30
    s.text(cx, cy, title, 21, 600, INK, "middle", maxw=w - 24)
    for ln in lines:
        cy += 24
        s.text(cx, cy, ln, 16, 400, TEXT, "middle", maxw=w - 24)


def pill(s: Svg, x, y, text, fill, fg, stroke=None, size=14, weight=600, h=26):
    w = tw(text, size, weight=weight) + 22
    s.rect(x, y, w, h, fill, stroke, 1.5, h / 2)
    s.text(x + w / 2, y + h / 2 + size * 0.36, text, size, weight, fg, "middle")
    return x + w


# --- 1. Обзор ---------------------------------------------------------------------------------

def d1() -> Svg:
    s = Svg("d1", "Решение как чёрный ящик: видео с камер на входе, оповещение о нарушении на выходе, "
                  "нейросети считаются на LinQ TPU")
    header(s, "СХЕМА 1 · ОБЗОР", "Как работает решение",
           "Видео с камер на входе, оповещение о нарушении техники безопасности на выходе")

    s.text(64, 330, "ВХОД", 15, 600, MUTED, ls=2)
    s.text(1440, 312, "ВЫХОД", 15, 600, MUTED, ls=2)
    for i, (t, ln) in enumerate([("Камеры цеха", "RTSP-поток с IP-камеры"),
                                 ("Видеозаписи", "файл, проигрывается по кругу"),
                                 ("Наборы кадров", "папка с фотографиями")]):
        y = 368 + i * 124
        card(s, 64, y, 360, 100, t, [ln], kind="ext", tsize=22, lsize=18)
        s.arrow([(424, y + 50), (620, y + 50)], INK, 3)

    # специалист по охране труда задаёт правила
    card(s, 690, 198, 480, 86, "Специалист по охране труда", ["рисует зоны, включает правила и расписание"],
         kind="ctl", tsize=21, lsize=17, pad=18)
    s.arrow([(930, 284), (930, 330)], GREY, 2.5, "8 6", label="настройка", at=(944, 314), anchor="start",
            lcolor=GREY)

    # чёрный ящик
    s.rect(620, 330, 620, 420, INK, r=18)
    s.text(660, 380, "ЧЁРНЫЙ ЯЩИК", 15, 600, "#8E9BB0", ls=2.5)
    s.text(660, 432, "Система видеоконтроля ТБ", 34, 700, "#FFFFFF", maxw=540)
    s.text(660, 474, "находит нарушения на каждом кадре", 20, 400, "#C9D2DE")
    s.text(660, 502, "и решает, когда поднять тревогу", 20, 400, "#C9D2DE")
    s.text(660, 556, "РАСПОЗНАЁТ СЕЙЧАС", 14, 600, "#8E9BB0", ls=2)
    for i, row in enumerate([["Человек в опасной зоне", "Телефон в руке"], ["Опасное сближение с техникой"],
                             ["Падение человека", "Потеря сознания", "Огонь"]]):
        x = 660
        for t in row:
            x = pill(s, x, 574 + i * 50, t, "#223047", "#FFFFFF", "#3B4B63", size=18, weight=400, h=40) + 10
        if x - 10 > 1200:
            WARN.append(f"d1: ряд «{' · '.join(row)}» выходит за чёрный ящик на {x - 1210:.0f}px")
    badge(s, 1240, 330, "подробно: схема 2 →", light=True)

    # LinQ TPU
    card(s, 730, 812, 400, 130, "LinQ TPU", ["российский ускоритель нейросетей", "стенд LinQ, связь через VPN"],
         kind="tpu", tsize=28, lsize=18)
    s.arrow([(880, 750), (880, 812)], AMBER, 3, label="кадр", at=(866, 790), anchor="end")
    s.arrow([(980, 812), (980, 750)], AMBER, 3, label="люди, позы, техника", at=(994, 790), anchor="start")

    # выходы
    card(s, 1440, 330, 420, 160, "Оповещение",
         ["диспетчеру и мастеру участка", "кадр с рамкой, клип, камера, время", "в браузере со звуком и в Telegram"],
         kind="alert", tsize=24, lsize=18)
    card(s, 1440, 518, 420, 104, "Журнал", ["история, статусы, кто что сделал"], kind="ctl", tsize=24, lsize=18)
    card(s, 1440, 646, 420, 104, "Дашборд", ["где и когда нарушают чаще"], kind="ctl", tsize=24, lsize=18)
    s.arrow([(1240, 410), (1440, 410)], RED, 3.5)
    s.arrow([(1240, 570), (1440, 570)], INK, 3)
    s.arrow([(1240, 698), (1440, 698)], INK, 3)

    # итог в цифрах
    s.line(64, 968, 1856, 968, LINE, 1.5)
    for x, num, cap in [(64, "835 мс", "кадр проходит обе нейросети на TPU"),
                        (680, "1,6 с", "от начала сближения с техникой до тревоги"),
                        (1296, "1 → 1", "одно нарушение — одно оповещение")]:
        s.text(x, 1024, num, 34, 700, INK)
        s.text(x + tw(num, 34, weight=700) + 10, 1024, cap, 19, 400, MUTED, maxw=600 - tw(num, 34, weight=700))
    return s


# --- 2. Внутри системы ------------------------------------------------------------------------

def d2() -> Svg:
    s = Svg("d2", "Внутри системы: камеры, захват видео, распознавание на LinQ TPU, анализ, журнал, оповещения; "
                  "горячий путь через очереди Redis Streams, управляющий контур отдельно")
    header(s, "СХЕМА 2 · ВНУТРИ ЧЁРНОГО ЯЩИКА", "Путь кадра: от камеры до оповещения",
           "Семь сервисов на Python в Docker Compose. Настройки и вход в горячем пути не участвуют")

    # управляющий контур
    zone(s, 230, 200, 1440, 145, "УПРАВЛЯЮЩИЙ КОНТУР")
    card(s, 263, 248, 493, 80, "Настройка камер", ["камеры, зоны-полигоны, правила, расписание"], tag="camera",
         kind="ctl", tsize=20, lsize=16, pad=18, tag_right=True)
    card(s, 1142, 248, 493, 80, "Вход и роли", ["пользователи, роли, участки, токены JWT"], tag="auth",
         kind="ctl", tsize=20, lsize=16, pad=18, tag_right=True)

    # горячий путь
    zone(s, 230, 395, 1440, 260, "ГОРЯЧИЙ ПУТЬ")
    y, h = 450, 170
    card(s, 40, y, 130, h, "Камеры", ["RTSP", "файлы", "кадры"], kind="ext", tsize=20, lsize=15, pad=18)
    boxes = [
        (263, "Захват видео", "ingest", ["читает поток", "5 кадр/с → JPEG", "буфер 20 с"], None),
        (556, "Распознавание", "inference", ["шлюз к LinQ TPU", "pose + objects", "резерв: CPU"], "схема 3"),
        (849, "Анализ", "analytics", ["трекинг людей", "сценарии", "подтверждение"], "схема 4"),
        (1142, "Журнал", "events", ["запись события", "клип ±5 с", "статусы, эскалация"], "схема 5"),
        (1435, "Оповещения", "notifications", ["WebSocket", "по роли и участку", "Telegram"], "схема 5"),
    ]
    for x, t, tag, lines, b in boxes:
        card(s, x, y, 200, h, t, lines, tag=tag, tsize=20, lsize=16, pad=18, badge_text=b)
    card(s, 1728, y, 150, h, "Люди", ["диспетчер", "мастер", "охрана труда"], kind="ext", tsize=20, lsize=15, pad=18)
    lane = y + 85
    for (x1, x2), lab in zip([(170, 263), (463, 556), (756, 849), (1049, 1142), (1342, 1435), (1635, 1728)],
                             ["видео", "кадры", "детекции", "нарушения", "события", "WebSocket"]):
        s.arrow([(x1, lane), (x2, lane)], BLUE, 3, label=lab, at=((x1 + x2) / 2, lane - 12), lsize=15)

    # настройка и доступ
    s.arrow([(420, 328), (420, 450)], GREY, 2.5, "8 6")
    s.arrow([(756, 288), (949, 288), (949, 450)], GREY, 2.5, "8 6", label="конфигурация", at=(852, 278),
            lcolor=GREY)
    s.arrow([(1535, 328), (1535, 450)], GREY, 2.5, "8 6", label="роль и участки", at=(1548, 375),
            anchor="start", lcolor=GREY)
    s.arrow([(1765, 450), (1765, 288), (1670, 288)], GREY, 2.5, "8 6", label="интерфейс", at=(1717, 278),
            lcolor=GREY)

    # стенд и хранилища
    card(s, 506, 735, 300, 130, "LinQ TPU", ["стенд LinQ, через VPN", "2 нейросети в INT8"], kind="tpu",
         tsize=24, lsize=16, badge_text="схема 6")
    s.arrow([(626, 620), (626, 735)], AMBER, 3, label="кадр", at=(614, 700), anchor="end")
    s.arrow([(686, 735), (686, 620)], AMBER, 3, label="люди и объекты", at=(700, 700), anchor="start")
    cylinder(s, 849, 735, 200, 130, "MinIO", ["снапшоты и клипы"])
    s.arrow([(949, 620), (949, 735)], GREY, 2.5, label="кадр с рамкой", at=(961, 700), anchor="start",
            lcolor=GREY)
    cylinder(s, 1142, 735, 200, 130, "PostgreSQL", ["журнал, история"])
    s.arrow([(1242, 620), (1242, 735)], GREY, 2.5, label="запись", at=(1254, 700), anchor="start", lcolor=GREY)
    card(s, 1435, 735, 200, 130, "Grafana", ["FPS и задержки", "всех сервисов"], tag="Prometheus", kind="ext",
         tsize=20, lsize=16, pad=18)

    # легенда
    s.line(64, 906, 1856, 906, LINE, 1.5)
    s.arrow([(64, 948), (124, 948)], BLUE, 3)
    s.text(140, 954, "горячий путь: очереди Redis Streams, сообщение снимается только после обработки, "
                     "рестарт сервиса ничего не теряет", 18, 400, TEXT)
    s.arrow([(64, 990), (124, 990)], GREY, 2.5, "8 6")
    s.text(140, 996, "настройка и доступ: если контур упадёт, детекция продолжит работать на кэше конфигурации "
                     "в Redis", 18, 400, TEXT)
    s.arrow([(64, 1032), (124, 1032)], AMBER, 3)
    s.text(140, 1038, "обмен со стендом LinQ", 18, 400, TEXT)
    badge(s, 560, 1032, "схема N")
    s.text(560, 1038, "блок подробно на следующих схемах", 18, 400, TEXT)
    return s


# --- 3. Распознавание на TPU ------------------------------------------------------------------

def d3() -> Svg:
    s = Svg("d3", "Распознавание: кадр уходит через VPN в RabbitMQ стенда LinQ, воркеры в Jupyter готовят тензоры, "
                  "две программы считаются на TPU одновременно, хвост сети и NMS — на CPU, ответ JSON")
    header(s, "СХЕМА 3 · ВНУТРИ БЛОКА «РАСПОЗНАВАНИЕ»", "Как кадр проходит через LinQ TPU",
           "Нейросети считаются на общем TPU стенда. Наш сервер говорит со стендом через очередь RabbitMQ")

    zone(s, 40, 200, 570, 600, "НАШ СЕРВЕР", "Docker")
    zone(s, 650, 200, 1230, 600, "СТЕНД LINQ", "hackathon.lin-q.ru · VPN 10.0.114.0/24",
         AMBER_ZONE, AMBER_ZONE_LINE, AMBER)
    top, bot, mid = 262, 770, 525
    req, rep = 400, 650

    def frame(x, w, kind="svc"):
        k = KINDS[kind]
        s.rect(x, top, w, bot - top, k["fill"], k["stroke"], 2, 14)
        s.line(x + 16, mid, x + w - 16, mid, k["stroke"], 1, "4 5")

    # наш inference
    frame(70, 300)
    s.text(92, 308, "Распознавание", 24, 600, INK)
    s.text(92, 334, "inference", 15, 500, BLUE, mono=True)
    for i, t in enumerate(["берёт кадр из очереди", "старше 2 с — пропускает", "камера занята — пропуск",
                           "сжимает до 640 px", "до 4 кадров в работе"]):
        s.text(92, 374 + i * 26, t, 17, 400, TEXT, maxw=256)
    for i, t in enumerate(["получает JSON", "кладёт детекции", "в очередь анализа"]):
        s.text(92, 578 + i * 26, t, 17, 400, TEXT, maxw=256)
    badge(s, 370, top, "→ схема 4")

    # VPN
    s.rect(430, 330, 140, 390, "#F6F7F9", "#C9D0DA", 2, 14)
    s.text(500, 500, "linq-vpn", 17, 600, INK, "middle", mono=True)
    for i, t in enumerate(["OpenVPN", "в Docker", "порт 5672"]):
        s.text(500, 528 + i * 24, t, 15, 400, TEXT, "middle")

    # RabbitMQ
    frame(690, 240, "ctl")
    s.text(712, 308, "RabbitMQ", 24, 600, INK)
    s.text(712, 334, "брокер стенда", 15, 400, MUTED)

    def queue(y):
        for j in range(6):
            s.rect(712 + j * 30, y, 22, 30, BLUE_SOFT, BLUE, 1.5, 4)

    queue(362)
    s.text(712, 424, "cvhack12731.jpeg", 15, 600, INK, mono=True, maxw=196)
    s.text(712, 452, "наша очередь кадров", 16, 400, TEXT, maxw=196)
    s.text(712, 476, "её разбирают воркеры", 16, 400, TEXT, maxw=196)
    queue(556)
    s.text(712, 616, "reply_to", 15, 600, INK, mono=True)
    s.text(712, 644, "временная очередь", 16, 400, TEXT, maxw=196)
    s.text(712, 668, "ответа клиенту", 16, 400, TEXT, maxw=196)

    # воркеры
    frame(1010, 380, "ctl")
    s.text(1032, 308, "4 воркера", 24, 600, INK)
    s.text(1032, 334, "Python в Jupyter стенда, CPU", 15, 400, MUTED)
    s.text(1032, 378, "Подготовка", 19, 600, INK)
    for i, t in enumerate(["JPEG → RGB → letterbox 640×640", "тензор для каждой модели", "обе задачи на TPU сразу"]):
        s.text(1032, 406 + i * 26, t, 17, 400, TEXT, maxw=336)
    s.text(1032, 574, "Хвост сети на CPU", 19, 600, INK)
    for i, t in enumerate(["ONNX: DFL-декод рамок, NMS", "люди и 17 точек скелета", "погрузчик, рохля, телефон",
                           "ответ — JSON в reply_to"]):
        s.text(1032, 602 + i * 26, t, 17, 400, TEXT, maxw=336)

    # TPU
    frame(1470, 380, "tpu")
    s.text(1492, 310, "LinQ TPU", 26, 700, AMBER)
    s.text(1492, 336, "общие ускорители стенда", 15, 400, AMBER_TEXT)
    s.text(1492, 376, "tpu.direct → input", 15, 500, AMBER_TEXT, mono=True)
    for i, t in enumerate(["pose.tpu · YOLOv8n-pose", "objects.tpu · YOLOv8s"]):
        s.rect(1492, 394 + i * 52, 336, 40, "#FFFFFF", AMBER_LINE, 1.5, 10)
        s.text(1508, 420 + i * 52, t, 16, 500, INK)
    for i, t in enumerate(["считает тело сети в INT8", "float32 ↔ int8 — сам рантайм", "отдаёт выходы ветвей",
                           "рамок, классов и точек"]):
        s.text(1492, 574 + i * 26, t, 17, 400, AMBER_TEXT, maxw=336)
    badge(s, 1850, top, "модели: схема 6")

    # дорожки запроса и ответа
    s.arrow([(370, req), (430, req)], BLUE, 3)
    s.arrow([(570, req), (690, req)], BLUE, 3, label="JPEG", at=(630, req - 12))
    s.arrow([(930, req), (1010, req)], BLUE, 3, label="JPEG", at=(970, req - 12))
    s.arrow([(1390, req), (1470, req)], BLUE, 3, label="тензоры", at=(1430, req - 12), lsize=15)
    s.arrow([(1470, rep), (1390, rep)], GREEN, 3, label="выходы", at=(1430, rep - 12), lsize=15)
    s.arrow([(1010, rep), (930, rep)], GREEN, 3, label="JSON", at=(970, rep - 12))
    s.arrow([(690, rep), (570, rep)], GREEN, 3, label="JSON", at=(630, rep - 12))
    s.arrow([(430, rep), (370, rep)], GREEN, 3)

    # резерв
    s.arrow([(220, 770), (220, 850)], GREY, 2.5, "8 6", label="стенд не отвечает", at=(234, 822), anchor="start",
            lcolor=GREY)
    card(s, 40, 850, 570, 160, "Резерв: CPU нашего сервера",
         ["те же модели в ONNX Runtime", "3 ошибки подряд → 30 с на CPU → снова TPU",
          "активный режим виден в метриках"], kind="dash", tsize=22, lsize=17)

    # замеры
    s.text(650, 868, "ЗАМЕР 24.10.2026 · 4 КАМЕРЫ ПО 5 КАДР/С · POSE + OBJECTS", 15, 600, MUTED, ls=1.6)
    for x, num, cap, sub in [(650, "835 мс", "средняя задержка кадра", "TPU 532 мс · сеть и брокер 266 мс"),
                             (1070, "4,3 кадр/с", "суммарно через TPU", "лишние кадры пропускаются"),
                             (1490, "TPU = CPU", "рамки совпадают,", "уверенность ±0,05")]:
        s.line(x, 890, x, 1006, AMBER_LINE, 3)
        s.text(x + 20, 940, num, 40, 700, INK)
        s.text(x + 20, 972, cap, 17, 400, TEXT, maxw=360)
        s.text(x + 20, 997, sub, 16, 400, MUTED, maxw=360)
    return s


# --- 4. Анализ --------------------------------------------------------------------------------

def d4() -> Svg:
    s = Svg("d4", "Анализ: детекции, трекинг, сценарии-плагины и автомат подтверждения; пример на временной шкале — "
                  "случайный кадр не поднимает тревогу, нарушение даёт одно оповещение")
    header(s, "СХЕМА 4 · ВНУТРИ БЛОКА «АНАЛИЗ»", "Как детекции становятся одним оповещением",
           "Случайный кадр тревогу не поднимает: нарушение должно длиться несколько секунд подряд")

    steps = [("Детекции кадра", "от TPU", ["люди, позы, техника, телефоны", "огонь — по цвету на CPU"], "svc"),
             ("Трекинг людей", "ByteTrack", ["у каждого человека свой", "номер от кадра к кадру"], "svc"),
             ("Сценарии", "scenarios/*.py", ["оценка человека или кадра", "0…1 по правилам камеры"], "svc"),
             ("Подтверждение", "конечный автомат", ["нарушение должно длиться", "несколько секунд подряд"], "svc"),
             ("Событие", "violations", ["начало и конец нарушения", "→ журнал и оповещения"], "alert")]
    for i, (t, tag, lines, kind) in enumerate(steps):
        y = 200 + i * 168
        card(s, 40, y, 340, 144, t, lines, tag=tag, kind=kind, tsize=22, lsize=17)
        if i:
            s.arrow([(210, y - 24), (210, y)], BLUE, 3)

    # сценарии
    zone(s, 440, 200, 1440, 440, "ВНУТРИ «СЦЕНАРИИ»", "каждый тип нарушения — отдельный плагин")
    s.arrow([(380, 608), (440, 608)], GREY, 2.5, "6 5")
    cards = [("Человек в опасной зоне", ("ВЫСОКАЯ", ORANGE), "pose", "окно 2 с",
              "точка опоры человека внутри полигона"),
             ("Опасное сближение с техникой", ("КРИТИЧНАЯ", RED), "pose + objects", "окно 1 с",
              "ближе 1 роста к погрузчику или рохле"),
             ("Телефон в руке", ("СРЕДНЯЯ", YELLOW), "pose + objects", "окно 3 с",
              "у кисти или головы, ближе 0,15 роста"),
             ("Падение человека", ("КРИТИЧНАЯ", RED), "pose", "переход ≤ 2 с",
              "стоял — и рядом оказался лёжа"),
             ("Потеря сознания", ("КРИТИЧНАЯ", RED), "pose", "окно 4 с",
              "лежит почти без движения"),
             ("Огонь", ("КРИТИЧНАЯ", RED), "без нейросети", "окно 2 с",
              "цвет пламени и мерцание, не на людях")]
    for i, (t, (sev, col), models, win, ln) in enumerate(cards):
        x, y = 464 + i % 3 * 470, 252 + i // 3 * 122
        s.rect(x, y, 450, 110, "#FFFFFF", "#C9D0DA", 2, 14)
        s.text(x + 20, y + 34, t, 21, 600, INK, maxw=410)
        px = pill(s, x + 20, y + 46, sev, col, "#FFFFFF")
        px = pill(s, px + 8, y + 46, models, BLUE_SOFT, BLUE, weight=500)
        pill(s, px + 8, y + 46, win, "#EEF0F3", TEXT, weight=500)
        s.text(x + 20, y + 96, ln, 17, 400, TEXT, maxw=410)
    s.rect(464, 498, 660, 130, "#F6F7F9", "#D5DBE3", 1.5, 12)
    code = ["@register", "class FallScenario(ScenarioBase):", '    requires = {"pose"}',
            "    params_schema = {...}  # форма в интерфейсе",
            "    def check(self, track, scene, params): ...  # 0…1"]
    for j, ln in enumerate(code):
        s.text(486, 526 + j * 21, ln, 15, 400, BLUE if j == 0 else INK, mono=True, maxw=620)
    for j, ln in enumerate(["Новый тип нарушения — новый файл в scenarios/:",
                            "так добавлены падение, потеря сознания и огонь.",
                            "Форма параметров в интерфейсе строится по JSON Schema.",
                            "Подтверждение, окончание, подавление повторов",
                            "и склейку треков делает каркас, а не сценарий."]):
        s.text(1154, 524 + j * 23, ln, 17, 400, TEXT, maxw=700)

    # временная шкала
    zone(s, 440, 664, 1440, 386, "ВНУТРИ «ПОДТВЕРЖДЕНИЕ»", "пример: человек у погрузчика, 5 кадров в секунду")
    s.arrow([(380, 776), (440, 776)], GREY, 2.5, "6 5")
    x0, x1, dur = 560, 1840, 14.0
    pps = (x1 - x0) / dur

    def X(t):
        return x0 + t * pps

    def positive(t):
        t = round(t, 1)
        if t == 0.6:
            return True
        if 2.8 <= t <= 7.6 and t not in (3.4, 5.6, 5.8):
            return True
        return 12.0 <= t <= 12.8

    fy, by = 862, 906
    s.text(464, fy + 22, "кадры", 15, 500, MUTED)
    s.text(464, by + 21, "состояние", 15, 500, MUTED)
    for i in range(70):
        t = i * 0.2
        s.rect(X(t) + 3, fy, 12, 32, RED if positive(t) else "#D5DBE3", r=3)
    bands = [(0, 0.6, "#EDF0F4", MUTED, "нет"), (0.6, 1.8, "#FBE3B5", "#7A5200", "кандидат"),
             (1.8, 2.8, "#EDF0F4", MUTED, "нет"), (2.8, 3.8, "#FBE3B5", "#7A5200", "кандидат"),
             (3.8, 10.6, RED, "#FFFFFF", "НАРУШЕНИЕ АКТИВНО"), (10.6, 14.0, "#DDE2E9", TEXT, "пауза: повторы подавлены")]
    for a, b, fill, fg, lab in bands:
        s.rect(X(a) + 1, by, X(b) - X(a) - 2, 30, fill, r=4)
        s.text((X(a) + X(b)) / 2, by + 20, lab, 14, 600, fg, "middle", maxw=X(b) - X(a) - 6)
    for t in range(0, 15, 2):
        s.text(X(t), 962, f"{t} с", 15, 400, MUTED, "middle")

    # пояснения над кадрами
    s.text(X(0.6) + 9, 818, "случайный кадр", 16, 500, TEXT, "middle")
    s.text(X(0.6) + 9, 840, "тревоги нет", 16, 400, MUTED, "middle")
    s.path(f"M{X(2.8) + 3},{fy - 6} V{fy - 14} H{X(3.8) + 15} V{fy - 6}", stroke=TEXT, sw=1.5)
    s.text(X(3.8) - 10, 790, "окно 1 с:", 16, 500, TEXT, "end")
    s.text(X(3.8) - 10, 812, "≥ 70 % кадров «да»", 16, 400, MUTED, "end")
    s.line(X(3.8), 736, X(3.8), by + 30, RED, 2, "5 4")
    s.text(X(3.8) + 12, 754, "оповещение, один раз", 17, 600, RED)
    s.text(X(5.7) + 9, 818, "короткий пропуск", 16, 500, TEXT, "middle")
    s.text(X(5.7) + 9, 840, "нарушение не рвёт", 16, 400, MUTED, "middle")
    s.path(f"M{X(7.6) + 15},{fy - 6} V{fy - 14} H{X(10.6)} V{fy - 6}", stroke=TEXT, sw=1.5)
    s.text((X(7.6) + X(10.6)) / 2, 818, "3 с без «да»", 16, 500, TEXT, "middle")
    s.text((X(7.6) + X(10.6)) / 2, 840, "→ нарушение закрыто", 16, 400, MUTED, "middle")
    s.text(X(12.4) + 9, 818, "повтор во время паузы", 16, 500, TEXT, "middle")
    s.text(X(12.4) + 9, 840, "не оповещает", 16, 400, MUTED, "middle")

    s.rect(464, 990, 14, 14, RED, r=3)
    s.text(486, 1003, "сценарий сказал «да»", 16, 400, TEXT)
    s.rect(680, 990, 14, 14, "#D5DBE3", r=3)
    s.text(702, 1003, "«нет»", 16, 400, TEXT)
    s.text(800, 1003, "Человек скрылся за техникой и появился рядом в течение 5 с — это то же нарушение "
                      "(склейка треков).", 16, 400, TEXT, maxw=1060)
    s.text(464, 1032, "Окна и пороги (confirm_s, release_s, cooldown_s) — параметры правила, "
                      "задаются в интерфейсе для каждой камеры.", 16, 400, MUTED, maxw=1400)
    return s


# --- 5. Журнал и оповещения -------------------------------------------------------------------

def d5() -> Svg:
    s = Svg("d5", "После подтверждения: кадр с рамкой и клип сохраняются в MinIO, событие пишется в журнал, "
                  "оповещение уходит людям по роли и участку, статусы и эскалация")
    header(s, "СХЕМА 5 · ВНУТРИ БЛОКОВ «ЖУРНАЛ» И «ОПОВЕЩЕНИЯ»", "Что происходит после подтверждения нарушения",
           "Доказательства сохраняются сразу, оповещение получают те, кому оно нужно, а без реакции включается эскалация")

    card(s, 40, 210, 320, 170, "Анализ", ["нарушение подтверждено", "рисует рамку и зону", "на кадре"],
         tag="analytics", tsize=22, lsize=17)
    card(s, 470, 210, 400, 170, "Журнал", ["запись в PostgreSQL", "SHA-256 кадра для проверок", "запрос клипа ±5 с"],
         tag="events", tsize=22, lsize=17)
    card(s, 980, 210, 400, 170, "Оповещения", ["WebSocket: звук для критичных", "Telegram с кадром",
                                               "фильтр по роли и участку"], tag="notifications", tsize=22, lsize=17)
    card(s, 470, 540, 400, 150, "Захват видео", ["кольцевой буфер 20 с", "собирает MP4 (H.264)"], tag="ingest",
         tsize=22, lsize=17)
    cylinder(s, 40, 540, 320, 150, "MinIO", ["кадр с рамкой", "клип MP4"])

    s.arrow([(360, 295), (470, 295)], BLUE, 3, label="нарушение", at=(415, 283))
    s.arrow([(870, 295), (980, 295)], BLUE, 3, label="событие", at=(925, 283))
    s.arrow([(200, 380), (200, 540)], GREY, 2.5, label="кадр с рамкой", at=(214, 466), anchor="start", lcolor=GREY)
    s.arrow([(620, 380), (620, 540)], GREY, 2.5, "8 6", label="запрос клипа", at=(608, 466), anchor="end",
            lcolor=GREY)
    s.arrow([(720, 540), (720, 380)], GREY, 2.5, "8 6", label="клип готов", at=(732, 466), anchor="start",
            lcolor=GREY)
    s.arrow([(470, 615), (360, 615)], GREY, 2.5, label="клип", at=(415, 603), lcolor=GREY)

    # люди
    people = [("Диспетчер", "все события, передаёт мастеру"), ("Мастер участка", "только свой участок"),
              ("Охрана труда, руководитель", "журнал, дашборд, эскалации")]
    for i, (t, ln) in enumerate(people):
        card(s, 1490, 200 + i * 108, 390, 92, t, [ln], kind="ext", tsize=20, lsize=17, pad=18)
    s.path("M1380,295 H1435 M1435,246 V462", stroke=BLUE, sw=3)
    for i in range(3):
        s.arrow([(1435, 246 + i * 108), (1490, 246 + i * 108)], BLUE, 3)
    card(s, 1490, 540, 390, 170, "В оповещении", ["тип и важность нарушения", "камера, зона, время",
                                                  "кадр с рамкой — сразу", "клип — следом, через 5–10 с"],
         kind="alert", tsize=20, lsize=17, pad=18)

    # разбор события
    zone(s, 40, 728, 1840, 328, "РАЗБОР СОБЫТИЯ", "каждое действие пишется в историю: кто, что и когда")

    def status(x, y, w, text, fill, stroke):
        s.rect(x, y, w, 50, fill, stroke, 2, 25)
        s.text(x + w / 2, y + 32, text, 19, 600, INK, "middle", maxw=w - 20)

    status(110, 850, 200, "Новое", BLUE_SOFT, BLUE)
    for i, t in enumerate(["Подтверждено", "Передано мастеру", "Ложное"]):
        status(560, 784 + i * 66, 260, t, "#FFFFFF", GREY)
    status(1060, 817, 220, "Устранено", GREEN_SOFT, GREEN)
    s.path("M310,875 H480 M480,809 V941", stroke=INK, sw=2.5)
    for i in range(3):
        s.arrow([(480, 809 + i * 66), (560, 809 + i * 66)], INK, 2.5)
    s.path("M820,875 H940", stroke=INK, sw=2.5)
    s.arrow([(820, 809), (940, 809), (940, 842), (1060, 842)], INK, 2.5)
    s.path("M940,875 V842", stroke=INK, sw=2.5)
    s.arrow([(820, 941), (1060, 941)], GREY, 2.5, "8 6")
    card(s, 1060, 912, 500, 58, "доля подтверждённых = точность по сценариям", kind="ext", tsize=17, pad=16)
    s.arrow([(210, 900), (210, 938)], RED, 2.5, "6 5")
    card(s, 64, 938, 380, 106, "Эскалация", ["не принято за 2–60 мин по важности", "→ руководству, охране труда, мастеру"],
         kind="alert", tsize=19, lsize=16, pad=16)
    card(s, 1600, 784, 256, 116, "Журнал и дашборд", ["фильтры: тип, камера,", "зона, время; CSV"],
         kind="ext", tsize=19, lsize=16, pad=18)
    return s


# --- 6. Подготовка моделей --------------------------------------------------------------------

def d6() -> Svg:
    s = Svg("d6", "Подготовка моделей: данные, обучение, экспорт ONNX, разрез графа, калибровка и INT8, "
                  "компиляция под TPU_H1M, загрузка на стенд; проверки на каждом шаге")
    header(s, "СХЕМА 6 · ОТКУДА БЕРУТСЯ НЕЙРОСЕТИ ДЛЯ TPU", "Как модель попадает на LinQ TPU",
           "Обучаем у себя, квантуем и компилируем в Docker с SDK LinQ 2026.9.45, программу кладём на стенд")

    def step(n, x, y, title, lines, w=430, h=200):
        s.rect(x, y, w, h, "#FFFFFF", BLUE, 2, 14)
        s.circle(x + 38, y + 40, 18, INK)
        s.text(x + 38, y + 47, str(n), 18, 700, "#FFFFFF", "middle")
        s.text(x + 68, y + 48, title, 22, 600, INK, maxw=w - 88)
        for j, ln in enumerate(lines):
            s.text(x + 22, y + 92 + j * 26, ln, 17, 400, TEXT, maxw=w - 44)

    xs = [40, 510, 980, 1450]
    step(1, xs[0], 200, "Данные", ["LOCO (склады): погрузчик, рохля", "COCO: телефон в руке",
                                   "9 120 рамок для обучения", "проверка — на другом складе"])
    step(2, xs[1], 200, "Обучение", ["YOLOv8s на своей GPU", "ранняя остановка: 19-я эпоха из 34",
                                     "поза: готовая YOLOv8n-pose"])
    step(3, xs[2], 200, "Экспорт в ONNX", ["вход фиксирован: 1×3×640×640", "TPU не умеет динамические формы",
                                           "NMS и декодирование — вне графа"])
    step(4, xs[3], 200, "Разрез графа", [])
    bx, bw = xs[3] + 22, 386
    s.rect(bx, 270, 236, 40, AMBER_FILL, AMBER_LINE, 2, 8)
    s.text(bx + 118, 296, "тело сети → TPU", 16, 600, AMBER, "middle")
    s.rect(bx + 242, 270, bw - 242, 40, "#EEF0F3", "#B4BCC7", 2, 8)
    s.text(bx + 242 + (bw - 242) / 2, 296, "хвост → CPU", 16, 600, TEXT, "middle")
    s.text(bx, 344, "DFL-декод и сигмоида — в ONNX-хвост,", 17, 400, TEXT, maxw=386)
    s.text(bx, 370, "сверяем с полной моделью", 17, 400, TEXT, maxw=386)
    for i in range(3):
        s.arrow([(xs[i] + 430, 300), (xs[i + 1], 300)], BLUE, 3)
    s.arrow([(1665, 400), (1665, 435), (255, 435), (255, 470)], BLUE, 3)

    step(5, xs[0], 470, "Калибровка и INT8", ["160 реальных кадров из обучения", "отсечение выбросов активаций",
                                              "(перцентиль 99,9)", "эмулятор INT8 — без стенда"])
    step(6, xs[1], 470, "Компиляция под TPU_H1M", ["пресет O5, при ошибке — O1", "batch = 1, программа .tpu",
                                                   "хэш содержимого в имени файла"])
    step(7, xs[2], 470, "На стенд LinQ", ["программа → /auto/cache/<логин>/", "meta.json и ONNX-хвост → воркеры",
                                          "запуск воркеров одним скриптом"])
    s.rect(xs[3], 470, 430, 200, AMBER_FILL, AMBER_LINE, 2, 14)
    s.text(xs[3] + 22, 518, "2 программы для TPU", 22, 600, AMBER)
    s.text(xs[3] + 22, 556, "yolov8n_pose_b1_o1_h1m.tpu", 14, 500, INK, mono=True, maxw=386)
    s.text(xs[3] + 22, 578, "люди и 17 точек скелета", 16, 400, AMBER_TEXT)
    s.text(xs[3] + 22, 614, "yolov8s_objects_b1_o1_h1m_1b310853.tpu", 14, 500, INK, mono=True, maxw=386)
    s.text(xs[3] + 22, 636, "погрузчик, рохля, телефон", 16, 400, AMBER_TEXT)
    for i in range(3):
        s.arrow([(xs[i] + 430, 570), (xs[i + 1], 570)], BLUE, 3)

    # проверки
    zone(s, 40, 730, 900, 316, "ПРОВЕРКА НА КАЖДОМ ШАГЕ")
    for i, (t, ln) in enumerate([("Тело + хвост = полная модель", "verify_split на реальных кадрах, CPU"),
                                 ("Эмулятор INT8 повторяет TPU", "подбор квантования без очереди стенда"),
                                 ("TPU = CPU на стенде", "те же рамки, уверенность ±0,05")]):
        y = 806 + i * 80
        s.circle(84, y - 7, 16, GREEN_SOFT, GREEN, 2)
        s.path(f"M{76},{y - 7} l6,6 l10,-12", stroke=GREEN, sw=3)
        s.text(114, y, t, 19, 600, INK)
        s.text(114, y + 26, ln, 17, 400, TEXT)

    # найденная проблема
    zone(s, 980, 730, 900, 316, "ЧТО НАШЛИ И ИСПРАВИЛИ", None, AMBER_ZONE, AMBER_ZONE_LINE, AMBER)
    s.text(1004, 800, "С калибровкой по умолчанию TPU не видел технику:", 18, 400, TEXT, maxw=852)
    s.text(1004, 826, "логиты классов совпадали с float-моделью лишь на 0,65.", 18, 400, TEXT, maxw=852)
    s.text(1004, 868, "КОРРЕЛЯЦИЯ ЛОГИТОВ TPU И FLOAT-МОДЕЛИ", 14, 600, MUTED, ls=1.5)
    z, one = 1180, 1740
    s.line(z, 882, z, 970, LINE, 1.5)
    for y, lab, v, fill, col in [(888, "по умолчанию", 0.65, RED_SOFT, RED), (928, "отсечение 99,9", 0.98, GREEN_SOFT, GREEN)]:
        s.text(z - 14, y + 20, lab, 16, 500, TEXT, "end")
        s.rect(z, y, (one - z) * v, 28, fill, col, 2, 6)
        s.text(z + (one - z) * v + 10, y + 21, f"{v:.2f}".replace(".", ","), 18, 700, col)
    s.text(z, 988, "0", 14, 400, MUTED, "middle")
    s.text(one, 988, "1", 14, 400, MUTED, "middle")
    s.text(1004, 1024, "Отсекли 0,1 % самых больших активаций при калибровке — TPU снова видит технику.",
           17, 400, TEXT, maxw=852)
    return s


# --- 7. Стек ----------------------------------------------------------------------------------

def d7() -> Svg:
    s = Svg("d7", "Что использовано в решении по слоям: LinQ TPU и SDK, нейросети, связь со стендом, видео, бэкенд, "
                  "хранилища, интерфейс, наблюдаемость и запуск")
    header(s, "СХЕМА 7 · СТЕК", "Что мы использовали",
           "Всё работает на одной машине в Docker Compose; внешний ресурс один — TPU стенда LinQ")
    rows = [
        ("LinQ TPU", "считает нейросети", "tpu",
         ["LinQ TPU, платформа H1M", "SDK tpu_framework 2026.9.45", "INT8, калибровка 99,9 перцентиля",
          "2 программы .tpu"], 4),
        ("Нейросети", "люди, позы, техника", "svc",
         ["YOLOv8n-pose · люди и 17 точек", "YOLOv8s · погрузчик, рохля, телефон", "Ultralytics 8.4",
          "ONNX Runtime — резерв на CPU", "LOCO + COCO 2017"], 2),
        ("Связь со стендом", "кадр туда, JSON обратно", "svc",
         ["OpenVPN в контейнере", "RabbitMQ стенда", "4 воркера в Jupyter", "pika", "ljup — Jupyter из консоли"], 2),
        ("Видео", "камеры и клипы", "svc",
         ["RTSP-камеры", "MediaMTX → HLS в браузер", "FFmpeg", "OpenCV", "клипы MP4 H.264"], 2),
        ("Бэкенд", "7 сервисов на Python", "svc",
         ["Python 3.12", "FastAPI", "Redis Streams — очереди", "ByteTrack — трекинг", "Shapely — зоны",
          "JWT RS256"], 3),
        ("Хранилища", "журнал, кадры, клипы", "svc",
         ["PostgreSQL 16 — журнал", "Redis 7 — кадры и состояние", "MinIO — снапшоты и клипы"], 0),
        ("Интерфейс", "6 ролей, 10 экранов", "svc",
         ["React 18 + TypeScript", "Ant Design", "ECharts", "react-konva — редактор зон",
          "формы по JSON Schema", "WebSocket"], 1),
        ("Наблюдаемость и запуск", "одна команда", "svc",
         ["Prometheus", "Grafana", "Traefik — один порт", "Docker Compose", "pytest — 31 тест"], 2),
    ]
    def chip_w(text: str, size: float) -> float:
        """Ширина подписи по классам символов: у плашек стека разная длина, и грубая оценка tw() даёт неровные поля."""
        em = 0.0
        for ch in text:
            if ch in " .,:·'-": em += 0.3
            elif ch in "ijlrtf1I": em += 0.32
            elif ch in "mwMWЖШЩМЮшщжмю—": em += 0.86
            elif ch.isdigit(): em += 0.58
            elif ch.isupper(): em += 0.68
            else: em += 0.56
        return em * size

    def chip(x, y, text, fill, fg, stroke, size=17, h=40):
        w = chip_w(text, size) + 32
        s.rect(x, y, w, h, fill, stroke, 1.5, h / 2)
        s.text(x + w / 2, y + h / 2 + size * 0.36, text, size, 500, fg, "middle")
        return x + w

    y0, rh, gap, cx = 200, 88, 10, 448
    for i, (title, note, kind, chips, key) in enumerate(rows):
        y = y0 + i * (rh + gap)
        tpu = kind == "tpu"
        s.rect(64, y, 1792, rh, AMBER_ZONE if tpu else ZONE, AMBER_ZONE_LINE if tpu else ZONE_LINE, 1.5, 16)
        s.text(90, y + 38, title, 21, 600, AMBER if tpu else INK, maxw=340)
        s.text(90, y + 64, note, 16, 400, AMBER_TEXT if tpu else MUTED, maxw=340)
        x = cx
        for j, label in enumerate(chips):
            if tpu:
                fill, fg, stroke = AMBER_FILL, AMBER_TEXT, AMBER_LINE
            elif j < key:
                fill, fg, stroke = BLUE_SOFT, INK, BLUE
            else:
                fill, fg, stroke = "#FFFFFF", INK, "#C3CBD6"
            x = chip(x, y + 24, label, fill, fg, stroke) + 12
        if x > 1856:
            WARN.append(f"d7: ряд «{title}» шире слайда на {x - 1856:.0f}px")
    s.line(64, 990, 1856, 990, LINE, 1.5)
    for x, num, cap in [(64, "7", "сервисов на Python"), (420, "2", "нейросети на TPU за один кадр"),
                        (900, "6", "сценариев: нарушения и ЧП"), (1260, "1", "команда запуска: docker compose up")]:
        s.text(x, 1040, num, 34, 700, INK)
        s.text(x + tw(num, 34, weight=700) + 12, 1040, cap, 19, 400, MUTED)
    return s


DIAGRAMS = [("01-obzor", d1), ("02-vnutri", d2), ("03-tpu", d3), ("04-analiz", d4), ("05-sobytie", d5),
            ("06-modeli", d6), ("07-stek", d7)]


def find_chrome() -> str | None:
    for p in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              "google-chrome", "chromium", "chromium-browser"]:
        if Path(p).is_file() or shutil.which(p):
            return p
    return None


def render_png(svg: str, png: Path, chrome: str) -> None:
    page = (f'<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="{FONTS_CSS}">'
            f'<style>html,body{{margin:0;background:#fff}}svg{{display:block}}</style></head><body>{svg}</body></html>')
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "page.html"
        src.write_text(page, encoding="utf-8")
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                        f"--window-size={W},{H}", "--virtual-time-budget=10000", f"--user-data-dir={tmp}/profile",
                        f"--screenshot={png}", src.as_uri()], check=True, capture_output=True, timeout=120)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    only = set(sys.argv[1:])
    chrome = find_chrome()
    for name, fn in DIAGRAMS:
        if only and name[:2] not in only:
            continue
        svg = fn().render()
        (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
        if chrome:
            render_png(svg, OUT / f"{name}.png", chrome)
        print(name)
    for w in WARN:
        print("WARN", w)
    if not chrome:
        print("Chrome не найден: собраны только SVG")


if __name__ == "__main__":
    main()
