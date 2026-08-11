% eval_hpt_v2_control_comparison
% Compare legacy conventional, tuned conventional dq/PI, and SAC raw guard=0
% on the same switch-level HPT plants and FRT scenarios.
%
% Workspace overrides:
%   hpt_compare_topology       "topology1" | "topology2" | "all"
%   hpt_compare_scenario_type  "steady" | "fault" | "all"
%   hpt_compare_case_name      e.g. "grid_10000V", "sag_0p90", "all"
%   hpt_compare_modes          string array, default primary comparison modes
%   hpt_compare_energy_enable  default 1.0 for SAC energy bridge
%   hpt_compare_model_params   optional struct of common model-workspace
%                               overrides applied to every evaluated mode
%   hpt_compare_conventional_profile "tuned_v2_l1" | "tuned_v1" | "model_default"
%   hpt_compare_conventional_params  optional struct of model-workspace overrides
%   hpt_compare_faults        optional cell array:
%                            {name, pu}, {name, pu, duration_s}, or
%                            {name, pu, duration_s, [puA puB puC]}.
%                            The 4th form enables an unbalanced controlled
%                            A/B/C source.  The older scalar forms preserve
%                            the original balanced programmable source path.
%   hpt_compare_fault_start   optional fault start time, default 0.035 s
%   hpt_compare_fault_stop_margin optional post-fault window after clear, default 0.125 s
%   hpt_compare_fault_settle_s optional voltage-envelope response window,
%                            default 0.0 s for strict assessment
%   hpt_compare_voltage_survival_current_gate optional boolean, default true.
%                            The L1 load-voltage-survival gate requires the
%                            grid-current limit. Setting this false is retained
%                            only for diagnostic migration runs. The gate uses
%                            the post-inception evaluation-window peak
%                            (grid_current_peak_pu), not the global waveform
%                            peak (grid_current_peak_global_pu), so startup
%                            and fault-inception spikes remain diagnostic.
%                            This staged switch is used by current-limit-aware
%                            SAC experiments without silently changing older
%                            voltage-only result semantics.
%   hpt_compare_actor_filter_tau optional SAC actor command filter tau, default 0.001 s
%   hpt_compare_fixed_action optional 1x4 fixed action for mode "fixed_action":
%                            [m_reg_d, m_reg_q, m_energy_d, m_energy_q]
%   hpt_compare_trajectory_file optional MAT file for mode "trajectory_action".
%                            The MAT file must contain:
%                            hpt_traj_t        Nx1 time vector, seconds
%                            hpt_traj_action   Nx4 action matrix
%   hpt_compare_output_dir   optional explicit result directory

clearvars -except hpt_compare_topology hpt_compare_scenario_type hpt_compare_case_name hpt_compare_modes hpt_compare_energy_enable hpt_compare_model_params hpt_compare_conventional_profile hpt_compare_conventional_params hpt_compare_faults hpt_compare_fault_start hpt_compare_fault_stop_margin hpt_compare_fault_settle_s hpt_compare_voltage_survival_current_gate hpt_compare_actor_filter_tau hpt_compare_run_label hpt_compare_fixed_action hpt_compare_trajectory_file hpt_compare_output_dir;
close all;

if ~exist('hpt_compare_topology', 'var')
    hpt_compare_topology = "all";
end
if ~exist('hpt_compare_scenario_type', 'var')
    hpt_compare_scenario_type = "all";
end
if ~exist('hpt_compare_case_name', 'var')
    hpt_compare_case_name = "all";
end
if ~exist('hpt_compare_modes', 'var')
    hpt_compare_modes = ["legacy_conventional", "conventional_dq", "sac_actor_raw_guard0"];
end
if ~exist('hpt_compare_energy_enable', 'var')
    hpt_compare_energy_enable = 1.0;
end
if ~exist('hpt_compare_model_params', 'var')
    hpt_compare_model_params = struct();
end
if ~exist('hpt_compare_conventional_profile', 'var')
    hpt_compare_conventional_profile = "tuned_v2_l1";
end
if ~exist('hpt_compare_conventional_params', 'var')
    hpt_compare_conventional_params = struct();
end
if ~exist('hpt_compare_fault_start', 'var')
    hpt_compare_fault_start = 0.035;
end
if ~exist('hpt_compare_fault_stop_margin', 'var')
    hpt_compare_fault_stop_margin = 0.125;
end
if ~exist('hpt_compare_fault_settle_s', 'var')
    hpt_compare_fault_settle_s = 0.0;
end
if ~exist('hpt_compare_voltage_survival_current_gate', 'var')
    hpt_compare_voltage_survival_current_gate = true;
end
if ~exist('hpt_compare_actor_filter_tau', 'var')
    hpt_compare_actor_filter_tau = 0.001;
end
if ~exist('hpt_compare_run_label', 'var')
    hpt_compare_run_label = "";
end
if ~exist('hpt_compare_fixed_action', 'var')
    hpt_compare_fixed_action = [0, 0, 0, 0];
end
if ~exist('hpt_compare_trajectory_file', 'var')
    hpt_compare_trajectory_file = "";
end
if ~exist('hpt_compare_output_dir', 'var')
    hpt_compare_output_dir = "";
end
hpt_compare_fixed_action = double(hpt_compare_fixed_action(:)');
assert(numel(hpt_compare_fixed_action) == 4, ...
    'hpt_compare_fixed_action must be [m_reg_d,m_reg_q,m_energy_d,m_energy_q]');
hpt_compare_trajectory_file = string(hpt_compare_trajectory_file);
if any(string(hpt_compare_modes) == "trajectory_action")
    assert(strlength(hpt_compare_trajectory_file) > 0, ...
        'hpt_compare_trajectory_file is required for trajectory_action mode');
    assert(exist(hpt_compare_trajectory_file, 'file') == 2, ...
        'Missing trajectory file: %s', hpt_compare_trajectory_file);
    trajCheck = load(hpt_compare_trajectory_file, 'hpt_traj_t', 'hpt_traj_action');
    assert(isfield(trajCheck, 'hpt_traj_t') && isfield(trajCheck, 'hpt_traj_action'), ...
        'Trajectory file must contain hpt_traj_t and hpt_traj_action');
    assert(size(trajCheck.hpt_traj_action, 2) == 4, ...
        'hpt_traj_action must be Nx4');
    assert(numel(trajCheck.hpt_traj_t) == size(trajCheck.hpt_traj_action, 1), ...
        'hpt_traj_t length must match hpt_traj_action rows');
end

hpt_compare_topology = string(hpt_compare_topology);
hpt_compare_scenario_type = string(hpt_compare_scenario_type);
hpt_compare_case_name = string(hpt_compare_case_name);
hpt_compare_modes = string(hpt_compare_modes);
hpt_compare_conventional_profile = string(hpt_compare_conventional_profile);

rootDir = fileparts(fileparts(mfilename('fullpath')));
evaluatorDir = fileparts(mfilename('fullpath'));
addpath(evaluatorDir);
validatorSchema = "hpt-frt-gates-v3-gbt19963.1";
actorFile = fullfile(rootDir, 'hpt_sac_actor_weights.mat');
dynamicActorFile = fullfile(rootDir, 'hpt_sac_actor_weights_dynamic.mat');
if any(hpt_compare_modes == "sac_actor_raw_guard0")
    assert(exist(actorFile, 'file') == 2, 'Missing HPT SAC actor: %s', actorFile);
    assert(exist(dynamicActorFile, 'file') == 2, ...
        'Missing dynamic HPT SAC actor: %s', dynamicActorFile);
    actor = load(actorFile, 'n_obs', 'n_act');
    assert(double(actor.n_obs) == 24 && double(actor.n_act) == 4, ...
        'HPT SAC actor must be 24/4, got %.0f/%.0f', double(actor.n_obs), double(actor.n_act));
end

cases = {
    fullfile(rootDir, 'topology1'), 'build_hpt_v2_1to1_switchlevel', 'hpt_v2_1to1_switchlevel', 'topology1', 'Zg', 200, 210, 6.0, 760, 920, 196, 214, 650, 235, 180;
    fullfile(rootDir, 'topology2'), 'build_hpt_v2_topology2_paper', 'hpt_v2_topology2_paper', 'topology2', 'Source_RL', 198, 212, 8.0, 760, 930, 194, 220, 620, 235, 180;
};

steadyGridVoltages = [9000, 10000, 11000];
faults = {
    'sag_0p20', 0.20;
    'sag_0p50', 0.50;
    'sag_0p75', 0.75;
    'sag_0p85', 0.85;
    'sag_0p90', 0.90;
    'swell_1p10', 1.10;
    'swell_1p20', 1.20;
    'swell_1p25', 1.25;
    'swell_1p30', 1.30;
};
if exist('hpt_compare_faults', 'var') && ~isempty(hpt_compare_faults)
    faults = hpt_compare_faults;
end
usePhaseFaultSource = faults_have_phase_vector(faults);

targetPhaseRms = 207.0;
nominalGridVoltage = 10000;
steadyStopTime = 0.08;
steadySettleStart = 0.05;
faultStart = hpt_compare_fault_start;
defaultFaultDuration = 0.060;
faultStopMargin = hpt_compare_fault_stop_margin;
Ts = 20e-6;

oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));
rowCells = {};

for c = 1:size(cases, 1)
    topology = string(cases{c, 4});
    if hpt_compare_topology ~= "all" && topology ~= hpt_compare_topology
        continue;
    end

    cd(cases{c, 1});
    M = cases{c, 3};
    sourceBranch = cases{c, 5};

    if hpt_compare_scenario_type == "all" || hpt_compare_scenario_type == "steady"
        stage_trajectory_file_if_needed(rootDir, cases{c, 1}, M);
        feval(cases{c, 2});
        if ~bdIsLoaded(M)
            load_system(M);
        end
        for k = 1:numel(steadyGridVoltages)
            caseName = string(sprintf("grid_%.0fV", steadyGridVoltages(k)));
            if hpt_compare_case_name ~= "all" && caseName ~= hpt_compare_case_name
                continue;
            end
            for m = 1:numel(hpt_compare_modes)
                mode = hpt_compare_modes(m);
                rowCells{end+1} = run_steady_case(M, topology, mode, ...
                    steadyGridVoltages(k), targetPhaseRms, steadyStopTime, ...
                    steadySettleStart, Ts, cases(c, :), hpt_compare_energy_enable, ...
                    hpt_compare_actor_filter_tau); %#ok<SAGROW>
            end
        end
    end
    if bdIsLoaded(M)
        set_param(M, 'Dirty', 'off');
        close_system(M, 0);
    end

    if hpt_compare_scenario_type == "all" || hpt_compare_scenario_type == "fault"
        stage_trajectory_file_if_needed(rootDir, cases{c, 1}, M);
        feval(cases{c, 2});
        M = cases{c, 3};
        stage_trajectory_file_if_needed(rootDir, cases{c, 1}, M);
        if ~bdIsLoaded(M)
            load_system(M);
        end
        if usePhaseFaultSource
            replace_grid_with_controlled_phase_source(M, sourceBranch, ...
                nominalGridVoltage, [1.0 1.0 1.0], faultStart, ...
                faultStart + defaultFaultDuration);
        else
            replace_grid_with_programmable_source(M, sourceBranch, nominalGridVoltage, ...
                1.0, faultStart, faultStart + defaultFaultDuration, ...
                faultStart + defaultFaultDuration + faultStopMargin);
        end

        for f = 1:size(faults, 1)
            faultName = string(faults{f, 1});
            if hpt_compare_case_name ~= "all" && faultName ~= hpt_compare_case_name
                continue;
            end
            faultPu = faults{f, 2};
            if size(faults, 2) >= 3 && ~isempty(faults{f, 3})
                faultDuration = faults{f, 3};
            else
                faultDuration = defaultFaultDuration;
            end
            faultPhasePu = fault_phase_pu(faults, f, faultPu);
            faultClear = faultStart + faultDuration;
            faultStopTime = faultClear + faultStopMargin;
            if usePhaseFaultSource
                configure_controlled_phase_grid(M, nominalGridVoltage, ...
                    faultPhasePu, faultStart, faultClear);
            else
                configure_programmable_grid(M, nominalGridVoltage, faultPu, ...
                    faultStart, faultClear, faultStopTime);
            end
            for m = 1:numel(hpt_compare_modes)
                mode = hpt_compare_modes(m);
                rowCells{end+1} = run_fault_case(M, topology, faultName, faultPu, ...
                    mode, targetPhaseRms, faultStopTime, Ts, faultStart, ...
                    faultClear, faultPhasePu, hpt_compare_energy_enable, ...
                    hpt_compare_actor_filter_tau); %#ok<SAGROW>
            end
        end
        if bdIsLoaded(M)
            set_param(M, 'Dirty', 'off');
            close_system(M, 0);
        end
    end
