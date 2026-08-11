"""test_sequence — PURE Fortescue math from hpt_frt.common.sequence (no OpenDSS in the test process)."""
import cmath
import math
import subprocess
import sys
from hpt_frt.common.sequence import symmetrical_components, seq_magnitudes


def test_balanced_is_pure_positive():
    a = cmath.exp(1j * 2 * math.pi / 3)
    V1, V2, V0 = symmetrical_components(1.0, a * a, a)
    assert abs(abs(V1) - 1.0) < 1e-9 and abs(V2) < 1e-9 and abs(V0) < 1e-9


def test_single_phase_drop_gives_negative_seq():
    a = cmath.exp(1j * 2 * math.pi / 3)
    Va, Vb, Vc = 0.0, a * a, a
    V1, V2, V0 = symmetrical_components(Va, Vb, Vc)
    assert abs(V1) < 1.0 and abs(V2) > 0.1
    assert abs((V0 + V1 + V2) - Va) < 1e-9                # Va reconstruction


def test_seq_magnitudes_matches():
    a = cmath.exp(1j * 2 * math.pi / 3)
    p, n, z = seq_magnitudes(1.0, a * a, a)
    assert abs(p - 1.0) < 1e-9 and n < 1e-9 and z < 1e-9


def test_pure_sequence_does_not_import_opendssdirect():
    """Importing the pure module must NOT pull the dss_python backend (the 0xe0465043 crash source)."""
    code = ("import sys; import hpt_frt.common.sequence as s; "
            "assert 'opendssdirect' not in sys.modules, 'pure sequence pulled opendssdirect'; "
            "print('clean')")
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert r.returncode == 0 and 'clean' in r.stdout, r.stderr
