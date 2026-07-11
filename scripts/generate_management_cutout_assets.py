#!/usr/bin/env python3
from __future__ import annotations

import argparse
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


WIDTH = 1536
HEIGHT = 864
NAVY = (13, 25, 44)
GRAPHITE = (31, 42, 57)
SLATE = (56, 71, 88)
IVORY = (232, 226, 207)
AMBER = (226, 158, 61)
COPPER = (172, 92, 54)
TEAL = (62, 130, 130)


def paper_background(seed: int) -> Image.Image:
    rng = random.Random(seed)
    image = Image.new("RGB", (WIDTH, HEIGHT), NAVY)
    pixels = image.load()
    for y in range(HEIGHT):
        light = int(12 * (1 - y / HEIGHT))
        for x in range(WIDTH):
            noise = rng.randint(-5, 5)
            pixels[x, y] = tuple(max(0, min(255, value + light + noise)) for value in NAVY)
    haze = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(haze)
    draw.ellipse((820, -240, 1660, 620), fill=(226, 158, 61, 32))
    draw.ellipse((-320, 390, 680, 1180), fill=(62, 130, 130, 20))
    return Image.alpha_composite(image.convert("RGBA"), haze.filter(ImageFilter.GaussianBlur(90)))


def shadowed_polygon(image: Image.Image, points: list[tuple[int, int]], fill: tuple[int, int, int], shadow: int = 18) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    shifted = [(x + shadow, y + shadow) for x, y in points]
    draw.polygon(shifted, fill=(0, 0, 0, 105))
    image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(13)))
    draw = ImageDraw.Draw(image)
    draw.polygon(points, fill=fill + (255,))
    draw.line(points + [points[0]], fill=IVORY + (75,), width=3)


def card(image: Image.Image, box: tuple[int, int, int, int], fill: tuple[int, int, int], accent: tuple[int, int, int] = AMBER) -> None:
    x1, y1, x2, y2 = box
    shadowed_polygon(image, [(x1, y1), (x2, y1 - 8), (x2 - 6, y2), (x1 + 8, y2 + 7)], fill)
    draw = ImageDraw.Draw(image)
    draw.rectangle((x1 + 34, y1 + 40, x2 - 38, y1 + 51), fill=accent + (190,))
    draw.rectangle((x1 + 34, y1 + 76, x2 - 92, y1 + 84), fill=IVORY + (105,))
    draw.rectangle((x1 + 34, y1 + 102, x2 - 55, y1 + 110), fill=IVORY + (68,))


def node(image: Image.Image, center: tuple[int, int], radius: int, fill: tuple[int, int, int], ring: bool = True) -> None:
    x, y = center
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((x - radius - 18, y - radius - 18, x + radius + 18, y + radius + 18), fill=fill + (65,))
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(18)))
    draw = ImageDraw.Draw(image)
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill + (255,))
    if ring:
        draw.ellipse((x - radius + 8, y - radius + 8, x + radius - 8, y + radius - 8), outline=IVORY + (160,), width=3)


def connector(image: Image.Image, start: tuple[int, int], end: tuple[int, int], color: tuple[int, int, int] = AMBER, width: int = 8) -> None:
    draw = ImageDraw.Draw(image)
    draw.line((start, end), fill=color + (210,), width=width)
    ex, ey = end
    sx, sy = start
    dx, dy = ex - sx, ey - sy
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    tip = (ex, ey)
    left = (int(ex - ux * 24 + px * 13), int(ey - uy * 24 + py * 13))
    right = (int(ex - ux * 24 - px * 13), int(ey - uy * 24 - py * 13))
    draw.polygon((tip, left, right), fill=color + (230,))


def figure(image: Image.Image, x: int, y: int, scale: float, fill: tuple[int, int, int]) -> None:
    draw = ImageDraw.Draw(image)
    head = int(22 * scale)
    draw.ellipse((x - head, y - int(94 * scale), x + head, y - int(50 * scale)), fill=fill + (255,))
    draw.polygon(((x - int(42 * scale), y - int(48 * scale)), (x + int(42 * scale), y - int(48 * scale)), (x + int(58 * scale), y + int(62 * scale)), (x - int(58 * scale), y + int(62 * scale))), fill=fill + (255,))
    draw.polygon(((x - int(34 * scale), y + int(55 * scale)), (x - int(4 * scale), y + int(55 * scale)), (x - int(18 * scale), y + int(150 * scale)), (x - int(48 * scale), y + int(150 * scale))), fill=fill + (255,))
    draw.polygon(((x + int(4 * scale), y + int(55 * scale)), (x + int(34 * scale), y + int(55 * scale)), (x + int(48 * scale), y + int(150 * scale)), (x + int(18 * scale), y + int(150 * scale))), fill=fill + (255,))