end

assert(~isempty(rowCells), 'No comparison cases matched topology=%s scenario=%s case=%s', ...
    hpt_compare_topology, hpt_compare_scenario_type, hpt_compare_case_name);

rows = [rowCells{:}];
if strlength(string(hpt_compare_output_dir)) > 0
    outDir = char(hpt_compare_output_dir);
else
    outDir = fullfile(rootDir, '..', 'results', 'control_comparison');
end
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
safeName = regexprep(sprintf('%s_%s_%s_%s', hpt_compare_topology, ...
    hpt_compare_scenario_type, hpt_compare_case_name, hpt_compare_run_label), ...
    '[^A-Za-z0-9_]+', '_');
outMat = fullfile(outDir, ['control_comparison_' char(safeName) '_' stamp '.mat']);
outCsv = fullfile(outDir, ['control_comparison_' char(safeName) '_' stamp '.csv']);
save(outMat, 'rows', 'targetPhaseRms', 'hpt_compare_topology', ...
    'hpt_compare_scenario_type', 'hpt_compare_case_name', 'hpt_compare_modes', ...
    'hpt_compare_model_params', 'hpt_compare_conventional_profile', ...
    'hpt_compare_conventional_params', ...
    'hpt_compare_voltage_survival_current_gate', ...
    'faults', 'hpt_compare_run_label', 'hpt_compare_fixed_action', ...
    'validatorSchema');
writetable(struct2table(rows), outCsv);

fprintf('HPT control comparison complete.\n');
fprintf('%-10s %-8s %-11s %-22s %8s %10s %10s %9s %9s %9s %-8s %s\n', ...
    'topology', 'type', 'case', 'mode', 'grid/pu', 'LV_mean', ...
    'LV_recov', 'VdcMin', 'max|a|', 'score', 'pass', 'reason');
for i = 1:numel(rows)
    if rows(i).scenario_type == "steady"
        caseValue = rows(i).grid_V;
    else
        caseValue = rows(i).fault_pu;
    end
    fprintf('%-10s %-8s %-11s %-22s %8.2f %10.3f %10.3f %9.3f %9.3f %9.3f %-8s %s\n', ...
        rows(i).topology, rows(i).scenario_type, rows(i).case_name, ...
        rows(i).mode, caseValue, rows(i).lv_mean, rows(i).lv_recovery_mean, ...
        rows(i).vdc_min, rows(i).action_max_abs, rows(i).control_score, ...
        string(rows(i).within_window), rows(i).window_reason);
end
fprintf('Saved CSV: %s\n', outCsv);

function [sacEnable, energyEnable, policyMode, actorSelectMode] = mode_settings(mode, scenarioType, energyEnableDefault)
    mode = string(mode);
    if mode == "legacy_conventional" || mode == "no_control"
        sacEnable = 0.0;
        energyEnable = 0.0;
        policyMode = 0.0;
        actorSelectMode = 0.0;
    elseif mode == "conventional_dq"
        sacEnable = 1.0;
        energyEnable = energyEnableDefault;
        policyMode = 0.0;
        actorSelectMode = 0.0;
    elseif mode == "rule_fallback"
        sacEnable = 1.0;
        energyEnable = energyEnableDefault;
        policyMode = 0.0;
        actorSelectMode = 0.0;
    elseif mode == "sac_actor_raw_guard0"
        sacEnable = 1.0;
        energyEnable = energyEnableDefault;
        policyMode = 1.0;
        if string(scenarioType) == "fault"
            actorSelectMode = 2.0;
        else
            actorSelectMode = 0.0;
        end
    elseif mode == "sac_actor_always_raw"
        sacEnable = 1.0;
        energyEnable = energyEnableDefault;
        policyMode = 1.0;
        actorSelectMode = 3.0;
    elseif mode == "sac_actor_depth_selector_raw"
        sacEnable = 1.0;
        energyEnable = energyEnableDefault;
        policyMode = 1.0;
        actorSelectMode = 4.0;
    elseif mode == "fixed_action"
        sacEnable = 1.0;
        energyEnable = energyEnableDefault;
        policyMode = -1.0;
        actorSelectMode = 0.0;
    elseif mode == "trajectory_action"
        sacEnable = 1.0;
        energyEnable = energyEnableDefault;
        policyMode = -2.0;
        actorSelectMode = 0.0;
    else
        error('Unknown comparison mode: %s', mode);
    end
end

function row = run_steady_case(M, topology, mode, gridVoltage, targetPhaseRms, ...
    stopTime, settleStart, Ts, caseSpec, energyEnableDefault, actorFilterTau)

    [sacEnable, energyEnable, policyMode, actorSelectMode] = mode_settings(mode, "steady", energyEnableDefault);
    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    in = in.setBlockParameter([M '/Grid'], 'Voltage', num2str(gridVoltage));
    in = set_common_variables(in, M, sacEnable, energyEnable, policyMode, ...
        actorSelectMode, targetPhaseRms, actorFilterTau);
    in = apply_conventional_profile(in, M, topology, mode);
    out = sim(in);

    Vlv = out.get('Vlv_abc');
    Vdc = out.get('Vdc');
    obs = out.get('HPTSAC_obs');
    act = out.get('HPTSAC_action');
    mref = out.get('Mref6_cmd');
    meng = out.get('Menergy_cmd');
    mregDbg = out.get('Mreg_cmd');
    energyDbg = out.get('Energy_dbg');
    Venergy = out.get('Energy_Vabc');
    if has_logged_var(out, 'Energy_Iabc')
        Ienergy = out.get('Energy_Iabc');
    else
        Ienergy = zeros(size(Vlv));
    end
    t = (0:size(Vlv, 1)-1)' * Ts;
    idx = t > settleStart;
    phaseRms = sqrt(mean(Vlv(idx, 1:3).^2, 1));
    obsRows = orient_channels(obs, 24);
    actRows = orient_channels(act, 4);
    mrefRows = orient_channels(mref, 6);
    mengRows = orient_channels(meng, 3);
    mregDbgRows = orient_channels(mregDbg, 7);
    energyDbgRows = orient_channels(energyDbg, 12);
    energyVRows = orient_channels(Venergy, 3);
    energyIRows = orient_channels(Ienergy, 3);
    energyIdMax = getVariable(get_param(M, 'ModelWorkspace'), 'hpt_energy_id_max');
    cmdActRows = actRows;
    measActRows = measured_response_rows(actRows, mrefRows, mregDbgRows, ...
        energyDbgRows, energyVRows, energyIRows, energyIdMax);

    row = base_row(M, topology, "steady", sprintf("grid_%.0fV", gridVoltage), ...
        mode, gridVoltage, NaN);
    row.hpt_sac_enable_cmd = sacEnable;
    row.hpt_sac_energy_enable_cmd = energyEnable;
    row.hpt_sac_policy_mode_cmd = policyMode;
    row.hpt_sac_actor_select_mode_cmd = actorSelectMode;
    row.lv_metric_source = "instant_three_phase_rms";
    row.lv_mean = mean(phaseRms);
    row.lv_a = phaseRms(1);
    row.lv_b = phaseRms(2);
    row.lv_c = phaseRms(3);
    row.lv_unbalance = max(phaseRms) - min(phaseRms);
    row.lv_recovery_mean = NaN;
    row.lv_peak = max(sqrt(mean(Vlv(:, 1:3).^2, 2)));
    row.lv_min = min(sqrt(mean(Vlv(:, 1:3).^2, 2)));
    row.vdc_mean = mean(Vdc(round(end*0.7):end, 1));
    row.vdc_min = min(Vdc(:, 1));
    row.vdc_max = max(Vdc(:, 1));
    row = add_action_semantics(row, cmdActRows, measActRows, mrefRows, mengRows);
    row.obs_vpu_mean = mean(obsRows(1, round(end*0.7):end));
    row.obs_vpos_mean = mean(obsRows(2, round(end*0.7):end));
    row.obs_vdcpu_mean = mean(obsRows(4, round(end*0.7):end));
    row.obs_verr_mean = mean(obsRows(6, round(end*0.7):end));
    row.obs_fault_flag_mean = mean(obsRows(17, round(end*0.7):end));
    row.obs_recovery_flag_mean = mean(obsRows(18, round(end*0.7):end));

    [row.within_window, row.window_reason] = assess_steady(row, caseSpec);
    row.l1_load_voltage_survival_pass = row.within_window;
    row.l1_reason = row.window_reason;
    row.l2_grid_code_ride_through_pass = false;
    row.l2_reason = "not_fault_scenario";
    row.l3_full_frt_pass = false;
    row.l3_reason = "not_fault_scenario";
    row.voltage_survival_pass = row.within_window;
    row.voltage_survival_reason = row.window_reason;
    row.full_frt_pass = row.within_window;
    row.full_frt_reason = row.window_reason;
    row.control_score = score_row(row);
end

