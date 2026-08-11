"""ODE side of the head-to-head: fixed open-loop actions, record Vdc_min during fault.
Matched 1:1 with sim_compare.m (Simulink mode-10 fixed setpoints)."""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK','TRUE'); os.environ.setdefault('MKL_THREADING_LAYER','SEQUENTIAL')
import sys; from pathlib import Path
import numpy as np
from .frt_env import HPTFRTEnv, load_frt_scenarios

scn = load_frt_scenarios(Path(__file__).resolve().parents[3]/'lab'/'frt_scenarios.csv')
def pick(ft,tV,scr=3):
    return [s for s in scn if s['fault_type']==ft and abs(s['target_V_pu']-tV)<1e-6 and s['scr']==scr][0]

def vdcmin(s, act):
    env=HPTFRTEnv([s],seed=0); o,_=env.reset(); vs=[]
    for k in range(250):
        o,r,d,t,info=env.step(np.array(act,np.float32))
        tf=s['t_fault']; dur=s['fault_dur']*0.20
        if tf+0.02<=info['t']<tf+dur: vs.append(info['Vdc'])
        if d: break
    return (min(vs) if vs else float('nan'))

print("=== ODE: sym3ph, fixed [id=0, iq, mse=0] ===")
print(f"{'depth':>6} | {'iq=0.0':>7} {'iq=0.15':>8} {'iq=0.30':>8}")
for tV in [0.75,0.50,0.20]:
    s=pick('sym3ph',tV)
    row=[vdcmin(s,[0,iq,0,0]) for iq in (0.0,0.15,0.30)]
    print(f"{tV:6.2f} | {row[0]:7.3f} {row[1]:8.3f} {row[2]:8.3f}")
print("\n=== ODE: sym3ph 0.50, effect of series (iq=0.15) ===")
s=pick('sym3ph',0.50)
for ms in [0.0,0.10,0.20]:
    print(f"  series mse_d={ms:.2f} -> Vdc_min={vdcmin(s,[0,0.15,ms,0]):.3f}")