def target_scene(image: Image.Image, scene: int) -> None:
    draw = ImageDraw.Draw(image)
    if scene == 1:
        for index, height in enumerate((210, 310, 410)):
            x = 840 + index * 150
            shadowed_polygon(image, [(x, 660), (x + 118, 625), (x + 118, 660 - height), (x, 695 - height)], (46 + index * 12, 58 + index * 10, 76 + index * 8))
        node(image, (1220, 170), 82, AMBER)
        figure(image, 630, 530, 1.15, IVORY)
    elif scene == 2:
        for index in range(3):
            card(image, (720 + index * 230, 180 + index * 72, 920 + index * 230, 490 + index * 72), (41 + index * 10, 56 + index * 8, 73 + index * 6), (AMBER, TEAL, COPPER)[index])
        figure(image, 520, 535, 1.05, IVORY)
    elif scene == 3:
        for index, value in enumerate((0.72, 0.48, 0.88)):
            x = 790 + index * 190
            draw.rectangle((x, 650 - int(380 * value), x + 105, 650), fill=(SLATE if index != 2 else AMBER) + (255,))
            draw.rectangle((x + 22, 650 - int(380 * value) + 30, x + 83, 640), fill=NAVY + (95,))
        connector(image, (720, 650), (1320, 240), TEAL, 7)
    elif scene == 4:
        node(image, (990, 420), 88, COPPER)
        for center in ((740, 230), (1190, 220), (760, 650), (1250, 640)):
            connector(image, center, (990, 420), AMBER, 6)
            node(image, center, 56, SLATE)
    elif scene == 5:
        for index in range(3):
            shadowed_polygon(image, [(720 + index * 125, 680 - index * 90), (1260 - index * 25, 680 - index * 90), (1190 - index * 20, 565 - index * 90), (760 + index * 115, 565 - index * 90)], (43 + index * 15, 57 + index * 12, 72 + index * 9))
        node(image, (1210, 260), 62, AMBER)
    elif scene == 6:
        for index in range(4):
            card(image, (650 + index * 190, 235, 810 + index * 190, 570), (39 + index * 7, 53 + index * 7, 69 + index * 6), (AMBER, TEAL, COPPER, AMBER)[index])
            if index < 3:
                connector(image, (810 + index * 190, 410), (650 + (index + 1) * 190, 410), IVORY, 5)
    elif scene == 7:
        for index, width in enumerate((520, 390, 270)):
            y = 650 - index * 145
            shadowed_polygon(image, [(760 + index * 55, y), (760 + index * 55 + width, y), (720 + index * 60 + width, y - 105), (800 + index * 50, y - 105)], (45 + index * 17, 59 + index * 13, 75 + index * 10))
        node(image, (1160, 205), 54, AMBER)
    else:
        for row in range(2):
            for col in range(3):
                center = (760 + col * 230, 280 + row * 250)
                node(image, center, 48, (AMBER, TEAL, COPPER)[col])
                if col < 2:
                    connector(image, center, (center[0] + 180, center[1]), IVORY, 5)


