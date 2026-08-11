from sac.smoke_matlab_engine import SIMULINK_DIR, build_statement


def test_hpt_v2_smoke_runner_builds_interface_statement():
    statement = build_statement("interface")
    assert str(SIMULINK_DIR).replace("\\", "/") in statement
    assert "test_hpt_v2_sac_interface.m" in statement
    assert "simulink" in statement