function row = run_fault_case(M, topology, faultName, faultPu, mode, ...
    targetPhaseRms, stopTime, Ts, faultStart, faultClear, faultPhasePu, energyEnableDefault, ...
    actorFilterTau)

    [sacEnable, energyEnable, policyMode, actorSelectMode] = mode_settings(mode, "fault", energyEnableDefault);
    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    in = set_common_variables(in, M, sacEnable, energyEnable, policyMode, ...
        actorSelectMode, targetPhaseRms, actorFilterTau);
    in = apply_conventional_profile(in, M, topology, mode);
    out = sim(in);

    Vlv = out.get('Vlv_abc');
    Vdc = out.get('Vdc');
    if string(topology) == "topology1"
        Vgrid = out.get('Vmv_abc');
    else
        Vgrid = out.get('Vpri_abc');
    end
    if has_logged_var(out, 'Vgrid_cmd_abc')
        VsourceCmd = out.get('Vgrid_cmd_abc');
    else
        VsourceCmd = Vgrid;
    end
    Igrid = out.get('Igrid_abc');
    obs = out.get('HPTSAC_obs');
    act = out.get('HPTSAC_action');
    mref = out.get('Mref6_cmd');
    meng = out.get('Menergy_cmd');
    mregDbg = out.get('Mreg_cmd');
    energyDbg = out.get('Energy_dbg');
    Venergy = out.get('Energy_Vabc');
    if has_logged_var(out, 'Energy_Iabc')
        Ienergy = out.get('Energy_Iabc');
    else
        Ienergy = zeros(size(Vlv));
    end
    t = (0:size(Vlv, 1)-1)' * Ts;
    phaseRmsRaw = sqrt(mean(Vlv(:, 1:3).^2, 2));
    phaseRmsInst = phaseRmsRaw;
    faultDuration = faultClear - faultStart;
    faultEnterGuard = min(0.025, max(0.004, 0.20 * faultDuration));
    faultExitGuard = min(0.005, max(0.002, 0.10 * faultDuration));
    faultIdx = t > (faultStart + faultEnterGuard) & t < (faultClear - faultExitGuard);
    if ~any(faultIdx)
        faultIdx = t >= faultStart & t <= faultClear;
    end
    recoveryIdx = t > (faultClear + 0.035) & t < (stopTime - 0.005);
    obsRows = orient_channels(obs, 24);
    if is_unbalanced_fault(faultPhasePu, faultPu)
        nMetric = min(numel(phaseRmsInst), size(obsRows, 2));
        if nMetric >= 1
            phaseRmsInst(1:nMetric) = obsRows(1, 1:nMetric)' * targetPhaseRms;
        end
    end
    actRows = orient_channels(act, 4);
    gridVRows = orient_channels(Vgrid, 3);
    [sourceVRows, sourceT] = orient_logged_rows_with_time(VsourceCmd, 3, Ts);
    gridIRows = orient_channels(Igrid, 3);
    mrefRows = orient_channels(mref, 6);
    mengRows = orient_channels(meng, 3);
    mregDbgRows = orient_channels(mregDbg, 7);
    energyDbgRows = orient_channels(energyDbg, 12);
    energyVRows = orient_channels(Venergy, 3);
    energyIRows = orient_channels(Ienergy, 3);
    energyIdMax = getVariable(get_param(M, 'ModelWorkspace'), 'hpt_energy_id_max');
    cmdActRows = actRows;
    measActRows = measured_response_rows(actRows, mrefRows, mregDbgRows, ...
        energyDbgRows, energyVRows, energyIRows, energyIdMax);

    row = base_row(M, topology, "fault", faultName, mode, NaN, faultPu);
    row.hpt_sac_enable_cmd = sacEnable;
    row.hpt_sac_energy_enable_cmd = energyEnable;
    row.hpt_sac_policy_mode_cmd = policyMode;
    row.hpt_sac_actor_select_mode_cmd = actorSelectMode;
    row.fault_a_pu = faultPhasePu(1);
    row.fault_b_pu = faultPhasePu(2);
    row.fault_c_pu = faultPhasePu(3);
    row.fault_start_s = faultStart;
    row.fault_clear_s = faultClear;
    row.fault_duration_s = faultClear - faultStart;
    row.fault_settle_s = evalin('base', 'hpt_compare_fault_settle_s');
    row.stop_time_s = stopTime;
    row.lv_mean = mean(phaseRmsInst(faultIdx));
    if is_unbalanced_fault(faultPhasePu, faultPu)
        row.lv_metric_source = "controller_filtered_lv_pu";
    else
        row.lv_metric_source = "instant_three_phase_rms";
    end
    row.lv_a = NaN;
    row.lv_b = NaN;
    row.lv_c = NaN;
    row.lv_unbalance = NaN;
    row.lv_recovery_mean = mean(phaseRmsInst(recoveryIdx));
    row.lv_peak = max(phaseRmsInst(t > faultStart & t < stopTime));
    row.lv_min = min(phaseRmsInst(t > faultStart & t < stopTime));
    baseGridPhaseRms = 10000.0 / sqrt(3);
    gridPreIdx = t >= max(0.020, faultStart - 0.060) & t <= (faultStart - 0.020);
    obsPreIdx = t >= max(0.035, faultStart - 0.030) & t < (faultStart - 0.006);
    gridFaultIdx = t >= (faultStart + row.fault_settle_s) & t <= faultClear;
    gridRecoveryIdx = t >= (faultClear + max(0.020, row.fault_settle_s)) & ...
        t <= (stopTime - 0.005);
    sourcePreIdx = sourceT >= max(0.020, faultStart - 0.060) & ...
        sourceT <= (faultStart - 0.020);
    sourceFaultIdx = sourceT >= (faultStart + row.fault_settle_s) & ...
        sourceT <= faultClear;
    sourceRecoveryIdx = sourceT >= (faultClear + max(0.020, row.fault_settle_s)) & ...
        sourceT <= (stopTime - 0.005);
    row = add_grid_window_metrics(row, "pre", gridVRows, t, gridPreIdx, baseGridPhaseRms);
    row = add_grid_window_metrics(row, "fault", gridVRows, t, gridFaultIdx, baseGridPhaseRms);
    row = add_grid_window_metrics(row, "recovery", gridVRows, t, gridRecoveryIdx, baseGridPhaseRms);
    row = add_source_window_metrics(row, "pre", sourceVRows, sourceT, sourcePreIdx, baseGridPhaseRms);
    row = add_source_window_metrics(row, "fault", sourceVRows, sourceT, sourceFaultIdx, baseGridPhaseRms);
    row = add_source_window_metrics(row, "recovery", sourceVRows, sourceT, sourceRecoveryIdx, baseGridPhaseRms);
    row.vdc_mean = mean(Vdc(round(end*0.7):end, 1));
    row.vdc_min = min(Vdc(:, 1));
    row.vdc_max = max(Vdc(:, 1));
    row = add_action_semantics(row, cmdActRows, measActRows, mrefRows, mengRows);
    row = add_action_window_metrics(row, "fault", cmdActRows, measActRows, gridFaultIdx);
    row = add_action_window_metrics(row, "recovery", cmdActRows, measActRows, gridRecoveryIdx);
    row.obs_vpu_mean = mean(obsRows(1, round(end*0.7):end));
    row.obs_vpos_mean = mean(obsRows(2, round(end*0.7):end));
    row.obs_vdcpu_mean = mean(obsRows(4, round(end*0.7):end));
    row.obs_verr_mean = mean(obsRows(6, round(end*0.7):end));
    row.obs_fault_flag_mean = mean(obsRows(17, round(end*0.7):end));
    row.obs_recovery_flag_mean = mean(obsRows(18, round(end*0.7):end));
    row = add_obs_window_metrics(row, "pre", obsRows, obsPreIdx);
    row = add_obs_window_metrics(row, "fault", obsRows, gridFaultIdx);
    row = add_obs_window_metrics(row, "recovery", obsRows, gridRecoveryIdx);
    row = add_fault_gate_metrics(row, phaseRmsInst, Vdc(:, 1), actRows, ...
        gridVRows, gridIRows, t, targetPhaseRms, faultPu, faultStart, ...
        faultClear, stopTime, row.fault_settle_s, faultPhasePu);
    row.voltage_survival_current_gate = logical(evalin('base', ...
        'hpt_compare_voltage_survival_current_gate'));
    row.simulation_completed = t(end) >= stopTime - 1.5 * Ts && ...
        all(isfinite(Vlv(:))) && all(isfinite(Vdc(:))) && ...
        all(isfinite(Igrid(:)));
    % No explicit breaker/trip-state output exists in the current plant.
    % Simulation continuity is recorded separately and is not treated as a
    % formal remained-connected verdict.
    row.remained_connected_evaluated = false;
    row.remained_connected = false;
    row.remained_connected_evidence = ...
        "continuous_switch_level_run_no_explicit_trip_interface";
    row.equipment_safety_pass = row.vdc_min >= 650.0 && ...
        row.vdc_max <= 1000.0 && row.action_max_abs <= 0.9501 && ...
        row.gbt_grid_current_limit_pass;

    [row.l1_load_voltage_survival_pass, row.l1_reason] = ...
        assess_fault_load_voltage_survival(row);
    [row.l2_grid_code_ride_through_pass, row.l2_reason] = ...
        assess_fault_grid_code_ride_through(row);
    [row.l3_full_frt_pass, row.l3_reason] = assess_fault_full_frt(row);
    row.voltage_survival_pass = row.l1_load_voltage_survival_pass;
    row.voltage_survival_reason = row.l1_reason;
    row.full_frt_pass = row.l3_full_frt_pass;
    row.full_frt_reason = row.l3_reason;
    row.within_window = row.l1_load_voltage_survival_pass;
    row.window_reason = row.l1_reason;
    row.control_score = score_row(row);
end

function in = apply_conventional_profile(in, M, topology, mode)
    mode = string(mode);
    if mode ~= "conventional_dq"
        return;
    end

    profile = evalin('base', 'hpt_compare_conventional_profile');
    overrides = evalin('base', 'hpt_compare_conventional_params');
    profile = string(profile);
    topology = string(topology);

    if profile == "tuned_v2_l1" || profile == "tuned_v1"
        if topology == "topology1"
            in = in.setVariable('hpt_vreg_kp', 4.0, 'Workspace', M);
            in = in.setVariable('hpt_vreg_ki', 1.0, 'Workspace', M);
            in = in.setVariable('hpt_m_reg_max', 0.65, 'Workspace', M);
            in = in.setVariable('hpt_sac_reg_q_gain', 1.0, 'Workspace', M);
            in = in.setVariable('hpt_inj_phase_offset', -1.05, 'Workspace', M);
            in = in.setVariable('hpt_swell_gain_scale', 0.65, 'Workspace', M);
            in = in.setVariable('hpt_vdc_kp', 0.16, 'Workspace', M);
            in = in.setVariable('hpt_vdc_ki', 0.30, 'Workspace', M);
            in = in.setVariable('hpt_energy_i_kp', 0.65, 'Workspace', M);
            in = in.setVariable('hpt_energy_i_ki', 90.0, 'Workspace', M);
            in = in.setVariable('hpt_conventional_recovery_reg_gain', 4.0, ...
                'Workspace', M);
            in = in.setVariable('hpt_conventional_recovery_reg_max', 0.65, ...
                'Workspace', M);
        else
            % Topology2's physical EnergyController outer DC loop currently
            % has the wrong sign around the parallel-coupled energy port.
            % Use the HPTSACController policy_mode=0 rule/dq current loop as
            % the strong traditional baseline, keeping its calibrated default
            % current-loop and injection parameters.
            % v3 L1 fixed-plant profile.  This parameter set was selected
            % from the 2026-08-03 switch-level campaign without changing the
            % topology2 chopper resistance or threshold.  It passes the
            % 0.90-pu/60-ms LVRT smoke and intentionally retains the
            % 1.10-pu/60-ms Vdc-limit failure as a measured baseline boundary.
            in = in.setVariable('hpt_vreg_kp', 5.6, 'Workspace', M);
            in = in.setVariable('hpt_vreg_ki', 0.35, 'Workspace', M);
            in = in.setVariable('hpt_m_reg_max', 0.60, 'Workspace', M);
            in = in.setVariable('hpt_sac_reg_max', 0.60, 'Workspace', M);
            in = in.setVariable('hpt_sac_reg_q_gain', -1.0, 'Workspace', M);
            in = in.setVariable('hpt_inj_phase_offset', -1.05, 'Workspace', M);
            in = in.setVariable('hpt_vdc_kp', 0.05, 'Workspace', M);
            in = in.setVariable('hpt_vdc_ki', 0.02, 'Workspace', M);
            in = in.setVariable('hpt_energy_i_kp', 0.20, 'Workspace', M);
            in = in.setVariable('hpt_energy_i_ki', 35.0, 'Workspace', M);
            in = in.setVariable('hpt_energy_vff_gain', 0.0, 'Workspace', M);
            in = in.setVariable('hpt_energy_control_sign', -1.0, 'Workspace', M);
            in = in.setVariable('hpt_energy_bridge_polarity', -1.0, 'Workspace', M);
            in = in.setVariable('hpt_conventional_energy_scale', 0.15, ...
                'Workspace', M);
            in = in.setVariable('hpt_conventional_recovery_reg_gain', 2.4, ...
                'Workspace', M);
            in = in.setVariable('hpt_conventional_recovery_reg_max', 0.44, ...
                'Workspace', M);
        end
    elseif profile ~= "model_default"
        error('Unknown conventional profile: %s', profile);
    end

    names = fieldnames(overrides);
    for k = 1:numel(names)
        in = in.setVariable(names{k}, overrides.(names{k}), 'Workspace', M);
    end
