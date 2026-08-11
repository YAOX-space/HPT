import csv

import pytest

from sac.calibration.calibrate_hpt_frt_proxy_from_matrix import (
    CURRENT_FRT_VALIDATOR_SCHEMA,
    REQUIRED_ENVELOPE_COLUMNS,
    validate_envelope_columns,
)


def _write_matrix(path, schema: str) -> None:
    fields = sorted(REQUIRED_ENVELOPE_COLUMNS)
    row = {name: "0" for name in fields}
    row["validator_schema"] = schema
    row["pcc_assessment_signal"] = "pcc_phase_a_rms_pu"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)


def test_current_validator_matrix_is_accepted(tmp_path):
    path = tmp_path / "current.csv"
    _write_matrix(path, CURRENT_FRT_VALIDATOR_SCHEMA)
    validate_envelope_columns([path])


def test_stale_validator_matrix_is_rejected(tmp_path):
    path = tmp_path / "stale.csv"
    _write_matrix(path, "legacy-pre-gbt19963.1-v3")
    with pytest.raises(RuntimeError, match="stale FRT validator"):
        validate_envelope_columns([path])
