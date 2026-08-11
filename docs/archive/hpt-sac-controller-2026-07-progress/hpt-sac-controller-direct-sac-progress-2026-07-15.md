# HPT Direct SAC Progress Report - 2026-07-15

## 鏈疆宸插畬鎴?
1. 鏄庣‘鍖哄垎浜嗕袱鏉￠獙璇佽矾寰勶細
   - `hpt_sac_guard_enable = 1`: guarded smoke锛屽彧鑳戒綔涓?teacher / baseline銆?   - `hpt_sac_guard_enable = 0`: final raw actor path锛屾墠鏄渶缁?direct SAC 鍊欓€夈€?
2. 鏂板 raw switch-level 璇婃柇鑴氭湰锛?   - `simulink/evaluators/eval_hpt_v2_sac_raw_switchlevel_smoke.m`
   - 瑕嗙洊 topology1/topology2 鐨?steady 9000/10000/11000 V锛屼互鍙?sag 0.90 / swell 1.10 fault-transition銆?   - 璇ヨ剼鏈笉鍋氬己鍒?assert锛岃€屾槸杈撳嚭 pass/fail reason锛屼綔涓?final promotion gate 鐨勫墠缃瘖鏂€?
3. 鏂板 switch-level guarded teacher trace 閲囬泦鑴氭湰锛?   - `simulink/collectors/collect_hpt_v2_sac_guard_teacher_traces.m`
   - 杈撳嚭 `obs_01..obs_24 -> action_01..action_04` 鐨勭湡瀹?Simulink trace銆?   - 鏈疆閲囬泦鍒?1128 涓?2 ms 閲囨牱鐐癸細
     - topology1 steady: 108
     - topology1 fault: 456
     - topology2 steady: 108
     - topology2 fault: 456

4. 鎵╁睍浜?Python BC warm-start锛?   - 鏀寔 `--teacher-source execution_guard`銆?   - 鏀寔 `expanded_fault_transition` curriculum銆?   - 鏀寔 `--switch-trace-csv`锛屾妸 Simulink guarded trace 鐩存帴鍔犲叆璁粌闆嗐€?   - 鏀寔 topology2 phase-equivalent label锛屾妸 guarded hidden phase shift 杞垚 raw actor 鍙〃杈剧殑 `m_reg_d/m_reg_q`銆?   - 鏀寔 `--raw-smoke-correction-csv`锛屼粠 raw failed states 鐢熸垚 recovery correction samples銆?
5. 鍙戠幇骞朵慨姝ｄ簡涓€涓噸瑕佹暟鎹鍙栭棶棰橈細
   - Simulink `HPTSAC_obs` / `HPTSAC_action` 鏄?`24 x 1 x N` 鍜?`4 x 1 x N`銆?   - 鏂拌剼鏈幇鍦ㄤ細 `squeeze + reshape` 鎴?`nChannels x N`锛岄伩鍏嶈鎶婃椂闂撮暱搴︾湅鎴?1銆?
6. topology2 鎵撳紑浜?raw actor 鐨?q-axis 娉ㄥ叆閫氶亾锛?   - `hpt_sac_reg_q_gain = 1.0`
   - 鍘熷洜锛歵opology2 guarded dynamic path 涓湁闅愯棌鐩镐綅琛ュ伩 `inj_phase + 0.55`锛屾渶缁?`guard=0` 鏃跺彧鑳介€氳繃 `m_reg_q` 琛ㄨ揪绛夋晥鐩镐綅銆?
## 宸茶缁冪殑鍊欓€?actor

1. `hpt_voltage_sac_guard_teacher_expanded_bc_v0.zip`
   - curriculum: `expanded_fault_transition`
   - teacher: proxy execution-guard labels
   - samples: 40716
   - action MSE: `[3.97e-05, 7.82e-06, 7.45e-07, 1.47e-06]`

2. `hpt_voltage_sac_switch_trace_bc_v0.zip`
   - 鍔犲叆 Simulink guarded trace銆?   - samples: 112908
   - switch trace augmented samples: 72192
   - action MSE: `[1.10e-05, 2.17e-05, 5.97e-05, 6.99e-07]`

3. `hpt_voltage_sac_switch_trace_phase_bc_v0.zip`
   - 鍔犲叆 topology2 phase-equivalent labels銆?   - samples: 185100
   - switch trace augmented samples: 144384
   - action MSE: `[9.58e-06, 1.78e-05, 7.11e-05, 2.24e-07]`

4. `hpt_voltage_sac_switch_trace_energy_full_v0.zip`
   - energy action range 鎵╁ぇ鍒?`[-0.95, 0.95]`銆?   - 鍔犲叆 raw smoke correction samples銆?   - samples: 226060
   - switch trace augmented samples: 144384
   - raw smoke correction samples: 40960
   - action MSE: `[4.11e-05, 5.12e-06, 1.88e-05, 5.49e-06]`

## 褰撳墠鏈€濂界粨鏋?
### Guarded smoke

guarded smoke 浠嶇劧鑳借繃锛岃鏄庣墿鐞嗗紑鍏崇骇妯″瀷鍜屽熀鏈帶鍒堕€氶亾鏄彲杩愯鐨勶細

- `simulink/tests/test_hpt_v2_sac_switchlevel_voltage_regulation.m`
- `simulink/tests/test_hpt_v2_sac_fault_transition.m`

浣?guarded smoke 涓嶆槸鏈€缁堟垚鏋滐紝鍥犱负瀹冧粛鍏佽鎵ц灞傝鐩?actor 鍔ㄤ綔銆?
### Raw `guard=0`, regulating SAC only

