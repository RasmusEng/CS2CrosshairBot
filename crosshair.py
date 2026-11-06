"""Decode CS2 crosshair share codes (the "CS" + 44 chars format) and render them to PNG.

Byte layout follows akiver/csgo-sharecode's cs2-v1 decoder:
https://github.com/akiver/csgo-sharecode
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

DICTIONARY = "ABCDEFGHJKLMNOPQRSTUVWXYZabcdefhijkmnopqrstuvwxyz23456789"
PREFIX = "CS"
CHAR_COUNT = 44
BYTE_LENGTH = 32

# Matches a share code anywhere in a message.
SHARE_CODE_RE = re.compile(rf"(?<![A-Za-z0-9]){PREFIX}[{DICTIONARY}]{{{CHAR_COUNT}}}(?![A-Za-z0-9])")

STYLE_NAMES = {
    0: "Dynamic Cross",
    1: "Dynamic Circle",
    2: "Dynamic Cross (Legacy)",
    3: "Static Circle",
    4: "Static Cross",
    5: "Static Cross (Shot Feedback)",
    6: "Dot Only",
    7: "Dynamic Quad",
    8: "Static Square",
    9: "Static Quad",
}
OUTLINE_NAMES = {0: "Off", 1: "Full", 2: "Half"}


class InvalidCrosshairCode(ValueError):
    pass


@dataclass
class Crosshair:
    code: str
    style: int
    follow_recoil: bool
    center_dot: bool
    t_style: bool
    outline_mode: int
    red: int
    green: int
    blue: int
    alpha: int
    outline_red: int
    outline_green: int
    outline_blue: int
    outline_alpha: int
    gap: int
    length: int
    thickness: int
    dynamic_spread_limit: int
    split_distance: int
    inner_split_alpha: float
    outer_split_alpha: float
    split_size_ratio: float
    screen_height: int
    scope_dot_scale: float
    scope_dot_use_crosshair_color: bool

    @property
    def style_name(self) -> str:
        return STYLE_NAMES.get(self.style, f"Unknown ({self.style})")

    @property
    def color(self) -> tuple[int, int, int, int]:
        return (self.red, self.green, self.blue, self.alpha)

    @property
    def outline_color(self) -> tuple[int, int, int, int]:
        return (self.outline_red, self.outline_green, self.outline_blue, self.outline_alpha)


def _code_to_bytes(code: str) -> list[int]:
    # Base 57, last character is the least significant digit.
    n = 0
    for ch in reversed(code[len(PREFIX):]):
        n = n * 57 + DICTIONARY.index(ch)
    if n.bit_length() > BYTE_LENGTH * 8:
        raise InvalidCrosshairCode("Code is out of range")
    return list(n.to_bytes(BYTE_LENGTH, "big"))


def decode(code: str) -> Crosshair:
    code = code.strip()
    if not SHARE_CODE_RE.fullmatch(code):
        raise InvalidCrosshairCode("Not a CS2 crosshair code (expected CS followed by 44 characters)")

    b = _code_to_bytes(code)
    if sum(b[1:]) % 256 != b[0]:
        raise InvalidCrosshairCode("Checksum mismatch")
    if b[1] != 1:
        raise InvalidCrosshairCode(f"Unsupported crosshair version {b[1]}")

    screen_height = b[2] | (b[3] << 8)
    if screen_height == 0:
        raise InvalidCrosshairCode("Screen height is 0")

    bits = b[18] | (b[19] << 8) | (b[20] << 16) | (b[21] << 24)
    gap = b[14] | (b[15] << 8)
    if gap >= 0x8000:
        gap -= 0x10000

    return Crosshair(
        code=code,
        style=min(b[4] & 0x1F, 9),
        follow_recoil=bool(b[4] & 0x20),
        center_dot=bool(b[4] & 0x40),
        t_style=bool(b[4] & 0x80),
        outline_mode=min(b[13] >> 6, 2),
        red=b[5],
        green=b[6],
        blue=b[7],
        alpha=b[8],
        outline_red=b[9],
        outline_green=b[10],
        outline_blue=b[11],
        outline_alpha=b[12],
        gap=max(-3840, min(gap, 3840)),
        length=b[16],
        thickness=min(b[13] & 0x3F, 32),
        dynamic_spread_limit=b[17],
        split_distance=bits & 0x7F,
        inner_split_alpha=min((bits >> 7) & 0x7F, 100) / 100,
        outer_split_alpha=(min((bits >> 14) & 0x7F, 70) + 30) / 100,
        split_size_ratio=min((bits >> 21) & 0x7F, 100) / 100,
        screen_height=max(screen_height, 240),
        scope_dot_scale=min((b[22] + 10) / 100, 2),
        scope_dot_use_crosshair_color=bool((bits >> 28) & 1),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

Rect = tuple[int, int, int, int]  # x0, y0, x1, y1 (exclusive end)


def _shapes(ch: Crosshair, c: int) -> list[Rect]:
    """Filled rectangles of the crosshair in native screen pixels, centred on pixel c."""
    t = max(ch.thickness, 1)
    # The centre block spans [lo, hi); arms start `gap` pixels outside it.
    lo = c - t // 2
    hi = lo + t
    g, L = ch.gap, ch.length
    rects: list[Rect] = []

    if ch.style in (0, 2, 4, 5) and L > 0:  # cross styles (dynamic ones drawn at rest)
        rects.append((lo - g - L, lo, lo - g, hi))  # left
        rects.append((hi + g, lo, hi + g + L, hi))  # right
        rects.append((lo, hi + g, hi, hi + g + L))  # bottom
        if not ch.t_style:
            rects.append((lo, lo - g - L, hi, lo - g))  # top
    elif ch.style in (7, 8, 9) and L > 0:  # quad / square: four corner brackets
        def bar(xa: int, xb: int, ya: int, yb: int) -> Rect:
            return (min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb))

        r = t // 2 + g + L
        for sx in (-1, 1):
            for sy in (-1, 1):
                # Outer corner of the bracket; legs run inwards from it.
                x, y = c + (sx > 0) + sx * r, c + (sy > 0) + sy * r
                rects.append(bar(x, x - sx * L, y, y - sy * t))
                rects.append(bar(x, x - sx * t, y, y - sy * L))

    if ch.center_dot or ch.style == 6:
        rects.append((lo, lo, hi, hi))
    return rects


def _circle_radius(ch: Crosshair) -> int:
    return max(ch.thickness, 1) // 2 + ch.gap + ch.length


def render(ch: Crosshair, scale: int = 8, tile: int = 0) -> Image.Image:
    """Render the crosshair on a dark background, upscaled with nearest-neighbour so pixels stay crisp."""
    reach = max(abs(ch.gap) + ch.length + ch.thickness + 4, 8)
    size = tile or (2 * reach + 9)
    size = max(size, 24)
    c = size // 2

    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    outline = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fill = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    od, fd = ImageDraw.Draw(outline), ImageDraw.Draw(fill)

    rects = _shapes(ch, c)
    circle = ch.style in (1, 3)

    if ch.outline_mode:
        # Full outline = 1px on every side; half outline = 1px on the right and bottom only.
        pad = (1, 1, 1, 1) if ch.outline_mode == 1 else (0, 0, 1, 1)
        for x0, y0, x1, y1 in rects:
            od.rectangle((x0 - pad[0], y0 - pad[1], x1 - 1 + pad[2], y1 - 1 + pad[3]), fill=ch.outline_color)
        if circle:
            r = _circle_radius(ch)
            od.ellipse((c - r - 1, c - r - 1, c + r + 1, c + r + 1), outline=ch.outline_color,
                       width=max(ch.thickness, 1) + 2)

    for x0, y0, x1, y1 in rects:
        fd.rectangle((x0, y0, x1 - 1, y1 - 1), fill=ch.color)
    if circle:
        r = _circle_radius(ch)
        fd.ellipse((c - r, c - r, c + r, c + r), outline=ch.color, width=max(ch.thickness, 1))

    img = Image.alpha_composite(bg, outline)
    img = Image.alpha_composite(img, fill)
    img = img.resize((size * scale, size * scale), Image.NEAREST)

    # Background: a neutral grey gradient so both dark and light crosshairs are visible.
    w = img.width
    back = Image.linear_gradient("L").resize((w, w)).point(lambda v: 60 + v * 70 // 255)
    back = Image.merge("RGBA", (back, back, back, Image.new("L", (w, w), 255)))
    return Image.alpha_composite(back, img)


def render_card(ch: Crosshair) -> bytes:
    """Crosshair preview plus a settings panel, as PNG bytes."""
    preview_px = 384
    reach = max(abs(ch.gap) + ch.length + ch.thickness + 4, 8)
    native = max(2 * reach + 9, 24)
    scale = max(1, preview_px // native)
    preview = render(ch, scale=scale)
    if preview.width != preview_px:
        preview = preview.resize((preview_px, preview_px), Image.NEAREST)

    panel_w = 360
    card = Image.new("RGBA", (preview_px + panel_w, preview_px), (24, 26, 30, 255))
    card.paste(preview, (0, 0))
    d = ImageDraw.Draw(card)
    title = ImageFont.load_default(size=22)
    body = ImageFont.load_default(size=16)

    x, y = preview_px + 20, 18
    d.text((x, y), "CS2 Crosshair", font=title, fill=(255, 255, 255))
    y += 38
    lines = [
        ("Style", ch.style_name),
        ("Color", f"rgb({ch.red}, {ch.green}, {ch.blue})  a={ch.alpha}"),
        ("Length", str(ch.length)),
        ("Thickness", str(ch.thickness)),
        ("Gap", str(ch.gap)),
        ("Outline", OUTLINE_NAMES[ch.outline_mode]
            + (f"  rgb({ch.outline_red}, {ch.outline_green}, {ch.outline_blue})" if ch.outline_mode else "")),
        ("Center dot", "On" if ch.center_dot else "Off"),
        ("T-style", "On" if ch.t_style else "Off"),
        ("Follow recoil", "On" if ch.follow_recoil else "Off"),
        ("Screen height", f"{ch.screen_height}p"),
    ]
    for k, v in lines:
        d.text((x, y), k, font=body, fill=(150, 155, 165))
        d.text((x + 130, y), v, font=body, fill=(235, 235, 235))
        y += 26
    # Colour swatch next to the title.
    d.rectangle((preview_px + panel_w - 50, 20, preview_px + panel_w - 22, 44),
                fill=(ch.red, ch.green, ch.blue, 255), outline=(255, 255, 255))
    d.text((x, preview_px - 30), f"Preview at {scale}x, 1 block = 1 px at {ch.screen_height}p",
           font=ImageFont.load_default(size=12), fill=(120, 125, 135))

    buf = io.BytesIO()
    card.convert("RGB").save(buf, "PNG")
    return buf.getvalue()
