"""test_pu — base values, dq power formula, peak/RMS bases, no double-0.3, MATLAB/Python match."""
import math
import re
from pathlib import Path
from hpt_frt.common import pu

REPO = Path(__file__).resolve().parents[1]


def test_self_check_identities():
    for k, err in pu.self_check(verbose=False).items():
        assert err < 1e-6, f'{k} error {err}'


def test_iq03_is_pe_full_120kvar():
    assert abs(pu.iq_pu_to_kvar(0.3) - 120.0) < 1e-9      # iq=0.3 system-pu == PE full == 120 kVAr
    assert abs(pu.iq_pu_to_rms_amp(0.3) - pu.I_PE_RMS) < 1e-9    # == 173.2 A rms
    assert abs(pu.iq_pu_to_peak_amp(0.3) - pu.I_PE_PEAK) < 1e-9  # == 244.9 A peak


def test_pe_current_bases_and_no_peak_rms_mix():
    assert abs(pu.I_PE_RMS - 173.205) < 1e-2
    assert abs(pu.I_PE_PEAK - 244.949) < 1e-2
    assert abs(pu.I_PE_PEAK / pu.I_PE_RMS - math.sqrt(2)) < 1e-9
    # a measured PEAK current == PE peak reads 0.3 system-pu (correct); legacy /I_pe_rms reads 1.414
    assert abs(pu.peak_amp_to_pu(pu.I_PE_PEAK) - 0.3) < 1e-9
    assert abs(pu.I_PE_PEAK / pu.I_PE_RMS - math.sqrt(2)) < 1e-9


def _matlab_consts():
    """Parse lab/simulink/pu_params.m -> {name: float}. Evaluates the simple arithmetic assignments."""
    txt = (REPO / 'lab' / 'simulink' / 'pu_params.m').read_text(encoding='utf-8')
    env = {'sqrt': math.sqrt}
    out = {}
    for m in re.finditer(r'p\.(\w+)\s*=\s*([^;%]+);', txt):
        name, expr = m.group(1), m.group(2).strip()
        expr = re.sub(r'\bp\.(\w+)', r'out["\1"]', expr).replace('e3', 'e3')
        try:
            out[name] = eval(expr, {'sqrt': math.sqrt, 'out': out})
        except Exception:
            pass
    return out


def test_matlab_python_pu_constants_match():
    m = _matlab_consts()
    pairs = [('S_base_VA', pu.S_BASE_VA), ('VLL_base', pu.VLL_BASE), ('I_sys_rms', pu.I_SYS_RMS),
             ('I_sys_peak', pu.I_SYS_PEAK), ('S_pe_VA', pu.S_PE_VA), ('I_pe_rms', pu.I_PE_RMS),
             ('I_pe_peak', pu.I_PE_PEAK), ('iq_pe_limit_pu', pu.IQ_PE_LIMIT_PU),
             ('I_conv_max_pu', pu.I_CONV_MAX_PU), ('I_dq_base_peak', pu.I_SYS_PEAK)]
    for name, pyval in pairs:
        assert name in m, f'pu_params.m missing {name}'
        assert abs(m[name] - pyval) < 1e-6, f'{name}: MATLAB {m[name]} != Python {pyval}'
    # the 120 kVAr identity must hold from the MATLAB constants too
    assert abs(m['iq_pe_limit_pu'] * m['S_base_VA'] / 1e3 - 120.0) < 1e-6