褰?`hpt_sac_guard_enable = 0` 涓?energy converter 浠嶇敤浼犵粺 Vdc loop 鏃讹紝raw actor 鏈夐儴鍒嗘敼鍠勪絾娌℃湁閫氳繃锛?
- topology1 11000 V steady 涓€搴﹂€氳繃銆?- topology2 9000/10000 V steady 鏈夎繃閫氳繃鎴栨帴杩戦€氳繃銆?- topology2 fault-window 鐢靛帇鍙帴杩戠洰鏍囷紝浣?Vdc / recovery 浠嶅け璐ャ€?
缁撹锛歳egulating bridge 鐨?direct actor 鏈夎繘灞曪紝浣嗚繕娌℃湁 strong success銆?
### Raw `guard=0`, regulating + energy SAC

褰撴妸 `hpt_sac_energy_enable = 1` 涔熸墦寮€锛岀粨鏋滄槑鏄惧彉宸細

- topology1 steady LV RMS 闄嶅埌绾?153-197 V锛孷dc 澶ч噺浣庝簬绐楀彛銆?- topology2 steady / fault 涓?Vdc 鎺ヨ繎 0 鎴栦负璐熴€?
杩欒鏄庡綋鍓?`m_energy_d/m_energy_q -> physical TPFBVSC` 鐨?direct modulation 鎺ュ彛杩樻病鏈夋牎鍑嗗ソ锛屼笉鑳界洿鎺ヤ氦缁?SAC銆?
## 鍏抽敭澶辫触鍘熷洜

1. proxy 璁粌鍒嗗竷鍜?switch-level 瑙傛祴鍒嗗竷涓嶄竴鑷淬€?   - steady 鍦烘櫙涓?Simulink 鐨?`fault_active/recovery_active` 浼氳缃綅銆?   - `vdcpu` 鍒嗗竷鏄庢樉鍋忕 proxy 鍋囪銆?   - 鍙湪 proxy obs 涓婁綆 MSE锛屼笉浠ｈ〃 switch-level obs 涓婃纭€?
2. topology2 鍔ㄦ€佹帶鍒堕渶瑕佺浉浣嶈嚜鐢卞害銆?   - guarded path 闅愬惈 `inj_phase + 0.55`銆?   - final raw path 涓嶈兘鍐嶄娇鐢ㄨ繖涓?hidden rule銆?   - 蹇呴』鐢?actor 鐨?`m_reg_q` 鍐呭寲绛夋晥鐩镐綅銆?
3. 鍙栬兘妗?direct modulation 灏氭湭鏍″噯銆?   - 鍥哄畾 energy command sweep 鏄剧ず锛屽ぇ澶氭暟 `m_energy_d/q` 鍥哄畾鍊间細璁?Vdc 鎺ヨ繎 0銆?   - 杩欎笉鏄櫘閫?SAC 璁粌鑳界洿鎺ヨВ鍐崇殑闂锛屽繀椤诲厛寮勬竻 energy bridge 鐨勭墿鐞嗘帶鍒舵帴鍙ｃ€佺鍙峰拰浣庡眰闂幆缁撴瀯銆?
## 灏氭湭瀹屾垚

1. 杩樻病鏈変竴涓?`hpt_sac_guard_enable = 0` 鐨勭粺涓€ actor 閫氳繃 smoke gate銆?2. 杩樻病鏈夊畬鎴愮湡姝ｅ弻妗?direct SAC锛歳egulating bridge + energy bridge 閮界敱 SAC 绋冲畾鎺у埗銆?3. 杩樻病鏈夊畬鎴?expanded matrix锛?   - 0.2/0.5/0.75/0.85/0.9 pu LVRT
   - 1.1/1.2/1.25/1.3 pu HVRT
   - asymmetric faults
   - weak-grid cases
   - DC-link IC variation
4. 杩樻病鏈夎缁?TD3+BC / IQL / CQL offline baselines銆?5. 杩樻病鏈夎缁?SAC-MOPO / MOReL learned-proxy uncertainty 鐗堟湰銆?
## 涓嬩竴姝?
1. 鍏堟牎鍑?energy converter action interface銆?   - 鐩爣涓嶆槸缁х画鐩茶锛岃€屾槸纭畾 `m_energy_d/m_energy_q` 鐨勭墿鐞嗗惈涔夊拰绗﹀彿銆?   - 闇€瑕佹妸 conventional Vdc loop 鐨勬湁鏁堣緭鍑烘槧灏勬垚 actor 鍙涔犵殑鐩爣锛屾垨閲嶆柊瀹氫箟 energy action 涓烘洿鍚堢悊鐨勭數娴?鍔熺巼鍙傝€冦€?
2. 淇濈暀 regulating actor 鐨?switch-trace BC 璺嚎銆?   - 杩欐潯璺嚎宸茶瘉鏄庤兘鎶?guarded behavior 閮ㄥ垎鍐呭寲銆?   - topology2 鐨?q-axis phase-equivalent label 鏄繀瑕佺殑銆?
3. 鍦?energy interface 鏍″噯鍚庯紝鍐嶉噸鏂伴噰闆?switch-level teacher traces銆?   - 蹇呴』鍖呭惈 Vdc low / recovery states銆?   - 蹇呴』璁板綍 conventional energy loop 鐨勭洰鏍囧拰瀹為檯 bridge command銆?
4. 涔嬪悗鍐嶈缁?offline baseline銆?   - 浼樺厛 TD3+BC 鍜?IQL銆?   - CQL 浣滀负淇濆畧瀵圭収銆?
5. 浠讳綍鏈€缁堝€欓€夊繀椤婚€氳繃锛?   - `hpt_sac_guard_enable = 0`
   - no execution-layer overwrite
   - switch-level smoke gate
   - expanded validation matrix

