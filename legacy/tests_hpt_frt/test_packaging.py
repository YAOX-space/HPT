"""test_packaging — the installed package imports with NO sys.path manipulation, and an env
reset/step works. Network modules (which load the OpenDSS backend) are imported in a SUBPROCESS so
the pytest process itself stays backend-free (clean exit, no 0xe0465043)."""
import subprocess
import sys


def _run(code):
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def test_principal_modules_import_without_path_injection():
    code = (
        "import hpt_frt\n"
        "from hpt_frt.common import pu, frt_v2, sequence\n"
        "from hpt_frt.network import config, sequence as nseq, opendss_runner, hpt_interface, "
        "scenarios, metrics, sac_wrapper\n"
        "from hpt_frt.device import frt_env, residual_env, frt_env_v2, frt_metrics, controller_registry\n"
        "assert config.DSS_FILE.exists(), 'packaged ieee33.dss missing'\n"
        "print('IMPORT_OK')\n")
    rc, out, err = _run(code)
    assert rc == 0 and 'IMPORT_OK' in out, err


def test_env_reset_step_via_package():
    code = (
        "import numpy as np\n"
        "from hpt_frt.device.frt_env_v2 import HPTFRTEnvV2, OBS_DIM_V2\n"
        "sc=dict(category='LVRT',fault_type='1ph_g',target_V_pu=0.5,scr=3.0,t_fault=0.05,"
        "fault_dur=0.3,T_sim=1.0)\n"
        "e=HPTFRTEnvV2([sc]); o,_=e.reset()\n"
        "assert OBS_DIM_V2==20 and o.shape==(20,) and e.action_space.shape==(3,)\n"
        "o2,r,d,tr,info=e.step([0.2,0.05,0.0]); assert o2.shape==(20,) and np.isfinite(r)\n"
        "print('ENV_OK')\n")
    rc, out, err = _run(code)
    assert rc == 0 and 'ENV_OK' in out, err


def test_dash_m_entrypoint_resolves():
    # a run script must be importable/executable as a package module (python -m ...) without flat dirs
    code = "import importlib; importlib.import_module('hpt_frt.network.run_exp_B_multi_hpt'); print('M_OK')"
    rc, out, err = _run(code)
    assert rc == 0 and 'M_OK' in out, err
