import io

import pytest
from PIL import Image

import crosshair

SAMPLE = "CSYqwankGFrU2WEqDZA8pnnRjWpidUoFULhD9oqt8vmxYC"
# Example from akiver/csgo-sharecode's README.
LIBRARY_EXAMPLE = "CSvbPubOq37zTGqtsPTP5QTrp5CB4xFXiKRLfzJsm49ZRe"


def test_decode_sample():
    ch = crosshair.decode(SAMPLE)
    assert ch.style_name == "Static Cross"
    assert (ch.red, ch.green, ch.blue, ch.alpha) == (0, 235, 255, 255)
    assert (ch.length, ch.thickness, ch.gap) == (3, 2, 1)
    assert ch.outline_mode == 0
    assert not ch.center_dot and not ch.t_style
    assert ch.screen_height == 1440


def test_decode_library_example():
    ch = crosshair.decode(LIBRARY_EXAMPLE)
    assert (ch.style, ch.red, ch.length, ch.thickness, ch.screen_height) == (2, 255, 5, 1, 768)


@pytest.mark.parametrize(
    "code",
    [
        "CSGO-abcde-abcde-abcde-abcde-abcde",  # old format
        SAMPLE[:-1],  # too short
        SAMPLE[:-1] + ("A" if SAMPLE[-1] != "A" else "B"),  # checksum mismatch
    ],
)
def test_decode_rejects_invalid(code):
    with pytest.raises(crosshair.InvalidCrosshairCode):
        crosshair.decode(code)


def test_finds_code_in_message():
    assert crosshair.SHARE_CODE_RE.findall(f"my crosshair: {SAMPLE} thanks") == [SAMPLE]


@pytest.mark.parametrize("style", range(10))
def test_render_card_every_style(style):
    from dataclasses import replace

    ch = replace(crosshair.decode(SAMPLE), style=style, outline_mode=1, center_dot=True)
    img = Image.open(io.BytesIO(crosshair.render_card(ch)))
    assert img.format == "PNG"
    assert img.size == (744, 384)
