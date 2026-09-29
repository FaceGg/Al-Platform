from __future__ import annotations

import base64
import struct

import numpy as np

from app.services.waveform_samples import (
    WAVEFORM_BYTES,
    WAVEFORM_POINTS,
    decode_sample_waveforms,
    decode_waveform,
)


def _encoded(points: list[int]) -> str:
    padded = list(points) + [0] * (WAVEFORM_POINTS - len(points))
    return base64.b64encode(struct.pack(f">{WAVEFORM_POINTS}h", *padded)).decode("ascii")


def test_decode_waveform_converts_big_endian_int16_to_float64():
    # b"\x00\x01" reads as 1 in big-endian (little-endian would read 256)
    raw = b"\x00\x01" + b"\x00\x00" * (WAVEFORM_POINTS - 1)
    decoded = decode_waveform(base64.b64encode(raw).decode("ascii"))
    assert decoded is not None
    assert decoded.dtype == np.float64
    assert decoded.shape == (WAVEFORM_POINTS,)
    assert decoded[0] == 1.0
    assert decoded[-1] == 0.0


def test_decode_waveform_round_trips_negative_and_large_samples():
    decoded = decode_waveform(_encoded([-3, 8160]))
    assert decoded is not None
    assert decoded[0] == -3.0
    assert decoded[1] == 8160.0


def test_decode_waveform_rejects_invalid_payloads():
    assert decode_waveform(None) is None
    assert decode_waveform(42) is None
    assert decode_waveform("") is None
    assert decode_waveform("   ") is None
    assert decode_waveform("not base64!!!") is None
    assert decode_waveform(base64.b64encode(b"\x00" * (WAVEFORM_BYTES - 2)).decode()) is None
    assert decode_waveform(base64.b64encode(b"\x00" * (WAVEFORM_BYTES + 2)).decode()) is None


def test_decode_sample_waveforms_maps_fields_to_channels():
    values = {
        "cvei": _encoded([1]),
        "cvev": _encoded([2]),
        "cver": _encoded([3]),
        "cvep": _encoded([4]),
        "feature": 1,
    }
    waveforms = decode_sample_waveforms(values)
    assert set(waveforms) == {"current", "voltage", "resistance", "power"}
    assert waveforms["current"][0] == 1
    assert waveforms["voltage"][0] == 2
    assert waveforms["resistance"][0] == 3
    assert waveforms["power"][0] == 4


def test_decode_sample_waveforms_skips_missing_and_invalid_channels():
    waveforms = decode_sample_waveforms({"cvei": _encoded([5]), "cvev": "not base64!!!"})
    assert set(waveforms) == {"current"}
    assert waveforms["current"][0] == 5
    assert decode_sample_waveforms({"feature": 1}) == {}


def test_decode_sample_waveforms_serializes_int16_samples_as_integers():
    waveforms = decode_sample_waveforms({"cvei": _encoded([8160])})
    assert type(waveforms["current"][0]) is int
