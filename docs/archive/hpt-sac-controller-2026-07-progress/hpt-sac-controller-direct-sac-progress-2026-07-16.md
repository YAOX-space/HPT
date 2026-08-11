# HPT Direct SAC 杩涘睍鎶ュ憡 - 2026-07-16

## 鏈疆瀹屾垚鍐呭

1. 淇浜?SAC energy 鍔ㄤ綔鐨勭墿鐞嗘帴鍙ｃ€?   - 鏃ф帴鍙ｏ細`act[3:4] = m_energy_d/m_energy_q`锛岀洿鎺ヤ綔涓?TPFBVSC 涓夌浉 PWM 璋冨埗閲忋€?   - 鏂版帴鍙ｏ細`act[3:4] = i_energy_d_ref_pu/i_energy_q_ref_pu`锛屼綔涓哄綊涓€鍖?dq 鐢垫祦鍙傝€冦€?   - Simulink 涓敱 `HPTSACController` 鍐呴儴 dq 鐢垫祦鐜妸璇ュ弬鑰冮噺杞崲鎴愪笁鐩?TPFBVSC PWM 璋冨埗閲忋€?
2. 鏂板鍙栬兘妗?teacher trace 閲囬泦鑴氭湰銆?   - 鏂囦欢锛歚simulink/collectors/collect_hpt_v2_sac_energy_teacher_traces.m`
   - 鏁版嵁鏉ユ簮锛氬父瑙?`EnergyController` 鐨?Vdc 澶栫幆鍜?dq 鐢垫祦鐜€?   - quick trace 宸茶窇閫氾紝鐢熸垚 520 涓?switch-level teacher 鏍锋湰銆?   - 鏈€鏂?CSV锛歚lab/results/hpt_v2_sac_energy_teacher_traces/energy_teacher_traces_20260716_005433.csv`

3. 鎵╁睍 BC warm-start锛屼娇鍏跺彲浠ヨ鍙?energy teacher trace銆?   - 鏂囦欢锛歚sac/pretrain_hpt_actor_bc.py`
   - 鏂板弬鏁帮細
     - `--energy-teacher-trace-csv`
     - `--energy-teacher-trace-repeat`
   - trace 涓?`target_action_03 = id_ref / hpt_energy_id_max`锛宍target_action_04 = iq_ref / hpt_energy_id_max`銆?
4. 淇 raw smoke correction 鐨勮娴嬬獥鍙ｃ€?   - 鏃ч€昏緫浣跨敤 `obs_vpu_mean`锛屽湪 fault case 涓洿鍋忓悜灏炬/鎭㈠娈碉紝涓嶈兘浠ｈ〃澶辫触绐楀彛銆?   - 鏂伴€昏緫浣跨敤 `lv_mean / 207` 鍜?`vdc_min / 800` 鏋勯€?correction state锛屾洿璐磋繎 fault-window 澶辫触鍘熷洜銆?
5. 閲嶆柊鐢熸垚涓や釜 switch-level Simulink 妯″瀷銆?   - `simulink/topoloty1/hpt_v2_1to1_switchlevel.slx`
   - `simulink/topology2/hpt_v2_topology2_paper.slx`

## 鍏抽敭楠岃瘉缁撴灉

### Energy fixed-command sweep

鑴氭湰锛歚simulink/sweeps/sweep_hpt_v2_sac_energy_response.m`

鏈€鏂扮粨鏋滐細

- CSV锛歚lab/results/hpt_v2_sac_energy_sweep/hpt_v2_sac_energy_sweep_20260716_005721.csv`
- 鎵€鏈夊浐瀹?energy current-reference 鍛戒护涓嬶紝VdcMin 淇濇寔鍦ㄧ害 673 V 浠ヤ笂銆?- 涔嬪墠 raw modulation 鎺ュ彛浼氬鑷?Vdc 鎺ヨ繎 0 鎴栧彉鎴愯礋鍊硷紱鏈疆宸茬粡娑堥櫎杩欎釜涓昏宕╂簝妯″紡銆?
缁撹锛氭妸 energy action 鏀规垚 dq current reference 鏄纭柟鍚戙€?
### 鏂?SAC 鍊欓€夎缁?
璁粌浜?3 涓€欓€夛細

1. `hpt_voltage_sac_energy_trace_smoke.zip`
   - 鐢ㄤ簬楠岃瘉 energy trace 鏁版嵁绠＄嚎銆?   - 鏍锋湰鏁帮細840
   - energy teacher samples锛?20

