import base64
import unittest

import numpy as np
import pandas as pd

from app.services.spot_weld_features import (
    WAVEFORM_FIELDS,
    QualityPipelineError,
    build_feature_frame,
    decode_waveform,
)


def waveform_payload(offset: int = 0) -> str:
    values = (np.arange(870, dtype=np.int32) + offset).astype(">i2")
    return base64.b64encode(values.tobytes()).decode("ascii")


def report_like_frame(rows: int = 2) -> pd.DataFrame:
    base = {
        "wld1c": 8.0,
        "wld2c": 10.0,
        "tipv1": 2.0,
        "tipv2": 2.5,
        "wres": 0.3,
        "energy": 100.0,
        "wld_spatter_strength": 1.0,
        "wld1_spatter_strength": 1.0,
        "wld2_spatter_strength": 0.5,
        "spatterpos_wld": 0.0,
        "spatterpos_pre": 0.0,
        "spotdiameter": 5.0,
        "spotposition": 1.0,
        "spattercode": 0.0,
        "cvei": waveform_payload(),
        "cvev": waveform_payload(1),
        "cver": waveform_payload(2),
        "cvep": waveform_payload(3),
    }
    return pd.DataFrame([{**base, "cvei": waveform_payload(index)} for index in range(rows)])


class TestSpotWeldFeatures(unittest.TestCase):
    def test_decode_report_waveform_uses_big_endian_int16(self):
        decoded = decode_waveform(waveform_payload(), field_name="cvei", row_index=0)
        self.assertEqual(decoded.shape, (870,))
        self.assertEqual(decoded[1], 1.0)

    def test_invalid_waveform_length_is_not_repaired(self):
        encoded = base64.b64encode(b"x" * 12).decode("ascii")
        with self.assertRaisesRegex(QualityPipelineError, "QUALITY_WAVEFORM_LENGTH_INVALID"):
            decode_waveform(encoded, field_name="cvei", row_index=7)

    def test_invalid_base64_is_rejected(self):
        with self.assertRaisesRegex(QualityPipelineError, "QUALITY_WAVEFORM_INVALID_BASE64"):
            decode_waveform("not-base64", field_name="cvei", row_index=2)

    def test_feature_schema_has_exactly_73_unique_names(self):
        frame, schema, statistics = build_feature_frame(report_like_frame())
        self.assertEqual(len(schema), 73)
        self.assertEqual(len(set(schema)), 73)
        self.assertEqual(list(frame.columns), schema)
        self.assertEqual(statistics["row_count"], 2)
        self.assertEqual(statistics["waveform_points"], 870)

    def test_mapping_can_read_report_columns_without_dropping_rows(self):
        frame = report_like_frame(1).rename(columns={"wld1c": "焊接电流1", "cvei": "电流波形"})
        mapping = {"wld1c": "焊接电流1", "cvei": "电流波形"}
        for name in WAVEFORM_FIELDS:
            mapping.setdefault(name, name)
        features, _, _ = build_feature_frame(frame, field_mapping=mapping)
        self.assertEqual(len(features), 1)
        self.assertAlmostEqual(float(features.iloc[0]["wld1c"]), 8.0)

    def test_nonfinite_numeric_input_fails_instead_of_imputation(self):
        frame = report_like_frame(1)
        frame.loc[0, "wld1c"] = 0.0
        with self.assertRaisesRegex(QualityPipelineError, "QUALITY_FEATURE_NONFINITE"):
            build_feature_frame(frame)


if __name__ == "__main__":
    unittest.main()
