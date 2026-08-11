"""test_current_base — the current-base redesign (audit item 6): action scale, converter limit and
system-pu PE limit are THREE distinct bases, and the iq=0.3 -> 244.95 A -> 120 kVAr identity holds
with NO second 0.3 multiply."""
import math
import pytest
from hpt_frt.common import pu as PU


def test_three_distinct_bases():
    assert PU.I_ACTION_PEAK == PU.I_SYS_PEAK == pytest.approx(816.50, abs=0.1)     # action scale
    assert PU.I_CONVERTER_PEAK == PU.I_PE_PEAK == pytest.approx(244.95, abs=0.1)    # converter limit
    assert PU.S_PE_PU == pytest.approx(0.30, abs=1e-9)                              # system-pu PE limit
    assert PU.I_ACTION_PEAK != PU.I_CONVERTER_PEAK                                  # not conflated


def test_action_iq_03_maps_to_pe_peak_and_120_kvar():
    amp = PU.action_iq_to_command_amp(0.30)
    assert amp == pytest.approx(PU.I_PE_PEAK, abs=1e-6)            # 0.3 * I_sys_peak = I_pe_peak = 244.95
    # round trip action -> amp -> pu -> kVAr
    kvar = PU.iq_pu_to_kvar(PU.peak_amp_to_pu(amp))
    assert kvar == pytest.approx(120.0, abs=1e-6)


def test_no_double_0p3_multiply():
    # the action scale is I_sys_peak, NOT I_pe_peak; applying 0.3 to an already-PE-scaled current
    # would give 0.3*244.95 = 73.5 A (wrong). The correct command is 244.95 A.
    wrong_double = 0.30 * PU.I_PE_PEAK
    assert not math.isclose(PU.action_iq_to_command_amp(0.30), wrong_double)
    assert PU.action_iq_to_command_amp(0.30) == pytest.approx(244.95, abs=0.1)


def test_converter_clip_caps_combined_vector_at_pe_peak():
    # a large combined (id,iq) vector is clipped to the converter peak limit, direction preserved
    idc, iqc = PU.clip_converter_current(300.0, 300.0)
    assert math.hypot(idc, iqc) == pytest.approx(PU.I_CONVERTER_PEAK, abs=1e-6)
    assert idc == pytest.approx(iqc)                              # 45-degree direction preserved
    # a small vector passes unchanged (no spurious scaling)
    assert PU.clip_converter_current(100.0, 50.0) == (100.0, 50.0)


def test_self_check_round_trip_all_zero():
    errs = PU.self_check(verbose=False)
    for k in ('action_iq0.3_eq_I_pe_peak', 'action_iq0.3_roundtrip_kVAr',
              'converter_clip_caps_at_pe_peak', 'converter_clip_passes_small'):
        assert errs[k] < 1e-6, (k, errs[k])