def forecast_scene(image: Image.Image, scene: int) -> None:
    draw = ImageDraw.Draw(image)
    if scene == 1:
        points = [(650, 540), (790, 445), (930, 465), (1080, 305), (1270, 265)]
        draw.line(points, fill=IVORY + (235,), width=12)
        draw.line(((650, 650), (830, 600), (980, 690), (1140, 585), (1320, 720)), fill=COPPER + (240,), width=10)
        for point in points:
            node(image, point, 18, AMBER, False)
    elif scene == 2:
        for index, box in enumerate(((760, 165, 1000, 405), (1050, 300, 1300, 560))):
            card(image, box, (50, 62, 79), COPPER)
            connector(image, ((box[0] + box[2]) // 2, box[3]), ((box[0] + box[2]) // 2, 700), COPPER, 9)
        figure(image, 625, 535, 1.05, IVORY)
    elif scene == 3:
        card(image, (770, 170, 1290, 620), (43, 57, 74), AMBER)
        for index in range(5):
            draw.arc((850 + index * 45, 260 + index * 26, 1200 - index * 30, 540 - index * 20), 200, 345, fill=(COPPER if index % 2 else TEAL) + (180,), width=8)
    elif scene == 4:
        for index in range(6):
            card(image, (690 + index * 72, 170 + index * 64, 1140 + index * 55, 395 + index * 64), (37 + index * 6, 50 + index * 6, 66 + index * 5), (AMBER if index == 5 else TEAL))
    elif scene == 5:
        lanes = [260, 425, 590]
        for lane in lanes:
            draw.line((680, lane, 1340, lane), fill=IVORY + (80,), width=5)
        for index in range(9):
            x = 750 + (index % 5) * 125
            y = lanes[(index * 2) % 3]
            node(image, (x, y), 35, (AMBER, TEAL, COPPER)[index % 3])
    elif scene == 6:
        figure(image, 620, 540, 1.15, IVORY)
        for center in ((820, 260), (1010, 390), (1210, 230), (1270, 570)):
            node(image, center, 50, COPPER)
            connector(image, center, (700, 500), AMBER, 5)
    elif scene == 7:
        for index, angle in enumerate((0, 120, 240)):
            center = ((900, 300), (1170, 360), (1010, 610))[index]
            node(image, center, 86, (AMBER, TEAL, COPPER)[index])
            draw.arc((center[0] - 120, center[1] - 120, center[0] + 120, center[1] + 120), angle, angle + 80, fill=IVORY + (180,), width=8)
    else:
        gates = (780, 1000, 1220)
        for index, x in enumerate(gates):
            shadowed_polygon(image, [(x, 210), (x + 125, 210), (x + 125, 660), (x, 660)], (46 + index * 10, 59 + index * 9, 75 + index * 7))
            draw.rectangle((x + 34, 300, x + 91, 570), fill=NAVY + (255,))
        connector(image, (670, 435), (1370, 435), AMBER, 12)


def account_scene(image: Image.Image, scene: int) -> None:
    draw = ImageDraw.Draw(image)
    if scene == 1:
        card(image, (810, 180, 1070, 610), (47, 60, 77), AMBER)
        card(image, (1040, 205, 1300, 635), (55, 65, 80), COPPER)
        figure(image, 650, 535, 1.05, IVORY)
    elif scene == 2:
        connector(image, (650, 300), (1270, 510), AMBER, 12)
        connector(image, (650, 590), (1270, 350), COPPER, 12)
        for center, color in (((650, 300), AMBER), ((650, 590), COPPER), ((1270, 430), IVORY)):
            node(image, center, 62, color)
    elif scene == 3:
        shadowed_polygon(image, [(920, 150), (1120, 150), (1260, 690), (780, 690)], (48, 61, 77))
        node(image, (1020, 430), 70, AMBER)
        connector(image, (680, 310), (940, 410), COPPER, 9)
        connector(image, (1360, 560), (1100, 455), TEAL, 9)
    elif scene == 4:
        connector(image, (690, 300), (1260, 300), COPPER, 12)
        connector(image, (690, 590), (1260, 590), COPPER, 12)
        draw.rectangle((950, 180, 1035, 700), fill=AMBER + (245,))
        draw.rectangle((970, 210, 1015, 670), fill=NAVY + (235,))
    elif scene == 5:
        centers = [(1010, 190), (830, 370), (1190, 370), (730, 620), (1010, 620), (1290, 620)]
        for index, center in enumerate(centers):
            node(image, center, 48 if index else 68, (AMBER if index == 0 else SLATE))
            if index:
                connector(image, centers[0], center, TEAL if index % 2 else COPPER, 5)
    elif scene == 6:
        nodes = ((770, 300, AMBER), (1020, 220, TEAL), (1260, 320, COPPER), (880, 610, COPPER), (1170, 610, AMBER))
        for x, y, color in nodes:
            node(image, (x, y), 55, color)
            connector(image, (x, y), (1020, 450), color, 5)
        node(image, (1020, 450), 82, IVORY)
    elif scene == 7:
        node(image, (1030, 420), 92, AMBER)
        for index, center in enumerate(((750, 210), (1290, 210), (750, 650), (1290, 650))):
            node(image, center, 55, (TEAL, COPPER, COPPER, TEAL)[index])
            connector(image, center, (1030, 420), IVORY, 6)
    else:
        for row in range(2):
            for col in range(2):
                card(image, (720 + col * 310, 170 + row * 270, 960 + col * 310, 390 + row * 270), (43 + row * 10, 57 + col * 8, 73), (AMBER, TEAL, COPPER, IVORY)[row * 2 + col])
        connector(image, (985, 430), (1015, 430), AMBER, 8)


def generate(project: Path) -> None:
    output = project / "images" / "management_cutout"
    output.mkdir(parents=True, exist_ok=True)
    name = project.name
    renderer = target_scene if "case02" in name else forecast_scene if "case03" in name else account_scene
    seed_base = sum((index + 1) * byte for index, byte in enumerate(name.encode("utf-8")))
    for scene in range(1, 9):
        image = paper_background(seed_base + scene * 97)
        renderer(image, scene)
        draw = ImageDraw.Draw(image)
        draw.line((92, 96, 520, 96), fill=AMBER + (170,), width=5)
        draw.line((92, 118, 390, 118), fill=IVORY + (70,), width=3)
        image.convert("RGB").save(output / f"{scene:02d}.png", quality=95)
    print(f"generated {name} count=8 out={output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--allow-programmatic-placeholders",
        action="store_true",
        help="Generate throwaway local placeholders. Forbidden for final case-video backgrounds.",
    )
    parser.add_argument("projects", nargs="+", type=Path)
    args = parser.parse_args()
    if not args.allow_programmatic_placeholders:
        raise SystemExit(
            "Programmatic management backgrounds are forbidden for final videos. "
            "Fix Azure image generation or use curated narrative illustrations. "
            "For disposable local placeholders only, pass --allow-programmatic-placeholders."
        )
    for project in args.projects:
        generate(project.resolve())


if __name__ == "__main__":
    main()