end

function v = actual_action_max(mrefRows, mengRows)
    v = max([abs(mrefRows(:)); abs(mengRows(:))]);
end

function actRows = measured_response_rows(hptActRows, mrefRows, mregDbgRows, ...
    energyDbgRows, energyVRows, energyIRows, energyIdMax)
    hasEnergyVI = size(energyVRows, 1) >= 3 && size(energyIRows, 1) >= 3 && ...
        size(energyVRows, 2) >= 1 && size(energyIRows, 2) >= 1;
    n = size(hptActRows, 2);
    if isempty(n) || n < 1
        actRows = hptActRows;
        return;
    end
    actRows = zeros(4, n);
    for k = 1:n
        if k <= size(mrefRows, 2) && k <= size(mregDbgRows, 2) && size(mregDbgRows, 1) >= 7
            theta = mregDbgRows(1, k);
            phi = mregDbgRows(7, k);
            [actRows(1, k), actRows(2, k)] = reg6_to_dq(mrefRows(:, k), theta + phi);
        else
            actRows(1, k) = hptActRows(1, k);
            actRows(2, k) = hptActRows(2, k);
        end
        if hasEnergyVI && k <= size(energyVRows, 2) && k <= size(energyIRows, 2)
            va = energyVRows(1, k);
            vb = energyVRows(2, k);
            vc = energyVRows(3, k);
            ia = energyIRows(1, k);
            ib = energyIRows(2, k);
            ic = energyIRows(3, k);
            valpha = (2/3) * (va - 0.5*vb - 0.5*vc);
            vbeta = (sqrt(3)/3) * (vb - vc);
            ialpha = (2/3) * (ia - 0.5*ib - 0.5*ic);
            ibeta = (sqrt(3)/3) * (ib - ic);
            theta = atan2(vbeta, valpha);
            actRows(3, k) = clip_scalar((ialpha*cos(theta) + ibeta*sin(theta)) / max(energyIdMax, 1e-9), -0.95, 0.95);
            actRows(4, k) = clip_scalar((-ialpha*sin(theta) + ibeta*cos(theta)) / max(energyIdMax, 1e-9), -0.95, 0.95);
        elseif size(energyDbgRows, 1) >= 5 && k <= size(energyDbgRows, 2)
            actRows(3, k) = clip_scalar(energyDbgRows(4, k) / max(energyIdMax, 1e-9), -0.95, 0.95);
            actRows(4, k) = clip_scalar(energyDbgRows(5, k) / max(energyIdMax, 1e-9), -0.95, 0.95);
        else
            actRows(3, k) = hptActRows(3, k);
            actRows(4, k) = hptActRows(4, k);
        end
    end
end

function row = add_action_semantics(row, cmdRows, measRows, mrefRows, mengRows)
    row.cmd_action_max_abs = matrix_max_abs(cmdRows);
    row.bridge_modulation_abs_max = actual_action_max(mrefRows, mengRows);
    row.action_max_abs = row.bridge_modulation_abs_max;

    row.cmd_m_reg_d_mean = tail_row_mean(cmdRows, 1);
    row.cmd_m_reg_q_mean = tail_row_mean(cmdRows, 2);
    row.cmd_m_energy_d_mean = tail_row_mean(cmdRows, 3);
    row.cmd_m_energy_q_mean = tail_row_mean(cmdRows, 4);

    row.meas_reg_d_mean = tail_row_mean(measRows, 1);
    row.meas_reg_q_mean = tail_row_mean(measRows, 2);
    row.meas_energy_d_mean = tail_row_mean(measRows, 3);
    row.meas_energy_q_mean = tail_row_mean(measRows, 4);

    % Backward-compatible fields now mean effective switch-level response.
    row.reg_d_mean = row.meas_reg_d_mean;
    row.reg_q_mean = row.meas_reg_q_mean;
    row.energy_d_mean = row.meas_energy_d_mean;
    row.energy_q_mean = row.meas_energy_q_mean;
end

function row = add_action_window_metrics(row, label, cmdRows, measRows, idx)
    prefix = char(label);
    row.(sprintf('action_%s_sample_count', prefix)) = window_sample_count(cmdRows, idx);
    row.(sprintf('action_%s_cmd_cols', prefix)) = size(cmdRows, 2);
    row.(sprintf('cmd_m_reg_d_%s_mean', prefix)) = window_row_mean(cmdRows, 1, idx);
    row.(sprintf('cmd_m_reg_q_%s_mean', prefix)) = window_row_mean(cmdRows, 2, idx);
    row.(sprintf('cmd_m_energy_d_%s_mean', prefix)) = window_row_mean(cmdRows, 3, idx);
    row.(sprintf('cmd_m_energy_q_%s_mean', prefix)) = window_row_mean(cmdRows, 4, idx);
    row.(sprintf('meas_reg_d_%s_mean', prefix)) = window_row_mean(measRows, 1, idx);
    row.(sprintf('meas_reg_q_%s_mean', prefix)) = window_row_mean(measRows, 2, idx);
    row.(sprintf('meas_energy_d_%s_mean', prefix)) = window_row_mean(measRows, 3, idx);
    row.(sprintf('meas_energy_q_%s_mean', prefix)) = window_row_mean(measRows, 4, idx);
end

function v = matrix_max_abs(rows)
    if isempty(rows)
        v = NaN;
    else
        v = max(abs(rows(:)));
    end
end

function v = tail_row_mean(rows, idx)
    if isempty(rows) || size(rows, 1) < idx || size(rows, 2) < 1
        v = NaN;
        return;
    end
    tailStart = max(1, round(size(rows, 2) * 0.7));
    v = mean(rows(idx, tailStart:end));
end

function v = window_row_mean(rows, rowIdx, mask)
    if isempty(rows) || size(rows, 1) < rowIdx || isempty(mask)
        v = NaN;
        return;
    end
    mask = mask(:)';
    n = min(numel(mask), size(rows, 2));
    if n < 1
        v = NaN;
        return;
    end
    mask = mask(1:n);
    if ~any(mask)
        v = NaN;
        return;
    end
    v = mean(rows(rowIdx, mask));
end

function n = window_sample_count(rows, mask)
    if isempty(rows) || isempty(mask)
        n = 0;
        return;
    end
    mask = mask(:)';
    nUse = min(numel(mask), size(rows, 2));
    if nUse < 1
        n = 0;
        return;
    end
    n = sum(mask(1:nUse));
end

function stage_trajectory_file_if_needed(rootDir, modelDir, M)
    modes = evalin('base', 'hpt_compare_modes');
    trajectoryFile = evalin('base', 'hpt_compare_trajectory_file');
    if ~any(string(modes) == "trajectory_action") || strlength(string(trajectoryFile)) == 0
        return;
    end

    srcFile = char(trajectoryFile);
    assert(exist(srcFile, 'file') == 2, 'Missing trajectory file: %s', srcFile);
    dstFiles = {
        fullfile(rootDir, 'hpt_sac_trajectory.mat');
        fullfile(modelDir, 'hpt_sac_trajectory.mat');
        fullfile(pwd, 'hpt_sac_trajectory.mat');
    };
    modelPath = which(M);
    if ~isempty(modelPath)
        dstFiles{end+1} = fullfile(fileparts(modelPath), 'hpt_sac_trajectory.mat'); %#ok<AGROW>
    end

    for didx = 1:numel(dstFiles)
        dstFile = dstFiles{didx};
        dstParent = fileparts(dstFile);
        if exist(dstParent, 'dir') ~= 7
            mkdir(dstParent);
        end
        if ~strcmp(srcFile, dstFile)
            copyfile(srcFile, dstFile, 'f');
        end
    end

    % MATLAB Function blocks use coder.load for the trajectory MAT file.
    % Clear function caches after staging so trajectory_action cannot reuse an
    % older compiled constant from a previous validation run.
    clear functions;
    clear mex;
end

function [d, q] = reg6_to_dq(reg6, angle)
    ma = reg6(1);
    mb = reg6(3);
    mc = reg6(5);
    alpha = (2/3) * (ma - 0.5*mb - 0.5*mc);
    beta = (sqrt(3)/3) * (mb - mc);
    s = sin(angle);
    c = cos(angle);
    d = s*alpha - c*beta;
    q = c*alpha + s*beta;
end

function y = clip_scalar(x, lo, hi)
    y = min(max(x, lo), hi);
end

