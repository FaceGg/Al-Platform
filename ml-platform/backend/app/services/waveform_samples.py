"""Waveform decoding for generic annotation data.

Manual annotation tasks may carry raw welding waveform columns (cvei/cvev/
cver/cvep) whose values are base64 strings. Each string decodes to 1740 bytes
of big-endian signed int16 samples (870 points per channel) and is served to
the annotator portal as a float64 series keyed by channel name
(current/voltage/resistance/power, matching the welding quality report
channel semantics).

Decoding is best-effort per channel: a payload that is missing, empty, or
malformed never fails the samples endpoint — the channel is simply omitted
from ``waveforms`` and the raw value keeps whatever handling it had before,
so samples without waveform data are returned unchanged.
"""

from __future__ import annotations

import base64
import binascii
from typing import Mapping

import numpy as np

WAVEFORM_FIELDS = ("cvei", "cvev", "cver", "cvep")
WAVEFORM_CHANNELS = {
    "cvei": "current",
    "cvev": "voltage",
    "cver": "resistance",
    "cvep": "power",
}
WAVEFORM_BYTES = 1740
WAVEFORM_POINTS = 870


def decode_waveform(encoded: object) -> np.ndarray | None:
    """Decode one base64 waveform string into 870 float64 samples.

    Returns None for anything that is not a valid 1740-byte base64 payload.
    """
    if not isinstance(encoded, str) or not encoded.strip():
        return None
    try:
        raw = base64.b64decode(encoded.strip(), validate=True)
    except (ValueError, TypeError, binascii.Error):
        return None
    if len(raw) != WAVEFORM_BYTES:
        return None
    values = np.frombuffer(raw, dtype=">i2").astype(np.float64)
    if values.shape != (WAVEFORM_POINTS,) or not np.isfinite(values).all():
        return None
    return values


def decode_sample_waveforms(values: Mapping[str, object]) -> dict[str, list[float]]:
    """Decode every valid waveform channel present in one sample's raw values."""
    waveforms: dict[str, list[float]] = {}
    for field in WAVEFORM_FIELDS:
        if field not in values:
            continue
        decoded = decode_waveform(values[field])
        if decoded is None:
            continue
        # int16-derived samples are integral; serialize without a redundant ".0"
        waveforms[WAVEFORM_CHANNELS[field]] = [
            int(point) if point.is_integer() else point for point in decoded.tolist()
        ]
    return waveforms
