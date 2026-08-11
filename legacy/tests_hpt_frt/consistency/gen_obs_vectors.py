"""gen_obs_vectors.py — Python->MAT->MATLAB consistency vectors (audit round-5 D). For each deployed
policy build >=20 de-privileged 20-D observations covering normal / deep+shallow LVRT / asym LVRT /
sym+asym HVRT / gate boundary (V2n~0.05) / voltage boundary (V1~0.9,1.1), run the SB3 actor, and save
obs + SB3 action. The MATLAB side (frt_v2_consistency_test.m) compares SB3 vs MAT-forward vs
frt_v2_hlc('actor') within 1e-8. Run AFTER the weights are exported:
    python -m tests.consistency.gen_obs_vectors
"""
import numpy as np
import scipy.io as sio
from pathlib import Path
from hpt_frt.device.model_io import load_sac
from hpt_frt.device.frt_env_v2 import OBS_DIM_V2, online_fault_class, is_fault_measured, ELAPSED_NORM

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / 'data' / 'models'
# (policy label -> model zip). Filled with the deployed checkpoints.
# residual -> EMA (that is what export_sac_actor.choose_residual exported to sac_residual_weights.mat)
POLICIES = {'single': 'sac_frt_best.zip', 'sym': 'sac_sym_best.zip', 'asym': 'sac_asym_best.zip',
            'hvrt_sym': 'sac_hvrt_sym_best.zip', 'hvrt_asym': 'sac_hvrt_asym_best.zip',
            'residual': 'sac_residual_ema_best.zip',
            # mi==17 (4-expert + residual hybrid): the gated-expert forwards are already covered above
            # (sym/asym/hvrt_*); only the residual net's forward needs locking. The mode-level
            # composition (gate + prior + residual + caps + wrong-sign clip) is verified by spotcheck.
            'resexpert': 'sac_resexpert_ema_best.zip'}

# (V1, V2n, label) operating points — covers the audit D.1 list
POINTS = [
    (1.00, 0.00, 'normal'), (0.95, 0.00, 'normal_near'),
    (0.20, 0.00, 'deep_sym'), (0.05, 0.00, 'superdeep_sym'), (0.75, 0.00, 'shallow_sym'),
    (0.50, 0.17, 'asym_1ph'), (0.45, 0.25, 'asym_2ph'), (0.60, 0.10, 'asym_2phg'),
    (1.25, 0.00, 'hvrt_sym'), (1.30, 0.00, 'hvrt_sym2'), (1.22, 0.12, 'hvrt_asym'),
    (0.901, 0.0, 'vbound_lo'), (1.099, 0.0, 'vbound_hi'),                 # V1 ~ 0.9 / 1.1
    (0.50, 0.0499, 'gate_lo'), (0.50, 0.0501, 'gate_hi'),                # V2n ~ 0.05 gate boundary
    (0.30, 0.05, 'deep_gate'), (0.85, 0.03, 'mild_asym'), (0.40, 0.30, 'strong_asym'),
    (1.35, 0.0, 'hvrt_high'), (0.10, 0.20, 'superdeep_asym'),
]


def obs_for(V1, V2n, *, Vdc=0.9, iq=0.0, tfrac=0.3, last=(0.0, 0.0, 0.0)):
    """Build the de-privileged 20-D observation EXACTLY as frt_env_v2.HPTFRTEnvV2._obs."""
    infault = is_fault_measured(V1, V2n)
    fc = online_fault_class(V1, V2n)
    probs = np.zeros(6, np.float32)
    if infault and fc != 0:
        probs[fc] = 0.92; probs[0] += 0.08
    else:
        probs[0] = 1.0
    iq_ref = (min(0.30, 1.5 * (0.9 - V1)) if V1 < 0.9 else (max(-0.30, -1.5 * (V1 - 1.1)) if V1 > 1.1 else 0.0))
    o = np.array([Vdc, V1, V2n, abs(iq), 0.0, 0.0, 0.9 - V1, iq_ref - iq, iq,
                  *probs, tfrac, float(infault), *last], np.float32)
    return np.clip(o, -5, 5).astype('float64')


def main():
    out_cases = []
    for label, fn in POLICIES.items():
        p = MODELS / fn
        if not p.exists():
            print('skip (absent):', fn); continue
        m = load_sac(p)
        assert m.observation_space.shape == (OBS_DIM_V2,) and m.action_space.shape == (3,), (label, m.observation_space.shape)
        obs = np.array([obs_for(V1, V2n) for V1, V2n, _ in POINTS], dtype='float64')
        act = np.array([m.predict(o, deterministic=True)[0] for o in obs], dtype='float64')
        out_cases.append(dict(policy=label, model=fn, obs=obs, sb3_act=act,
                              labels=np.array([lb for _, _, lb in POINTS], dtype=object)))
        print(f'{label:10s} {fn:26s} {len(obs)} obs -> SB3 act[0]={np.round(act[0],4)}')
    d = Path(__file__).resolve().parent / 'consistency_vectors.mat'
    sio.savemat(str(d), {'cases': np.array(out_cases, dtype=object)})
    print(f'wrote {len(out_cases)} policies x {len(POINTS)} obs -> {d}')


if __name__ == '__main__':
    main()