2. `hpt_voltage_sac_currentref_bc_candidate.zip`
   - 鏍锋湰鏁帮細80,291
   - switch trace samples锛?6,096
   - energy teacher samples锛?6,640
   - action MSE锛歚[1.44e-3, 3.98e-4, 1.41e-2, 3.63e-4]`

3. `hpt_voltage_sac_currentref_bc_windowcorr_candidate.zip`
   - 褰撳墠瀵煎嚭鍒?Simulink 鐨勫€欓€夈€?   - 鏍锋湰鏁帮細121,251
   - switch trace samples锛?6,096
   - raw smoke correction samples锛?0,960
   - energy teacher samples锛?6,640
   - action MSE锛歚[3.78e-4, 1.00e-4, 2.87e-3, 3.05e-5]`

### 鏈€鏂?raw guard=0 switch-level smoke

鑴氭湰锛歚simulink/evaluators/eval_hpt_v2_sac_raw_switchlevel_smoke.m`

鏈€鏂扮粨鏋滐細

- CSV锛歚lab/results/hpt_v2_sac_raw_switchlevel_smoke/raw_sac_switchlevel_smoke_20260716_012512.csv`
- `hpt_sac_guard_enable = 0`
- 褰撳墠閫氳繃 3 / 10 涓?smoke cases锛?  - topology1 steady 10 kV
  - topology1 steady 11 kV
  - topology2 steady 10 kV
- 鏈€灏?Vdc锛氱害 559 V銆?
瀵规瘮鏈疆涔嬪墠锛?
- 涔嬪墠 raw energy modulation 浼氬嚭鐜?Vdc 鎺ヨ繎 0 鎴栬礋鍊笺€?- 褰撳墠宸茬粡娌℃湁绯荤粺鎬?DC-link 宕╂簝銆?- 澶辫触妯″紡涓昏鍙樻垚鐢靛帇璋冭妭骞呭€?鐩镐綅涓嶅锛屼互鍙?topology2 dynamic fault 涓?Vdc 鏀拺涓嶈冻銆?
## 杩樻病鏈夊畬鎴?
1. 杩樻病鏈変竴涓粺涓€ actor 閫氳繃鍏ㄩ儴 raw guard=0 smoke gate銆?2. topology1 鍦?9 kV steady 鍜?sag fault-window 涓粛鍋忎綆銆?3. topology2 鍦?9 kV/11 kV steady 涓粛涓嶇ǔ锛?1 kV case 杩樻湁 unbalance/Vdc 绐楀彛闂銆?4. topology2 dynamic sag/swell fault 浠嶆湭閫氳繃锛屽挨鍏?swell case 鐨?VdcMin 绾?559 V锛屼綆浜庣洰鏍囩獥鍙ｃ€?5. 杩樻病鏈夎繘鍏?expanded matrix 鏈€缁堥獙璇侊紱褰撳墠鍙畬鎴愪簡 smoke 灞傞潰鐨勮凯浠ｃ€?
## 涓嬩竴姝ュ缓璁?
1. 鍒嗙 steady actor 鍜?dynamic actor 鐨?teacher 鏉冮噸銆?   - 褰撳墠鍚屼竴涓?BC 璁粌闆嗛噷 steady銆乨ynamic銆乺aw correction 娣峰湪涓€璧凤紝topology2 11 kV steady 琚?fault correction 鎷夊亸銆?   - 寤鸿 dynamic actor 鍙敤浜?fault transition锛宻teady actor 浣跨敤鐙珛 steady trace/correction銆?
2. 瀵?topology2 dynamic 鍗曠嫭澧炲姞 switch-level trace銆?   - 褰撳墠 dynamic 澶辫触涓昏涓嶆槸 energy 鎺ュ彛锛岃€屾槸 series regulating bridge 鐩镐綅鍜屽箙鍊间笉澶熺ǔ銆?   - 闇€瑕侀噰闆嗘洿瀵嗙殑 topology2 sag/swell fault-window obs -> action 鏁版嵁銆?
3. 瀵?Vdc 鏀拺鍔犲叆涓撻棬鐨?topology2 HVRT teacher銆?   - 鏈€鏂?topology2 swell raw case锛歀V 杩樺彲鎺ヨ繎绐楀彛锛屼絾 Vdc 涓嬪啿鏄庢樉銆?   - energy current-ref 搴旇鍦?HVRT/fault edge 鏇寸Н鏋佸湴鏀拺 DC-link銆?
4. 鍦?smoke 閫氳繃涔嬪墠锛屼笉杩涘叆 8 灏忔椂 SAC/MOPO 闀胯銆?   - 褰撳墠鐡堕鏄?switch-level action semantics 鍜?data alignment銆?   - 闀胯鍓嶅繀椤诲厛璁?BC/teacher 鏁版嵁鍦?smoke gate 涓婃湁绋冲畾閫氳繃瓒嬪娍銆?
