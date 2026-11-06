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
Piece = tuple[Rect, float]  # rectangle and alpha multiplier

CROSS_STYLES = {0, 2, 4, 5}
QUAD_STYLES = {7, 8, 9}
CIRCLE_STYLES = {1, 3}
# Styles that spread when moving/shooting, and the static cross that kicks on each shot.
DYNAMIC_STYLES = {0, 1, 2, 7}
SHOT_FEEDBACK_STYLE = 5

FRAME_MS = 60


def is_animated(ch: Crosshair) -> bool:
    return ch.style in DYNAMIC_STYLES or ch.style == SHOT_FEEDBACK_STYLE


def _max_spread(ch: Crosshair) -> int:
    """How far (native px) the pieces travel at the peak of the animation."""
    if ch.style in DYNAMIC_STYLES:
        # Capped so a large spread limit does not shrink the crosshair to a speck in the preview.
        return max(2, min(ch.dynamic_spread_limit, ch.length * 2 + 6, 24))
    if ch.style == SHOT_FEEDBACK_STYLE:
        return max(2, min(ch.length // 2 + 1, 6))
    return 0


def _spread_timeline(ch: Crosshair) -> list[float]:
    """Spread per frame, 0 = at rest, 1 = full spread."""
    if ch.style == SHOT_FEEDBACK_STYLE:
        shot = [1.0, 0.5, 0.0, 0.0]
        return [0.0] * 6 + shot * 3 + [0.0] * 6
    expand = [1 - (1 - i / 5) ** 2 for i in range(1, 6)]  # ease out
    contract = [(1 - i / 10) ** 2 for i in range(1, 11)]  # ease in
    return [0.0] * 6 + expand + [1.0] * 8 + contract


def _native_size(ch: Crosshair) -> int:
    reach = abs(ch.gap) + ch.length + ch.thickness + _max_spread(ch) + 4
    return max(2 * reach + 9, 24)


def _pieces(ch: Crosshair, c: int, spread: int) -> list[Piece]:
    """Filled rectangles of the crosshair in native screen pixels, centred on pixel c."""
    t = max(ch.thickness, 1)
    # The centre block spans [lo, hi); arms start `gap` pixels outside it.
    lo = c - t // 2
    hi = lo + t
    g, L = ch.gap, ch.length
    pieces: list[Piece] = []

    def arms(start: int, n: int, alpha: float) -> None:
        pieces.append(((lo - start - n, lo, lo - start, hi), alpha))  # left
        pieces.append(((hi + start, lo, hi + start + n, hi), alpha))  # right
        pieces.append(((lo, hi + start, hi, hi + start + n), alpha))  # bottom
        if not ch.t_style:
            pieces.append(((lo, lo - start - n, hi, lo - start), alpha))  # top

    if ch.style in CROSS_STYLES and L > 0:
        if ch.style == 0 and spread:
            # Dynamic cross splits each arm: the inner part moves at most split_distance, the outer
            # part (split_size_ratio of the length) moves with the full spread. Both fade to their split alpha.
            outer_len = round(L * ch.split_size_ratio)
            inner_len = L - outer_len
            fade = min(1.0, spread / max(ch.split_distance, 1))
            if inner_len:
                arms(g + min(spread, ch.split_distance), inner_len, 1 + (ch.inner_split_alpha - 1) * fade)
            if outer_len:
                arms(g + inner_len + spread, outer_len, 1 + (ch.outer_split_alpha - 1) * fade)
        else:
            arms(g + spread, L, 1.0)
    elif ch.style in QUAD_STYLES and L > 0:  # quad / square: four corner brackets
        def bar(xa: int, xb: int, ya: int, yb: int) -> Rect:
            return (min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb))

        r = t // 2 + g + L + spread
        for sx in (-1, 1):
            for sy in (-1, 1):
                # Outer corner of the bracket; legs run inwards from it.
                x, y = c + (sx > 0) + sx * r, c + (sy > 0) + sy * r
                pieces.append((bar(x, x - sx * L, y, y - sy * t), 1.0))
                pieces.append((bar(x, x - sx * t, y, y - sy * L), 1.0))

    if ch.center_dot or ch.style == 6:
        pieces.append(((lo, lo, hi, hi), 1.0))
    return pieces


def _with_alpha(color: tuple[int, int, int, int], mult: float) -> tuple[int, int, int, int]:
    return (*color[:3], round(color[3] * max(0.0, min(mult, 1.0))))


def render(ch: Crosshair, scale: int = 8, spread: int = 0, size: int = 0) -> Image.Image:
    """Render the crosshair on a grey background, upscaled with nearest-neighbour so pixels stay crisp."""
    size = size or _native_size(ch)
    c = size // 2

    outline = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fill = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    od, fd = ImageDraw.Draw(outline), ImageDraw.Draw(fill)

    pieces = _pieces(ch, c, spread)
    circle = ch.style in CIRCLE_STYLES
    t = max(ch.thickness, 1)
    r = t // 2 + ch.gap + ch.length + spread

    if ch.outline_mode:
        # Full outline = 1px on every side; half outline = 1px on the right and bottom only.
        pad = (1, 1, 1, 1) if ch.outline_mode == 1 else (0, 0, 1, 1)
        for (x0, y0, x1, y1), a in pieces:
            od.rectangle((x0 - pad[0], y0 - pad[1], x1 - 1 + pad[2], y1 - 1 + pad[3]),
                         fill=_with_alpha(ch.outline_color, a))
        if circle:
            od.ellipse((c - r - 1, c - r - 1, c + r + 1, c + r + 1), outline=ch.outline_color, width=t + 2)

    for (x0, y0, x1, y1), a in pieces:
        fd.rectangle((x0, y0, x1 - 1, y1 - 1), fill=_with_alpha(ch.color, a))
    if circle:
        fd.ellipse((c - r, c - r, c + r, c + r), outline=ch.color, width=t)

    img = Image.alpha_composite(outline, fill)
    img = img.resize((size * scale, size * scale), Image.NEAREST)

    # Background: a neutral grey gradient so both dark and light crosshairs are visible.
    w = img.width
    back = Image.linear_gradient("L").resize((w, w)).point(lambda v: 60 + v * 70 // 255)
    back = Image.merge("RGBA", (back, back, back, Image.new("L", (w, w), 255)))
    return Image.alpha_composite(back, img)


def _panel(ch: Crosshair, preview_px: int, scale: int) -> Image.Image:
    panel_w = 360
    card = Image.new("RGBA", (preview_px + panel_w, preview_px), (24, 26, 30, 255))
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
    footer = f"Preview at {scale}x, 1 block = 1 px at {ch.screen_height}p"
    if is_animated(ch):
        footer += "\nAnimation approximates in-game movement"
    d.multiline_text((x, preview_px - 44), footer, font=ImageFont.load_default(size=12), fill=(120, 125, 135),
                     spacing=4)
    return card


def render_card(ch: Crosshair) -> tuple[bytes, str]:
    """Crosshair preview plus a settings panel. Returns (image bytes, "gif" or "png")."""
    preview_px = 384
    native = _native_size(ch)
    scale = max(1, preview_px // native)
    panel = _panel(ch, preview_px, scale)

    def frame(spread: int) -> Image.Image:
        preview = render(ch, scale=scale, spread=spread, size=native)
        if preview.width != preview_px:
            preview = preview.resize((preview_px, preview_px), Image.NEAREST)
        card = panel.copy()
        card.paste(preview, (0, 0))
        return card.convert("RGB")

    buf = io.BytesIO()
    if not is_animated(ch):
        frame(0).save(buf, "PNG")
        return buf.getvalue(), "png"

    peak = _max_spread(ch)
    cache: dict[int, Image.Image] = {}
    frames = []
    for f in _spread_timeline(ch):
        s = round(f * peak)
        if s not in cache:
            cache[s] = frame(s)
        frames.append(cache[s])
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=FRAME_MS, loop=0)
    return buf.getvalue(), "gif"