function in = set_common_variables(in, M, sacEnable, energyEnable, policyMode, ...
    actorSelectMode, targetPhaseRms, actorFilterTau)

    in = in.setVariable('hpt_sac_enable', sacEnable, 'Workspace', M);
    in = in.setVariable('hpt_sac_energy_enable', energyEnable, 'Workspace', M);
    in = in.setVariable('hpt_sac_policy_mode', policyMode, 'Workspace', M);
    in = in.setVariable('hpt_sac_actor_select_mode', actorSelectMode, 'Workspace', M);
    in = in.setVariable('hpt_sac_actor_filter_tau', actorFilterTau, 'Workspace', M);
    in = in.setVariable('hpt_sac_guard_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
    faultStartForGridNorm = evalin('base', 'hpt_compare_fault_start');
    gridNormStartupS = min(0.070, max(0.030, faultStartForGridNorm - 0.005));
    in = in.setVariable('hpt_sac_gridnorm_startup_s', gridNormStartupS, ...
        'Workspace', M);
    modelOverrides = evalin('base', 'hpt_compare_model_params');
    names = fieldnames(modelOverrides);
    for k = 1:numel(names)
        in = in.setVariable(names{k}, modelOverrides.(names{k}), 'Workspace', M);
    end
    fixedAction = evalin('base', 'hpt_compare_fixed_action');
    in = in.setVariable('hpt_sac_fixed_reg_d', fixedAction(1), 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_reg_q', fixedAction(2), 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_energy_d', fixedAction(3), 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_energy_q', fixedAction(4), 'Workspace', M);
    trajectoryFile = evalin('base', 'hpt_compare_trajectory_file');
    if strlength(string(trajectoryFile)) > 0
        srcFile = char(trajectoryFile);
        trajData = load(srcFile, 'hpt_traj_t', 'hpt_traj_action');
        assert(isfield(trajData, 'hpt_traj_t') && isfield(trajData, 'hpt_traj_action'), ...
            'Trajectory file must contain hpt_traj_t and hpt_traj_action');
        trajT = double(trajData.hpt_traj_t(:));
        trajAction = double(trajData.hpt_traj_action);
        assert(size(trajAction, 1) == numel(trajT) && size(trajAction, 2) == 4, ...
            'hpt_traj_action must be Nx4 and match hpt_traj_t');
        in = in.setVariable('hpt_traj_t', trajT, 'Workspace', M);
        in = in.setVariable('hpt_traj_action', trajAction, 'Workspace', M);
        dstFiles = {fullfile(pwd, 'hpt_sac_trajectory.mat')};
        modelPath = which(M);
        if ~isempty(modelPath)
            dstFiles{end+1} = fullfile(fileparts(modelPath), 'hpt_sac_trajectory.mat'); %#ok<AGROW>
        end
        for didx = 1:numel(dstFiles)
            dstFile = dstFiles{didx};
            if ~strcmp(srcFile, dstFile)
                copyfile(srcFile, dstFile, 'f');
            end
        end
    end
end

function row = base_row(M, topology, scenarioType, caseName, mode, gridVoltage, faultPu)
    row = struct();
    row.validator_schema = "hpt-frt-gates-v3-gbt19963.1";
    row.model = string(M);
    row.topology = string(topology);
    row.scenario_type = string(scenarioType);
    row.case_name = string(caseName);
    row.mode = string(mode);
    row.guard_enable = 0.0;
    row.grid_V = gridVoltage;
    row.fault_pu = faultPu;
    row.fault_a_pu = faultPu;
    row.fault_b_pu = faultPu;
    row.fault_c_pu = faultPu;
    row.fault_start_s = NaN;
    row.fault_clear_s = NaN;
    row.fault_duration_s = NaN;
    row.fault_settle_s = NaN;
    row.lv_metric_source = "";
    row.stop_time_s = NaN;
    row.lv_mean = NaN;
    row.lv_a = NaN;
    row.lv_b = NaN;
    row.lv_c = NaN;
    row.lv_unbalance = NaN;
    row.lv_recovery_mean = NaN;
    row.lv_peak = NaN;
    row.lv_min = NaN;
    row.fault_lv_min = NaN;
    row.fault_lv_max = NaN;
    row.fault_lv_band_violation_max_pu = NaN;
    row.fault_lv_band_violation_mean_pu = NaN;
    row.fault_lv_band_violation_duration_s = NaN;
    row.fault_lv_band_pass = false;
    row.recovery_lv_min = NaN;
    row.recovery_lv_max = NaN;
    row.vdc_mean = NaN;
    row.vdc_min = NaN;
    row.vdc_max = NaN;
    row.action_max_abs = NaN;
    row.cmd_action_max_abs = NaN;
    row.bridge_modulation_abs_max = NaN;
    row.cmd_m_reg_d_mean = NaN;
    row.cmd_m_reg_q_mean = NaN;
    row.cmd_m_energy_d_mean = NaN;
    row.cmd_m_energy_q_mean = NaN;
    row.hpt_sac_enable_cmd = NaN;
    row.hpt_sac_energy_enable_cmd = NaN;
    row.hpt_sac_policy_mode_cmd = NaN;
    row.hpt_sac_actor_select_mode_cmd = NaN;
    row.cmd_m_reg_d_fault_mean = NaN;
    row.cmd_m_reg_q_fault_mean = NaN;
    row.cmd_m_energy_d_fault_mean = NaN;
    row.cmd_m_energy_q_fault_mean = NaN;
    row.cmd_m_reg_d_recovery_mean = NaN;
    row.cmd_m_reg_q_recovery_mean = NaN;
    row.cmd_m_energy_d_recovery_mean = NaN;
    row.cmd_m_energy_q_recovery_mean = NaN;
    row.action_fault_sample_count = NaN;
    row.action_fault_cmd_cols = NaN;
    row.action_recovery_sample_count = NaN;
    row.action_recovery_cmd_cols = NaN;
    row.meas_reg_d_mean = NaN;
    row.meas_reg_q_mean = NaN;
    row.meas_energy_d_mean = NaN;
    row.meas_energy_q_mean = NaN;
    row.meas_reg_d_fault_mean = NaN;
    row.meas_reg_q_fault_mean = NaN;
    row.meas_energy_d_fault_mean = NaN;
    row.meas_energy_q_fault_mean = NaN;
    row.meas_reg_d_recovery_mean = NaN;
    row.meas_reg_q_recovery_mean = NaN;
    row.meas_energy_d_recovery_mean = NaN;
    row.meas_energy_q_recovery_mean = NaN;
    row.reg_d_mean = NaN;
    row.reg_q_mean = NaN;
    row.energy_d_mean = NaN;
    row.energy_q_mean = NaN;
    row.obs_vpu_mean = NaN;
    row.obs_vpos_mean = NaN;
    row.obs_vdcpu_mean = NaN;
    row.obs_verr_mean = NaN;
    row.obs_fault_flag_mean = NaN;
    row.obs_recovery_flag_mean = NaN;
    row.obs_vpu_pre_mean = NaN;
    row.obs_vpos_pre_mean = NaN;
    row.obs_vneg_pre_mean = NaN;
    row.obs_vdcpu_pre_mean = NaN;
    row.obs_fault_flag_pre_mean = NaN;
    row.obs_recovery_flag_pre_mean = NaN;
    row.obs_vpu_fault_mean = NaN;
    row.obs_vpos_fault_mean = NaN;
    row.obs_vneg_fault_mean = NaN;
    row.obs_vdcpu_fault_mean = NaN;
    row.obs_fault_flag_fault_mean = NaN;
    row.obs_recovery_flag_fault_mean = NaN;
    row.obs_vpu_recovery_mean = NaN;
    row.obs_vpos_recovery_mean = NaN;
    row.obs_vneg_recovery_mean = NaN;
    row.obs_vdcpu_recovery_mean = NaN;
    row.obs_fault_flag_recovery_mean = NaN;
    row.obs_recovery_flag_recovery_mean = NaN;
    row.gbt_category = "";
    row.pcc_assessment_signal = "";
    row.pcc_fault_voltage_min_pu = NaN;
    row.pcc_fault_voltage_max_pu = NaN;
    row.pcc_envelope_violation_max_pu = NaN;
    row.pcc_envelope_violation_mean_pu = NaN;
    row.pcc_envelope_violation_duration_s = NaN;
    row.pcc_envelope_margin_min_pu = NaN;
    row.pcc_envelope_pass = false;
    row.scenario_valid = false;
    row.scenario_valid_reason = "not_evaluated";
    row.gbt_voltage_margin_min = NaN;
    row.gbt_voltage_envelope_pass = false;
    row.envelope_violation_max_pu = NaN;
    row.envelope_violation_mean_pu = NaN;
    row.envelope_violation_duration_s = NaN;
    row.envelope_margin_min_pu = NaN;
    row.envelope_pass = false;
    row.load_quality_violation_max_pu = NaN;
    row.load_quality_violation_duration_s = NaN;
    row.load_quality_pass = false;
    row.recovery_violation_max_pu = NaN;
    row.recovery_violation_mean_pu = NaN;
    row.recovery_violation_duration_s = NaN;
    row.recovery_envelope_pass = false;
    row.timestep_envelope_pass = false;
    row.gbt_recover_cover_s = NaN;
    row.gbt_recover_evaluated = false;
    row.gbt_recover_final_dev = NaN;
    row.gbt_recover_pass = false;
    row.gbt_vdc_pu_min = NaN;
    row.gbt_vdc_pu_max = NaN;
    row.gbt_vdc_survive_pass = false;
    row.gbt_action_limit_pass = false;
    row.grid_vpos_pu_min = NaN;
    row.grid_vpos_pu_mean = NaN;
    row.source_vpos_seq_pre_pu = NaN;
    row.source_vneg_seq_pre_pu = NaN;
    row.source_va_pre_pu = NaN;
    row.source_vb_pre_pu = NaN;
    row.source_vc_pre_pu = NaN;
    row.source_vabc_unbalance_pre_pu = NaN;
    row.source_vpos_seq_fault_pu = NaN;
    row.source_vneg_seq_fault_pu = NaN;
    row.source_va_fault_pu = NaN;
    row.source_vb_fault_pu = NaN;
    row.source_vc_fault_pu = NaN;
    row.source_vabc_unbalance_fault_pu = NaN;
    row.source_vpos_seq_recovery_pu = NaN;
    row.source_vneg_seq_recovery_pu = NaN;
    row.source_va_recovery_pu = NaN;
    row.source_vb_recovery_pu = NaN;
    row.source_vc_recovery_pu = NaN;
    row.source_vabc_unbalance_recovery_pu = NaN;
    row.grid_vpos_seq_pre_pu = NaN;
    row.grid_vneg_seq_pre_pu = NaN;
    row.grid_va_pre_pu = NaN;
    row.grid_vb_pre_pu = NaN;
    row.grid_vc_pre_pu = NaN;
    row.grid_vabc_unbalance_pre_pu = NaN;
    row.grid_vpos_seq_fault_pu = NaN;
    row.grid_vneg_seq_fault_pu = NaN;
    row.grid_va_fault_pu = NaN;
    row.grid_vb_fault_pu = NaN;
    row.grid_vc_fault_pu = NaN;
    row.grid_vabc_unbalance_fault_pu = NaN;
    row.grid_vpos_seq_recovery_pu = NaN;
    row.grid_vneg_seq_recovery_pu = NaN;
    row.grid_va_recovery_pu = NaN;
    row.grid_vb_recovery_pu = NaN;
    row.grid_vc_recovery_pu = NaN;
    row.grid_vabc_unbalance_recovery_pu = NaN;
    row.grid_id_mean_pu = NaN;
    row.grid_iq_mean_pu = NaN;
    row.grid_iq_ref_mean_pu = NaN;
    row.grid_iq_shortfall_max_pu = NaN;
    row.grid_iq_met_fraction = NaN;
    row.grid_iq_wrong_sign = false;
    row.grid_current_limit_pu = NaN;
    row.grid_current_eval_start_s = NaN;
    row.grid_current_peak_global_pu = NaN;
    row.grid_current_peak_fault_pu = NaN;
    row.grid_current_peak_recovery_pu = NaN;
    row.grid_current_peak_pu = NaN;
    row.grid_idq_peak_pu = NaN;
    row.gbt_reactive_evaluated = false;
    row.gbt_reactive_response_ms = NaN;
    row.gbt_reactive_response_pass = false;
    row.gbt_grid_current_limit_pass = false;
    row.voltage_survival_current_gate = false;
    row.gbt_reactive_status = "";
    row.gbt_reactive_pass = false;
    row.gbt_limit_status = "";
    row.gbt_certifiable = false;
    row.remained_connected_evaluated = false;
    row.remained_connected = false;
    row.remained_connected_evidence = "not_evaluated";
    row.simulation_completed = false;
    row.equipment_safety_pass = false;
    row.active_power_recovery_evaluated = false;
    row.active_power_recovery_pass = false;
    row.l1_load_voltage_survival_pass = false;
    row.l1_reason = "not_evaluated";
    row.l2_grid_code_ride_through_pass = false;
    row.l2_reason = "not_evaluated";
    row.l3_full_frt_pass = false;
    row.l3_reason = "not_evaluated";
    row.voltage_survival_pass = false;
    row.voltage_survival_reason = "";
    row.full_frt_pass = false;
    row.full_frt_reason = "";
    row.within_window = false;
    row.window_reason = "";
    row.control_score = NaN;
end

function [ok, reason] = assess_steady(row, caseSpec)
    lvLo = caseSpec{6};
    lvHi = caseSpec{7};
    ubHi = caseSpec{8};
    vdcLo = caseSpec{9};
    vdcHi = caseSpec{10};
    reasons = strings(0, 1);
    if ~(row.lv_mean >= lvLo && row.lv_mean <= lvHi)
        reasons(end+1) = "steady_lv"; %#ok<AGROW>
    end
    if ~(row.lv_unbalance <= ubHi)
        reasons(end+1) = "steady_unbalance"; %#ok<AGROW>
    end
    if ~(row.vdc_mean >= vdcLo && row.vdc_mean <= vdcHi)
        reasons(end+1) = "steady_vdc"; %#ok<AGROW>
    end
    if ~(row.action_max_abs <= 0.9501)
        reasons(end+1) = "action_limit"; %#ok<AGROW>
    end
    ok = isempty(reasons);
    reason = strjoin(reasons, ";");
end

function [ok, reason] = assess_fault_grid_code_ride_through(row)
    reasons = strings(0, 1);
    if ~row.l1_load_voltage_survival_pass
        reasons(end+1) = "l1_load_voltage_survival"; %#ok<AGROW>
    end
    if ~row.scenario_valid
        reasons(end+1) = "scenario_outside_gbt_voltage_envelope"; %#ok<AGROW>
    end
    if ~row.remained_connected_evaluated
        reasons(end+1) = "connection_status_not_evaluated"; %#ok<AGROW>
    elseif ~row.remained_connected
        reasons(end+1) = "disconnected_or_incomplete_simulation"; %#ok<AGROW>
    end
    if ~row.equipment_safety_pass
        reasons(end+1) = "equipment_safety"; %#ok<AGROW>
    end
    ok = isempty(reasons);
    reason = strjoin(reasons, ";");
end

function [ok, reason] = assess_fault_full_frt(row)
    reasons = strings(0, 1);
    if ~row.l2_grid_code_ride_through_pass
        reasons(end+1) = "l2_grid_code_ride_through"; %#ok<AGROW>
    end
    if ~row.gbt_reactive_evaluated
        reasons(end+1) = "reactive_support_not_evaluated"; %#ok<AGROW>
    elseif ~row.gbt_reactive_pass
        reasons(end+1) = string(row.gbt_reactive_status); %#ok<AGROW>
    end
    if ~row.active_power_recovery_evaluated
        reasons(end+1) = "active_power_recovery_not_evaluated"; %#ok<AGROW>
    elseif ~row.active_power_recovery_pass
        reasons(end+1) = "active_power_recovery"; %#ok<AGROW>
    end
    ok = isempty(reasons);
    reason = strjoin(reasons, ";");
end

function [ok, reason] = assess_fault_load_voltage_survival(row)
    reasons = strings(0, 1);
    % L1 is a project-defined HPT load-quality and equipment-safety gate. The
    % GB/T PCC curve is assessed separately by scenario_valid and L2.
    if ~row.fault_lv_band_pass
        reasons(end+1) = "timestep_fault_lv_band"; %#ok<AGROW>
    end
    if ~(row.recovery_violation_max_pu <= 1e-3)
        reasons(end+1) = "timestep_recovery_envelope"; %#ok<AGROW>
    end
    if ~(row.vdc_min >= 650.0 && row.vdc_max <= 1000.0)
        reasons(end+1) = "dc_link_bounds"; %#ok<AGROW>
    end
    if ~(row.action_max_abs <= 0.9501)
        reasons(end+1) = "action_limit"; %#ok<AGROW>
    end
    if row.voltage_survival_current_gate && ~row.gbt_grid_current_limit_pass
        reasons(end+1) = "grid_current_limit"; %#ok<AGROW>
    end
    ok = isempty(reasons);
    reason = strjoin(reasons, ";");
end

function score = score_row(row)
    score = 0.0;
    if row.scenario_type == "steady"
        score = score + abs(row.lv_mean - 207.0) / 5.0;
        score = score + row.lv_unbalance / 5.0;
        score = score + max(0.0, 760.0 - row.vdc_mean) / 10.0;
        score = score + max(0.0, row.vdc_mean - 930.0) / 10.0;
    else
        score = score + abs(row.lv_mean - 207.0) / 5.0;
        score = score + abs(row.lv_recovery_mean - 207.0) / 5.0;
        score = score + max(0.0, row.lv_peak - 235.0) / 3.0;
        score = score + max(0.0, 180.0 - row.lv_min) / 3.0;
        score = score + max(0.0, 650.0 - row.vdc_min) / 10.0;
        score = score + max(0.0, row.vdc_max - 1000.0) / 10.0;
        if ~isnan(row.grid_iq_shortfall_max_pu)
            score = score + 40.0 * max(0.0, row.grid_iq_shortfall_max_pu);
        end
        if ~isnan(row.grid_current_peak_pu)
            score = score + 50.0 * max(0.0, row.grid_current_peak_pu - 1.5);
        end
        if ~isnan(row.recovery_violation_max_pu)
            score = score + 120.0 * max(0.0, row.recovery_violation_max_pu)^2;
        end
        if ~isnan(row.fault_lv_band_violation_max_pu)
            score = score + 180.0 * max(0.0, row.fault_lv_band_violation_max_pu)^2;
        end
        if ~isnan(row.recovery_violation_duration_s)
            score = score + 30.0 * max(0.0, row.recovery_violation_duration_s);
        end
        if ~isnan(row.fault_lv_band_violation_duration_s)
            score = score + 35.0 * max(0.0, row.fault_lv_band_violation_duration_s);
        end
    end
    score = score + max(0.0, row.action_max_abs - 0.9501) * 100.0;
    if ~row.within_window
        score = score + 100.0;
    end
end

function row = add_fault_gate_metrics(row, lvRmsInst, vdc, actRows, ...
    gridVRows, gridIRows, t, targetPhaseRms, faultPu, faultStart, ...
    faultClear, stopTime, faultSettleS, faultPhasePu)

    solverTol = 1e-3;
    vdcBase = 800.0;
    lvPu = lvRmsInst ./ targetPhaseRms;
    dt = median(diff(t));

    % Project-defined HPT load-side quality gate. These limits are not the
    % GB/T PCC voltage-time curve.
    faultBandIdx = t >= faultStart + max(0.0, faultSettleS) & t <= faultClear;
    faultLoPu = 176.0 / targetPhaseRms;
    faultHiPu = 238.0 / targetPhaseRms;
    faultBandViolation = max(max(0.0, faultLoPu - lvPu), ...
        max(0.0, lvPu - faultHiPu));
    faultBandViolation(~faultBandIdx) = 0.0;
    if any(faultBandIdx)
        row.fault_lv_min = min(lvRmsInst(faultBandIdx));
        row.fault_lv_max = max(lvRmsInst(faultBandIdx));
        row.fault_lv_band_violation_max_pu = max(faultBandViolation(faultBandIdx));
        row.fault_lv_band_violation_mean_pu = mean(faultBandViolation(faultBandIdx));
        row.fault_lv_band_violation_duration_s = dt * ...
            nnz(faultBandViolation(faultBandIdx) > solverTol);
        row.fault_lv_band_pass = row.fault_lv_band_violation_max_pu <= solverTol;
    else
        row.fault_lv_min = NaN;
        row.fault_lv_max = NaN;
        row.fault_lv_band_violation_max_pu = NaN;
        row.fault_lv_band_violation_mean_pu = NaN;
        row.fault_lv_band_violation_duration_s = NaN;
        row.fault_lv_band_pass = false;
    end

    recoveryIdx = t >= faultClear + 0.035 & t <= stopTime;
    recoveryViolation = max(0.0, abs(lvPu - 1.0) - 0.07);
    recoveryViolation(~recoveryIdx) = 0.0;
    if any(recoveryIdx)
        row.recovery_lv_min = min(lvRmsInst(recoveryIdx));
        row.recovery_lv_max = max(lvRmsInst(recoveryIdx));
        row.recovery_violation_max_pu = max(recoveryViolation(recoveryIdx));
        row.recovery_violation_mean_pu = mean(recoveryViolation(recoveryIdx));
        row.recovery_violation_duration_s = dt * nnz(recoveryViolation(recoveryIdx) > solverTol);
        row.recovery_envelope_pass = row.recovery_violation_max_pu <= solverTol;
    else
        row.recovery_lv_min = NaN;
        row.recovery_lv_max = NaN;
        row.recovery_violation_max_pu = NaN;
        row.recovery_violation_mean_pu = NaN;
        row.recovery_violation_duration_s = NaN;
        row.recovery_envelope_pass = false;
    end
    row.load_quality_violation_max_pu = max( ...
        row.fault_lv_band_violation_max_pu, row.recovery_violation_max_pu);
    row.load_quality_violation_duration_s = ...
        row.fault_lv_band_violation_duration_s + row.recovery_violation_duration_s;
    row.load_quality_pass = row.fault_lv_band_pass && row.recovery_envelope_pass;
    row.timestep_envelope_pass = row.load_quality_pass;

    % Compatibility fields now explicitly mirror project load quality. They
    % must not be interpreted as the PCC grid-code envelope.
    row.envelope_violation_max_pu = row.load_quality_violation_max_pu;
    row.envelope_violation_mean_pu = max( ...
        row.fault_lv_band_violation_mean_pu, row.recovery_violation_mean_pu);
    row.envelope_violation_duration_s = row.load_quality_violation_duration_s;
    row.envelope_margin_min_pu = -row.load_quality_violation_max_pu;
    row.envelope_pass = row.load_quality_pass;
    row.gbt_recover_cover_s = stopTime - faultClear;
    row.gbt_recover_evaluated = any(recoveryIdx);
    row.gbt_recover_final_dev = row.recovery_violation_max_pu;
    row.gbt_recover_pass = row.recovery_envelope_pass;

    % GB/T scenario validity is assessed at the PCC. Single-phase faults use
    % the affected phase voltage; two- and three-phase faults use line voltage.
    [pccPu, assessmentSignal] = hpt_pcc_assessment_voltage( ...
        gridVRows, t, faultPhasePu, faultPu, 10000.0, 50.0);
    tRel = t - faultStart;
    pccAssessIdx = t >= faultStart + max(0.0, faultSettleS) & t <= stopTime;
    if faultPu < 1.0
        row.gbt_category = "LVRT";
        pccEnv = hpt_gbt19963_envelope("LVRT", tRel);
        pccMargin = pccPu - pccEnv;
        pccViolation = max(0.0, pccEnv - pccPu);
    else
        row.gbt_category = "HVRT";
        pccEnv = hpt_gbt19963_envelope("HVRT", tRel);
        pccMargin = pccEnv - pccPu;
        pccViolation = max(0.0, pccPu - pccEnv);
    end
    pccViolation(~pccAssessIdx) = 0.0;
    pccMargin(~pccAssessIdx) = Inf;
    row.pcc_assessment_signal = assessmentSignal;
    if any(faultBandIdx)
        row.pcc_fault_voltage_min_pu = min(pccPu(faultBandIdx));
        row.pcc_fault_voltage_max_pu = max(pccPu(faultBandIdx));
    end
    if any(pccAssessIdx) && all(isfinite(pccPu(pccAssessIdx)))
        row.pcc_envelope_violation_max_pu = max(pccViolation(pccAssessIdx));
        row.pcc_envelope_violation_mean_pu = mean(pccViolation(pccAssessIdx));
        row.pcc_envelope_violation_duration_s = dt * ...
            nnz(pccViolation(pccAssessIdx) > solverTol);
        row.pcc_envelope_margin_min_pu = min(pccMargin(pccAssessIdx));
        row.pcc_envelope_pass = row.pcc_envelope_violation_max_pu <= solverTol;
        row.scenario_valid = row.pcc_envelope_pass;
        if row.scenario_valid
            row.scenario_valid_reason = "pass";
        else
            row.scenario_valid_reason = "pcc_voltage_outside_gbt_envelope";
        end
    else
        row.scenario_valid = false;
        row.scenario_valid_reason = "pcc_assessment_signal_missing";
    end
    row.gbt_voltage_margin_min = row.pcc_envelope_margin_min_pu;
    row.gbt_voltage_envelope_pass = row.scenario_valid;

    row.gbt_vdc_pu_min = min(vdc) / vdcBase;
    row.gbt_vdc_pu_max = max(vdc) / vdcBase;
    row.gbt_vdc_survive_pass = row.gbt_vdc_pu_min >= 0.75 && ...
        row.gbt_vdc_pu_max <= 1.25;
    row.gbt_action_limit_pass = max(abs(actRows), [], 'all') <= 0.9501;
    row = add_grid_reactive_metrics(row, gridVRows, gridIRows, t, ...
        faultStart, faultClear);
    row.gbt_limit_status = sprintf( ...
        "grid_current_eval_peak_pu=%.3f;grid_current_global_peak_pu=%.3f;action_max=%.3f", ...
        row.grid_current_peak_pu, row.grid_current_peak_global_pu, ...
        max(abs(actRows), [], 'all'));
    row.active_power_recovery_evaluated = false;
    row.active_power_recovery_pass = false;
    row.gbt_certifiable = false;
end

function row = add_grid_reactive_metrics(row, gridVRows, gridIRows, t, ...
    faultStart, faultClear)

    reactiveTol = 0.12;
    reactiveDelay = 0.06;
    reactiveDwell = 0.80;
    signEps = 1e-3;
    iqPeLimitPu = 0.30;
    currentLimitPu = 1.50;
    currentBlanking = 0.020;
    vMvLineRms = 10000.0;
    sBase = 400e3;
    vPhasePeak = sqrt(2) * vMvLineRms / sqrt(3);
    iBasePeak = sqrt(2) * sBase / (sqrt(3) * vMvLineRms);

    [vPosPu, idPu, iqPu] = grid_dq_from_voltage_angle(gridVRows, gridIRows, ...
        vPhasePeak, iBasePeak);
    refPu = arrayfun(@(v) grid_iq_reference(v, iqPeLimitPu), vPosPu);
    assessIdx = t >= faultStart + reactiveDelay & t <= faultClear;
    demandIdx = assessIdx & abs(refPu) > reactiveTol;
    currentEvalStart = faultStart + currentBlanking;
    currentEvalIdx = t >= currentEvalStart;
    currentFaultIdx = t >= currentEvalStart & t <= faultClear;
    currentRecoveryIdx = t >= faultClear + currentBlanking;

    row.grid_vpos_pu_min = min(vPosPu(t >= faultStart & t <= faultClear));
    row.grid_vpos_pu_mean = mean(vPosPu(t >= faultStart & t <= faultClear));
    row.grid_id_mean_pu = mean(idPu(assessIdx));
    row.grid_iq_mean_pu = mean(iqPu(assessIdx));
    row.grid_iq_ref_mean_pu = mean(refPu(assessIdx));
    row.grid_current_limit_pu = currentLimitPu;
    row.grid_current_eval_start_s = currentEvalStart;
    row.grid_current_peak_global_pu = max_abs_current_pu(gridIRows, true(size(t)), iBasePeak);
    row.grid_current_peak_fault_pu = max_abs_current_pu(gridIRows, currentFaultIdx, iBasePeak);
    row.grid_current_peak_recovery_pu = max_abs_current_pu(gridIRows, currentRecoveryIdx, iBasePeak);
    row.grid_current_peak_pu = max_abs_current_pu(gridIRows, currentEvalIdx, iBasePeak);
    row.grid_idq_peak_pu = max(sqrt(idPu.^2 + iqPu.^2));
    row.gbt_grid_current_limit_pass = row.grid_current_peak_pu <= currentLimitPu;

    wrongSign = (vPosPu < 0.9 & iqPu < -signEps) | ...
        (vPosPu > 1.1 & iqPu > signEps);
    row.grid_iq_wrong_sign = any(wrongSign(assessIdx));

    if ~any(assessIdx)
        row.gbt_reactive_status = "not_evaluated_no_fault_current_window";
        row.gbt_reactive_evaluated = false;
        row.gbt_reactive_pass = false;
        return;
    end
    if ~any(demandIdx)
        row.grid_iq_shortfall_max_pu = 0.0;
        row.grid_iq_met_fraction = NaN;
        row.gbt_reactive_status = "not_evaluated_no_sustained_reactive_demand_after_delay";
        row.gbt_reactive_evaluated = false;
        row.gbt_reactive_pass = false;
        return;
    end

    shortfall = zeros(size(refPu));
    lvrtIdx = refPu > reactiveTol;
    hvrtIdx = refPu < -reactiveTol;
    shortfall(lvrtIdx) = max(0.0, (refPu(lvrtIdx) - reactiveTol) - iqPu(lvrtIdx));
    shortfall(hvrtIdx) = max(0.0, iqPu(hvrtIdx) - (refPu(hvrtIdx) + reactiveTol));
    metIdx = demandIdx & shortfall <= 1e-9;

    row.gbt_reactive_evaluated = true;
    row.grid_iq_shortfall_max_pu = max(shortfall(demandIdx));
    row.grid_iq_met_fraction = nnz(metIdx) / nnz(demandIdx);

    firstMet = find(metIdx, 1, 'first');
    if isempty(firstMet)
        row.gbt_reactive_response_ms = Inf;
        row.gbt_reactive_response_pass = false;
    else
        row.gbt_reactive_response_ms = 1000.0 * (t(firstMet) - faultStart);
        row.gbt_reactive_response_pass = row.gbt_reactive_response_ms <= ...
            1000.0 * reactiveDelay + 1e-6;
    end

    if row.grid_iq_wrong_sign
        row.gbt_reactive_status = "reactive_wrong_sign";
        row.gbt_reactive_pass = false;
    elseif row.grid_iq_met_fraction < reactiveDwell
        row.gbt_reactive_status = "reactive_shortfall";
        row.gbt_reactive_pass = false;
    elseif ~row.gbt_reactive_response_pass
        row.gbt_reactive_status = "reactive_response_slow";
        row.gbt_reactive_pass = false;
    else
        row.gbt_reactive_status = "pass";
        row.gbt_reactive_pass = true;
    end
end

function [vPosPu, idPu, iqPu] = grid_dq_from_voltage_angle(gridVRows, ...
    gridIRows, vPhasePeak, iBasePeak)

    va = gridVRows(1, :)';
    vb = gridVRows(2, :)';
    vc = gridVRows(3, :)';
    ia = gridIRows(1, :)';
    ib = gridIRows(2, :)';
    ic = gridIRows(3, :)';

    valpha = (2/3) * (va - 0.5*vb - 0.5*vc);
    vbeta = (sqrt(3)/3) * (vb - vc);
    ialpha = (2/3) * (ia - 0.5*ib - 0.5*ic);
    ibeta = (sqrt(3)/3) * (ib - ic);
    theta = atan2(vbeta, valpha);
    id = ialpha .* cos(theta) + ibeta .* sin(theta);
    iq = -ialpha .* sin(theta) + ibeta .* cos(theta);

    vPosPu = sqrt(valpha.^2 + vbeta.^2) ./ vPhasePeak;
    idPu = id ./ iBasePeak;
    % The V-I block current is oriented grid/source -> HPT.  FRT support is
    % reported in the opposite convention: positive iq means the HPT injects
    % voltage-supporting reactive current during LVRT.
    iqPu = -iq ./ iBasePeak;
end

function peakPu = max_abs_current_pu(gridIRows, idx, iBasePeak)
    if ~any(idx)
        peakPu = NaN;
        return;
    end
    peakPu = max(max(abs(gridIRows(:, idx)))) / iBasePeak;
end

function iqRef = grid_iq_reference(vPosPu, iqPeLimitPu)
    if vPosPu < 0.9
        iqRef = min(iqPeLimitPu, 1.5 * (0.9 - vPosPu));
    elseif vPosPu > 1.1
        iqRef = max(-iqPeLimitPu, -1.5 * (vPosPu - 1.1));
    else
        iqRef = 0.0;
    end
end

function row = add_grid_window_metrics(row, label, gridVRows, t, idx, basePhaseRms)
    label = char(label);
    [phasePu, unbalancePu, vPosPu, vNegPu] = grid_window_metrics( ...
        gridVRows, t, idx, basePhaseRms);
    row.(sprintf('grid_va_%s_pu', label)) = phasePu(1);
    row.(sprintf('grid_vb_%s_pu', label)) = phasePu(2);
    row.(sprintf('grid_vc_%s_pu', label)) = phasePu(3);
    row.(sprintf('grid_vabc_unbalance_%s_pu', label)) = unbalancePu;
    row.(sprintf('grid_vpos_seq_%s_pu', label)) = vPosPu;
    row.(sprintf('grid_vneg_seq_%s_pu', label)) = vNegPu;
end

function row = add_source_window_metrics(row, label, sourceVRows, t, idx, basePhaseRms)
    label = char(label);
    [phasePu, unbalancePu, vPosPu, vNegPu] = grid_window_metrics( ...
        sourceVRows, t, idx, basePhaseRms);
    row.(sprintf('source_va_%s_pu', label)) = phasePu(1);
    row.(sprintf('source_vb_%s_pu', label)) = phasePu(2);
    row.(sprintf('source_vc_%s_pu', label)) = phasePu(3);
    row.(sprintf('source_vabc_unbalance_%s_pu', label)) = unbalancePu;
    row.(sprintf('source_vpos_seq_%s_pu', label)) = vPosPu;
    row.(sprintf('source_vneg_seq_%s_pu', label)) = vNegPu;
end

function [phasePu, unbalancePu, vPosPu, vNegPu] = grid_window_metrics( ...
    gridVRows, t, idx, basePhaseRms)

    phasePu = [NaN, NaN, NaN];
    unbalancePu = NaN;
    vPosPu = NaN;
    vNegPu = NaN;
    if isempty(gridVRows) || ~any(idx)
        return;
    end
    n = min(size(gridVRows, 2), numel(idx));
    idx = idx(:)';
    idx = idx(1:n);
    if ~any(idx)
        return;
    end
    phaseRms = sqrt(mean(gridVRows(:, idx).^2, 2));
    phasePu = phaseRms(:)' ./ basePhaseRms;
    unbalancePu = (max(phaseRms) - min(phaseRms)) / basePhaseRms;
    [vPosPu, vNegPu] = sequence_voltage_pu(gridVRows, t, idx, basePhaseRms, 50.0);
end

function row = add_obs_window_metrics(row, label, obsRows, idx)
    label = char(label);
    if isempty(obsRows) || size(obsRows, 1) < 18 || ~any(idx)
        return;
    end
    n = min(size(obsRows, 2), numel(idx));
    idx = idx(:)';
    idx = idx(1:n);
    if ~any(idx)
        return;
    end
    row.(sprintf('obs_vpu_%s_mean', label)) = mean(obsRows(1, idx));
    row.(sprintf('obs_vpos_%s_mean', label)) = mean(obsRows(2, idx));
    row.(sprintf('obs_vneg_%s_mean', label)) = mean(obsRows(3, idx));
    row.(sprintf('obs_vdcpu_%s_mean', label)) = mean(obsRows(4, idx));
    row.(sprintf('obs_fault_flag_%s_mean', label)) = mean(obsRows(17, idx));
    row.(sprintf('obs_recovery_flag_%s_mean', label)) = mean(obsRows(18, idx));
end

function tf = faults_have_phase_vector(faults)
    tf = false;
    if size(faults, 2) < 4
        return;
    end
    for k = 1:size(faults, 1)
        if ~isempty(faults{k, 4})
            tf = true;
            return;
        end
    end
end

function phasePu = fault_phase_pu(faults, rowIdx, faultPu)
    phasePu = [faultPu, faultPu, faultPu];
    if size(faults, 2) < 4 || isempty(faults{rowIdx, 4})
        return;
    end
    phasePu = double(faults{rowIdx, 4});
    phasePu = phasePu(:)';
    assert(numel(phasePu) == 3, ...
        'Fault phase multiplier must be [puA puB puC]');
    assert(all(isfinite(phasePu)) && all(phasePu > 0), ...
        'Fault phase multipliers must be positive finite values');
end

function tf = is_unbalanced_fault(faultPhasePu, faultPu)
    phasePu = double(faultPhasePu(:)');
    tf = numel(phasePu) == 3 && max(abs(phasePu - double(faultPu))) > 1e-9;
end

function [vPosPu, vNegPu] = sequence_voltage_pu(gridVRows, t, idx, basePhaseRms, f0)
    vPosPu = NaN;
    vNegPu = NaN;
    if ~any(idx)
        return;
    end
    tt = t(idx);
    if numel(tt) < 16
        return;
    end
    ref = exp(-1j * 2*pi*f0 * tt(:));
    va = gridVRows(1, idx)';
    vb = gridVRows(2, idx)';
    vc = gridVRows(3, idx)';
    Va = sqrt(2) * mean(va .* ref);
    Vb = sqrt(2) * mean(vb .* ref);
    Vc = sqrt(2) * mean(vc .* ref);
    a = exp(1j * 2*pi/3);
    Vpos = (Va + a*Vb + a^2*Vc) / 3;
    Vneg = (Va + a^2*Vb + a*Vc) / 3;
    vPosPu = abs(Vpos) / basePhaseRms;
    vNegPu = abs(Vneg) / basePhaseRms;
end

function replace_grid_with_controlled_phase_source(M, sourceBranch, nominalGridVoltage, ...
    phasePu, faultStart, faultClear)

    grid = [M '/Grid'];
    pos = get_param(grid, 'Position');
    delete_block(grid);

    x0 = pos(1);
    y0 = pos(2);
    add_block('simulink/Sources/Clock', [M '/GridFaultClock'], ...
        'Position', [x0-120 y0-80 x0-90 y0-60]);
    add_block('simulink/Sources/Constant', [M '/GridFaultVline'], ...
        'Position', [x0-125 y0-45 x0-85 y0-25], ...
        'Value', sprintf('%.12g', nominalGridVoltage));
    add_block('simulink/Sources/Constant', [M '/GridFaultF0'], ...
        'Position', [x0-125 y0-15 x0-85 y0+5], ...
        'Value', '50');
    add_block('simulink/Sources/Constant', [M '/GridFaultStart'], ...
        'Position', [x0-125 y0+15 x0-85 y0+35], ...
        'Value', sprintf('%.12g', faultStart));
    add_block('simulink/Sources/Constant', [M '/GridFaultClear'], ...
        'Position', [x0-125 y0+45 x0-85 y0+65], ...
        'Value', sprintf('%.12g', faultClear));
    add_block('simulink/Sources/Constant', [M '/GridFaultPuAbc'], ...
        'Position', [x0-125 y0+75 x0-85 y0+95], ...
        'Value', mat2str(phasePu, 12));

    wav = [M '/GridFaultWaveform'];
    add_block('simulink/User-Defined Functions/MATLAB Function', wav, ...
        'Position', [x0-45 y0-70 x0+55 y0+70]);
    set_matlab_function_script(wav, controlled_phase_waveform_code());
    add_block('simulink/Signal Routing/Demux', [M '/GridFaultDemux'], ...
        'Position', [x0+95 y0-35 x0+100 y0+65], 'Outputs', '3');
    add_block('simulink/Sinks/To Workspace', [M '/Vgrid_cmd_abc'], ...
        'Position', [x0+80 y0-100 x0+165 y0-76], ...
        'VariableName', 'Vgrid_cmd_abc', 'SaveFormat', 'StructureWithTime');

    add_line(M, 'GridFaultClock/1', 'GridFaultWaveform/1', 'autorouting', 'on');
    add_line(M, 'GridFaultVline/1', 'GridFaultWaveform/2', 'autorouting', 'on');
    add_line(M, 'GridFaultF0/1', 'GridFaultWaveform/3', 'autorouting', 'on');
    add_line(M, 'GridFaultStart/1', 'GridFaultWaveform/4', 'autorouting', 'on');
    add_line(M, 'GridFaultClear/1', 'GridFaultWaveform/5', 'autorouting', 'on');
    add_line(M, 'GridFaultPuAbc/1', 'GridFaultWaveform/6', 'autorouting', 'on');
    add_line(M, 'GridFaultWaveform/1', 'GridFaultDemux/1', 'autorouting', 'on');
    add_line(M, 'GridFaultWaveform/1', 'Vgrid_cmd_abc/1', 'autorouting', 'on');

    phaseNames = {'A', 'B', 'C'};
    for k = 1:3
        y = y0 - 30 + (k-1) * 55;
        src = [M '/Grid_' phaseNames{k} '_CVS'];
        gnd = [M '/Grid_' phaseNames{k} '_Ground'];
        add_block('powerlib/Electrical Sources/Controlled Voltage Source', src, ...
            'Position', [x0+145 y x0+205 y+38]);
        add_block('powerlib/Elements/Ground', gnd, ...
            'Position', [x0+145 y+48 x0+175 y+78]);
        add_line(M, sprintf('GridFaultDemux/%d', k), ...
            sprintf('Grid_%s_CVS/1', phaseNames{k}), 'autorouting', 'on');
        connect_replace(M, ph(src, 'RConn', 1), ...
            ph([M '/' sourceBranch], 'LConn', k));
        connect_if_free(M, ph(src, 'LConn', 1), ph(gnd, 'LConn', 1));
    end

    configure_controlled_phase_grid(M, nominalGridVoltage, phasePu, faultStart, faultClear);
end

function configure_controlled_phase_grid(M, nominalGridVoltage, phasePu, faultStart, faultClear)
    set_param([M '/GridFaultVline'], 'Value', sprintf('%.12g', nominalGridVoltage));
    set_param([M '/GridFaultF0'], 'Value', '50');
    set_param([M '/GridFaultStart'], 'Value', sprintf('%.12g', faultStart));
    set_param([M '/GridFaultClear'], 'Value', sprintf('%.12g', faultClear));
    set_param([M '/GridFaultPuAbc'], 'Value', mat2str(double(phasePu(:)'), 12));
end

function set_matlab_function_script(blockPath, codeText)
    rt = sfroot;
    chart = rt.find('-isa', 'Stateflow.EMChart', 'Path', blockPath);
    chart.Script = codeText;
end

function codeText = controlled_phase_waveform_code()
    lines = {
        'function vabc = fcn(t, vline, f0, faultStart, faultClear, phasePu)'
        '%#codegen'
        'vabc = zeros(3,1);'
        'pu = reshape(phasePu, 3, 1);'
        'if ~(t >= faultStart && t <= faultClear)'
        '    pu(:) = 1.0;'
        'end'
        'vpk = sqrt(2) * vline / sqrt(3);'
        'theta = 2*pi*f0*t;'
        'vabc(1) = vpk * pu(1) * sin(theta);'
        'vabc(2) = vpk * pu(2) * sin(theta - 2*pi/3);'
        'vabc(3) = vpk * pu(3) * sin(theta + 2*pi/3);'
        'end'
    };
    codeText = strjoin(lines, newline);
end

function replace_grid_with_programmable_source(M, sourceBranch, nominalGridVoltage, ...
    faultPu, faultStart, faultClear, stopTime)

    grid = [M '/Grid'];
    pos = get_param(grid, 'Position');
    delete_block(grid);
    add_block('powerlib/Electrical Sources/Three-Phase Programmable Voltage Source', ...
        grid, 'Position', pos);
    configure_programmable_grid(M, nominalGridVoltage, faultPu, faultStart, ...
        faultClear, stopTime);
    for k = 1:3
        connect_if_free(M, ph(grid, 'RConn', k), ...
            ph([M '/' sourceBranch], 'LConn', k));
    end
end

function configure_programmable_grid(M, nominalGridVoltage, faultPu, faultStart, ...
    faultClear, stopTime)

    grid = [M '/Grid'];
    t1 = max(0.0, faultStart - 1e-4);
    t2 = faultStart;
    t3 = faultClear;
    t4 = min(stopTime, faultClear + 1e-4);
    set_param(grid, ...
        'PositiveSequence', sprintf('[%.12g 0 50]', nominalGridVoltage), ...
        'VariationEntity', 'Amplitude', ...
        'VariationType', 'Table of time-amplitude pairs', ...
        'TimeValues', sprintf('[0 %.12g %.12g %.12g %.12g %.12g]', ...
            t1, t2, t3, t4, stopTime), ...
        'Amplitudes', sprintf('[1 1 %.12g %.12g 1 1]', faultPu, faultPu));
end

function p = ph(blockPath, portKind, idx)
    phs = get_param(blockPath, 'PortHandles');
    p = phs.(portKind)(idx);
end

function connect_if_free(M, srcPort, dstPort)
    dstLine = get_param(dstPort, 'Line');
    if isequal(dstLine, -1)
        add_line(M, srcPort, dstPort, 'autorouting', 'on');
    end
end

function connect_replace(M, srcPort, dstPort)
    dstLine = get_param(dstPort, 'Line');
    if ~isequal(dstLine, -1)
        delete_line(dstLine);
    end
    add_line(M, srcPort, dstPort, 'autorouting', 'on');
end

function tf = has_logged_var(out, name)
    names = who(out);
    tf = any(strcmp(names, name));
end

function [rows, t] = orient_logged_rows_with_time(x, nChannels, Ts)
    if isstruct(x) && isfield(x, 'time') && isfield(x, 'signals')
        t = x.time(:);
        values = x.signals.values;
        rows = orient_channels(values, nChannels);
        n = min(numel(t), size(rows, 2));
        t = t(1:n);
        rows = rows(:, 1:n);
        return;
    end
    rows = orient_channels(x, nChannels);
    t = (0:size(rows, 2)-1)' * Ts;
end

function y = orient_channels(x, nChannels)
    x = squeeze(x);
    if size(x, 1) == nChannels
        y = reshape(x, nChannels, []);
    elseif size(x, 2) == nChannels
        y = x';
    else
        y = reshape(x, nChannels, []);
    end
end
