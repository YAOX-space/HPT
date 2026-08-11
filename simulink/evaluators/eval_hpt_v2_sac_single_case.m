% eval_hpt_v2_sac_single_case
% Single-case raw SAC switch-level diagnostic.
%
% Workspace overrides:
%   hpt_eval_topology       "topology1" | "topology2" | "all"
%   hpt_eval_scenario_type  "steady" | "fault" | "all"
%   hpt_eval_case_name      e.g. "grid_10000V", "sag_0p90", "all"
%   hpt_eval_fault_phase_pu optional [puA puB puC] for unbalanced faults
%
% The evaluator uses the same raw SAC controller interface as the canonical
% control-comparison evaluator, but it runs only the requested case.

clearvars -except hpt_eval_topology hpt_eval_scenario_type hpt_eval_case_name hpt_eval_energy_enable hpt_eval_fault_phase_pu;
close all;

if ~exist('hpt_eval_topology', 'var')
    hpt_eval_topology = "all";
end
if ~exist('hpt_eval_scenario_type', 'var')
    hpt_eval_scenario_type = "all";
end
if ~exist('hpt_eval_case_name', 'var')
    hpt_eval_case_name = "all";
end
if ~exist('hpt_eval_energy_enable', 'var')
    hpt_eval_energy_enable = 1.0;
end
if ~exist('hpt_eval_fault_phase_pu', 'var')
    hpt_eval_fault_phase_pu = [];
end
hpt_eval_topology = string(hpt_eval_topology);
hpt_eval_scenario_type = string(hpt_eval_scenario_type);
hpt_eval_case_name = string(hpt_eval_case_name);

rootDir = fileparts(fileparts(mfilename('fullpath')));
actorFile = fullfile(rootDir, 'hpt_sac_actor_weights.mat');
dynamicActorFile = fullfile(rootDir, 'hpt_sac_actor_weights_dynamic.mat');
assert(exist(actorFile, 'file') == 2, 'Missing HPT SAC actor: %s', actorFile);
assert(exist(dynamicActorFile, 'file') == 2, ...
    'Missing dynamic HPT SAC actor: %s', dynamicActorFile);
actor = load(actorFile, 'n_obs', 'n_act');
assert(double(actor.n_obs) == 24 && double(actor.n_act) == 4, ...
    'HPT SAC actor must be 24/4, got %.0f/%.0f', double(actor.n_obs), double(actor.n_act));

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

targetPhaseRms = 207.0;
nominalGridVoltage = 10000;
steadyStopTime = 0.08;
steadySettleStart = 0.05;
faultStart = 0.035;
faultClear = 0.095;
faultStopTime = 0.22;
Ts = 20e-6;

oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));
rowCells = {};
traceCells = {};

for c = 1:size(cases, 1)
    topology = string(cases{c, 4});
    if hpt_eval_topology ~= "all" && topology ~= hpt_eval_topology
        continue;
    end

    cd(cases{c, 1});
    feval(cases{c, 2});
    M = cases{c, 3};
    sourceBranch = cases{c, 5};

    if hpt_eval_scenario_type == "all" || hpt_eval_scenario_type == "steady"
        for k = 1:numel(steadyGridVoltages)
            caseName = string(sprintf("grid_%.0fV", steadyGridVoltages(k)));
            if hpt_eval_case_name ~= "all" && caseName ~= hpt_eval_case_name
                continue;
            end
            [row, traceRows] = run_steady_case(M, topology, ...
                "sac_actor_raw_guard0", steadyGridVoltages(k), 1.0, ...
                targetPhaseRms, steadyStopTime, steadySettleStart, Ts, ...
                cases(c, :), hpt_eval_energy_enable);
            rowCells{end+1} = row; %#ok<SAGROW>
            traceCells = [traceCells, traceRows]; %#ok<AGROW>
        end
    end
    close_system(M, 0);

    if hpt_eval_scenario_type == "all" || hpt_eval_scenario_type == "fault"
        feval(cases{c, 2});
        M = cases{c, 3};
        gridSourceMode = "";

        for f = 1:size(faults, 1)
            faultName = string(faults{f, 1});
            if hpt_eval_case_name ~= "all" && faultName ~= hpt_eval_case_name
                continue;
            end
            faultPu = faults{f, 2};
            faultPhasePu = fault_phase_pu(faultPu, hpt_eval_fault_phase_pu);
            if gridSourceMode == ""
                if is_unbalanced_fault(faultPhasePu, faultPu)
                    replace_grid_with_controlled_phase_source(M, sourceBranch, ...
                        nominalGridVoltage, faultPhasePu, faultStart, faultClear);
                    gridSourceMode = "controlled_phase";
                else
                    replace_grid_with_programmable_source(M, sourceBranch, nominalGridVoltage, ...
                        faultPu, faultStart, faultClear, faultStopTime);
                    gridSourceMode = "programmable";
                end
            elseif gridSourceMode == "controlled_phase"
                configure_controlled_phase_grid(M, nominalGridVoltage, faultPhasePu, ...
                    faultStart, faultClear);
            else
                configure_programmable_grid(M, nominalGridVoltage, faultPu, ...
                    faultStart, faultClear, faultStopTime);
            end
            [row, traceRows] = run_fault_case(M, topology, faultName, faultPu, ...
                "sac_actor_raw_guard0", 1.0, targetPhaseRms, faultStopTime, Ts, ...
                faultStart, faultClear, cases(c, :), hpt_eval_energy_enable);
            rowCells{end+1} = row; %#ok<SAGROW>
            traceCells = [traceCells, traceRows]; %#ok<AGROW>
        end
        close_system(M, 0);
    end
end

assert(~isempty(rowCells), 'No cases matched topology=%s scenario=%s case=%s', ...
    hpt_eval_topology, hpt_eval_scenario_type, hpt_eval_case_name);

rows = [rowCells{:}];
outDir = fullfile(rootDir, '..', '..', 'lab', 'results', ...
    'hpt_v2_sac_single_case');
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
safeName = regexprep(sprintf('%s_%s_%s', hpt_eval_topology, ...
    hpt_eval_scenario_type, hpt_eval_case_name), '[^A-Za-z0-9_]+', '_');
outMat = fullfile(outDir, ['single_case_' char(safeName) '_' stamp '.mat']);
outCsv = fullfile(outDir, ['single_case_' char(safeName) '_' stamp '.csv']);
traceDir = fullfile(rootDir, '..', '..', 'lab', 'results', ...
    'hpt_v2_sac_single_case_actor_traces');
if exist(traceDir, 'dir') ~= 7
    mkdir(traceDir);
end
traceCsv = fullfile(traceDir, ['single_actor_trace_' char(safeName) '_' stamp '.csv']);
save(outMat, 'rows', 'traceCells', 'targetPhaseRms', 'hpt_eval_topology', ...
    'hpt_eval_scenario_type', 'hpt_eval_case_name');
writetable(struct2table(rows), outCsv);
if ~isempty(traceCells)
    write_trace_csv(traceCsv, traceCells);
end

fprintf('Single-case raw SAC guard=0 diagnostic complete.\n');
for i = 1:numel(rows)
    fprintf('%-10s %-8s %-11s %10.3f %10.3f %9.3f %9.3f %-8s %s\n', ...
        rows(i).topology, rows(i).scenario_type, rows(i).case_name, ...
        rows(i).lv_mean, rows(i).lv_recovery_mean, rows(i).vdc_min, ...
        rows(i).action_max_abs, string(rows(i).within_window), rows(i).window_reason);
end
fprintf('Saved CSV: %s\n', outCsv);
fprintf('Saved actor trace CSV: %s\n', traceCsv);

function [row, traceRows] = run_steady_case(M, topology, mode, gridVoltage, sacEnable, ...
    targetPhaseRms, stopTime, settleStart, Ts, caseSpec, energyEnable)

    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    in = in.setBlockParameter([M '/Grid'], 'Voltage', num2str(gridVoltage));
    in = set_common_sac_variables(in, M, sacEnable, energyEnable, 1.0, 0.0, targetPhaseRms);
    out = sim(in);

    Vlv = out.get('Vlv_abc');
    Vdc = out.get('Vdc');
    obs = out.get('HPTSAC_obs');
    act = out.get('HPTSAC_action');
    t = (0:size(Vlv, 1)-1)' * Ts;
    idx = t > settleStart;
    phaseRms = sqrt(mean(Vlv(idx, 1:3).^2, 1));
    obsRows = orient_channels(obs, 24);
    actRows = orient_channels(act, 4);

    row = base_row(M, topology, "steady", sprintf("grid_%.0fV", gridVoltage), ...
        mode, gridVoltage, NaN);
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
    row.action_max_abs = max(abs(actRows), [], 'all');
    row.reg_d_mean = mean(actRows(1, round(end*0.7):end));
    row.reg_q_mean = mean(actRows(2, round(end*0.7):end));
    row.energy_d_mean = mean(actRows(3, round(end*0.7):end));
    row.energy_q_mean = mean(actRows(4, round(end*0.7):end));
    row.obs_vpu_mean = mean(obsRows(1, round(end*0.7):end));
    row.obs_vpos_mean = mean(obsRows(2, round(end*0.7):end));
    row.obs_vdcpu_mean = mean(obsRows(4, round(end*0.7):end));
    row.obs_verr_mean = mean(obsRows(6, round(end*0.7):end));
    row.obs_fault_flag_mean = mean(obsRows(17, round(end*0.7):end));
    row.obs_recovery_flag_mean = mean(obsRows(18, round(end*0.7):end));
    row.gbt_reactive_status = "not_applicable_steady";
    row.gbt_limit_status = "action_surrogate";

    [row.within_window, row.window_reason] = assess_steady(row, caseSpec);
    traceRows = make_trace_rows(M, topology, "steady", row.case_name, gridVoltage, ...
        NaN, gridVoltage/10000.0, Vlv, Vdc, obsRows, actRows, Ts, ...
        targetPhaseRms, caseSpec, 0.035, 0.095, stopTime);
end

function [row, traceRows] = run_fault_case(M, topology, faultName, faultPu, mode, sacEnable, ...
    targetPhaseRms, stopTime, Ts, faultStart, faultClear, caseSpec, energyEnable)

    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    in = set_common_sac_variables(in, M, sacEnable, energyEnable, 1.0, ...
        double(sacEnable > 0.5) * 2.0, targetPhaseRms);
    out = sim(in);

    Vlv = out.get('Vlv_abc');
    Vdc = out.get('Vdc');
    if string(topology) == "topology1"
        Vgrid = out.get('Vmv_abc');
    else
        Vgrid = out.get('Vpri_abc');
    end
    Igrid = out.get('Igrid_abc');
    obs = out.get('HPTSAC_obs');
    act = out.get('HPTSAC_action');
    t = (0:size(Vlv, 1)-1)' * Ts;
    phaseRmsInst = sqrt(mean(Vlv(:, 1:3).^2, 2));
    faultIdx = t > (faultStart + 0.025) & t < (faultClear - 0.005);
    recoveryIdx = t > (faultClear + 0.035) & t < (stopTime - 0.005);
    obsRows = orient_channels(obs, 24);
    actRows = orient_channels(act, 4);
    gridVRows = orient_channels(Vgrid, 3);
    gridIRows = orient_channels(Igrid, 3);

    row = base_row(M, topology, "fault", faultName, mode, NaN, faultPu);
    row.lv_mean = mean(phaseRmsInst(faultIdx));
    row.lv_a = NaN;
    row.lv_b = NaN;
    row.lv_c = NaN;
    row.lv_unbalance = NaN;
    row.lv_recovery_mean = mean(phaseRmsInst(recoveryIdx));
    row.lv_peak = max(phaseRmsInst(t > faultStart & t < stopTime));
    row.lv_min = min(phaseRmsInst(t > faultStart & t < stopTime));
    row.vdc_mean = mean(Vdc(round(end*0.7):end, 1));
    row.vdc_min = min(Vdc(:, 1));
    row.vdc_max = max(Vdc(:, 1));
    row.action_max_abs = max(abs(actRows), [], 'all');
    row.reg_d_mean = mean(actRows(1, round(end*0.7):end));
    row.reg_q_mean = mean(actRows(2, round(end*0.7):end));
    row.energy_d_mean = mean(actRows(3, round(end*0.7):end));
    row.energy_q_mean = mean(actRows(4, round(end*0.7):end));
    row.obs_vpu_mean = mean(obsRows(1, round(end*0.7):end));
    row.obs_vpos_mean = mean(obsRows(2, round(end*0.7):end));
    row.obs_vdcpu_mean = mean(obsRows(4, round(end*0.7):end));
    row.obs_verr_mean = mean(obsRows(6, round(end*0.7):end));
    row.obs_fault_flag_mean = mean(obsRows(17, round(end*0.7):end));
    row.obs_recovery_flag_mean = mean(obsRows(18, round(end*0.7):end));
    row = add_gbt_fault_metrics(row, phaseRmsInst, Vdc(:, 1), actRows, ...
        gridVRows, gridIRows, t, targetPhaseRms, faultPu, faultStart, ...
        faultClear, stopTime);

    [row.within_window, row.window_reason] = assess_fault(row, caseSpec);
    traceRows = make_trace_rows(M, topology, "fault", row.case_name, NaN, ...
        faultPu, faultPu, Vlv, Vdc, obsRows, actRows, Ts, targetPhaseRms, ...
        caseSpec, faultStart, faultClear, stopTime);
end

function traceRows = make_trace_rows(M, topology, scenarioType, caseName, ...
    gridVoltage, faultPu, gridPu, Vlv, Vdc, obsRows, actRows, Ts, ...
    targetPhaseRms, caseSpec, faultStart, faultClear, stopTime)

    n = min([size(obsRows, 2), size(actRows, 2), size(Vlv, 1), size(Vdc, 1)]);
    t = (0:n-1) * Ts;
    sampleStride = 100;
    sampleIdx = 1:sampleStride:n;
    traceRows = {};
    for kk = 1:numel(sampleIdx)
        j = sampleIdx(kk);
        lvInst = sqrt(mean(Vlv(j, 1:3).^2));
        vdcInst = Vdc(j, 1);
        [zone, windowOk, windowReason] = classify_window( ...
            scenarioType, t(j), lvInst, vdcInst, faultPu, targetPhaseRms, ...
            faultStart, faultClear, stopTime, caseSpec);
        target = dagger_target(topology, scenarioType, obsRows(:, j), actRows(:, j));

        row = struct();
        row.model = string(M);
        row.topology = string(topology);
        row.scenario_type = string(scenarioType);
        row.condition_class = condition_class(scenarioType, faultPu);
        row.case_name = string(caseName);
        row.t = t(j);
        row.window_zone = string(zone);
        row.window_ok = double(windowOk);
        row.window_reason = string(windowReason);
        row.grid_V = gridVoltage;
        row.fault_pu = faultPu;
        row.grid_pu = gridPu;
        row.lv_rms_inst = lvInst;
        row.vdc_inst = vdcInst;
        for ii = 1:24
            row.(sprintf('obs_%02d', ii)) = obsRows(ii, j);
        end
        for ii = 1:4
            row.(sprintf('action_%02d', ii)) = target(ii);
            row.(sprintf('actor_action_%02d', ii)) = actRows(ii, j);
        end
        traceRows{end+1} = row; %#ok<AGROW>
    end
end

function target = dagger_target(topology, scenarioType, obs, act)
    vpu = obs(1);
    vpos = obs(2);
    vdcpu = obs(4);
    target = zeros(4, 1);
    if scenarioType == "steady"
        if topology == "topology1"
            % Topology1 fixed-action sweep shows raw m_reg_d near 0.8 can
            % hold grid_9000V, but high measured vpu or low Vdc must pull it down.
            target(1) = 0.80 + 6.0 * (1.0 - vpu);
            target(1) = min(max(target(1), 0.0), 0.80);
        else
            target(1) = min(max(1.8 * (1.0 - vpu), -0.60), 0.60);
        end
    else
        target(1) = min(max(20.0 * (1.0 - vpu), -0.60), 0.60);
        if vpos < 0.92 && target(1) < 0
            target(1) = 0;
        elseif vpos > 1.08 && target(1) > 0
            target(1) = 0;
        end
    end
    if vdcpu < 0.95
        dcScale = min(max((vdcpu - 0.70) / 0.25, 0.0), 1.0);
        target(1) = target(1) * dcScale;
    end
    target(2) = 0.0;
    target(3) = 0.0;
    target(4) = 0.0;
    for ii = 1:4
        if ~isfinite(target(ii))
            target(ii) = act(ii);
        end
    end
end

function c = condition_class(scenarioType, faultPu)
    if scenarioType == "steady" || ~isfinite(faultPu)
        c = "steady";
    elseif faultPu < 0.80
        c = "deep_lvrt";
    elseif faultPu < 1.0
        c = "shallow_lvrt";
    elseif faultPu <= 1.20
        c = "shallow_hvrt";
    else
        c = "high_hvrt";
    end
end

function row = add_gbt_fault_metrics(row, lvRmsInst, vdc, actRows, ...
    gridVRows, gridIRows, t, targetPhaseRms, faultPu, faultStart, ...
    faultClear, stopTime)

    solverTol = 1e-3;
    vdcBase = 800.0;
    lvPu = lvRmsInst ./ targetPhaseRms;
    tRel = t - faultStart;
    assessIdx = t >= faultStart & t <= stopTime;
    if faultPu < 1.0
        row.gbt_category = "LVRT";
        env = arrayfun(@(x) lvrt_lower_env(x, faultPu), tRel);
        margin = lvPu - env;
    else
        row.gbt_category = "HVRT";
        env = arrayfun(@hvrt_upper_env, tRel);
        margin = env - lvPu;
    end

    row.gbt_voltage_margin_min = min(margin(assessIdx));
    row.gbt_voltage_envelope_pass = row.gbt_voltage_margin_min >= -solverTol;
    row.gbt_recover_cover_s = stopTime - faultClear;
    row.gbt_recover_evaluated = row.gbt_recover_cover_s >= 0.10;
    postIdx = t > faultClear;
    if row.gbt_recover_evaluated && any(postIdx)
        finalStart = max(faultClear, stopTime - 0.12);
        finalIdx = t >= finalStart & t <= stopTime;
        row.gbt_recover_final_dev = max(abs(lvPu(finalIdx) - 1.0));
        row.gbt_recover_pass = row.gbt_recover_final_dev <= 0.07 && ...
            min(margin(postIdx)) >= -solverTol;
    else
        row.gbt_recover_final_dev = NaN;
        row.gbt_recover_pass = false;
    end

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
    row.gbt_certifiable = row.gbt_reactive_evaluated && ...
        row.gbt_grid_current_limit_pass;
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

function [zone, ok, reason] = classify_window( ...
    scenarioType, t, lvInst, vdcInst, faultPu, targetPhaseRms, ...
    faultStart, faultClear, stopTime, caseSpec)

    reason = "";
    ok = true;
    if scenarioType == "steady"
        if t <= 0.05
            zone = "startup";
            return;
        end
        zone = "steady";
        lvLo = caseSpec{6};
        lvHi = caseSpec{7};
        vdcLo = caseSpec{9};
        vdcHi = caseSpec{10};
        if lvInst < lvLo || lvInst > lvHi
            ok = false;
            reason = append_reason(reason, "steady_lv_inst");
        end
        if vdcInst < vdcLo || vdcInst > vdcHi
            ok = false;
            reason = append_reason(reason, "steady_vdc_inst");
        end
        return;
    end

    if t < faultStart
        zone = "prefault";
    elseif t < faultClear
        zone = "fault";
    elseif t < stopTime - 0.005
        zone = "recovery";
    else
        zone = "tail";
    end
    if t >= faultStart
        lvPu = lvInst / targetPhaseRms;
        tRel = t - faultStart;
        if faultPu < 1.0
            env = lvrt_lower_env(tRel, faultPu);
            if lvPu < env - 1e-3
                ok = false;
                reason = append_reason(reason, "gbt_lvrt_envelope_inst");
            end
        else
            env = hvrt_upper_env(tRel);
            if lvPu > env + 1e-3
                ok = false;
                reason = append_reason(reason, "gbt_hvrt_envelope_inst");
            end
        end
    end
    vdcPu = vdcInst / 800.0;
    if vdcPu < 0.75 || vdcPu > 1.25
        ok = false;
        reason = append_reason(reason, "gbt_vdc_survive_inst");
    end
end

function reason = append_reason(reason, token)
    if strlength(string(reason)) == 0
        reason = token;
    else
        reason = reason + ";" + token;
    end
end

function in = set_common_sac_variables(in, M, sacEnable, energyEnable, policyMode, ...
    actorSelectMode, targetPhaseRms)

    in = in.setVariable('hpt_sac_enable', sacEnable, 'Workspace', M);
    in = in.setVariable('hpt_sac_energy_enable', energyEnable, 'Workspace', M);
    in = in.setVariable('hpt_sac_policy_mode', policyMode, 'Workspace', M);
    in = in.setVariable('hpt_sac_actor_select_mode', actorSelectMode, ...
        'Workspace', M);
    in = in.setVariable('hpt_sac_guard_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
end

function row = base_row(M, topology, scenarioType, caseName, mode, gridVoltage, faultPu)
    row = struct();
    row.model = string(M);
    row.topology = string(topology);
    row.scenario_type = string(scenarioType);
    row.case_name = string(caseName);
    row.mode = string(mode);
    row.guard_enable = 0.0;
    row.grid_V = gridVoltage;
    row.fault_pu = faultPu;
    row.lv_mean = NaN;
    row.lv_a = NaN;
    row.lv_b = NaN;
    row.lv_c = NaN;
    row.lv_unbalance = NaN;
    row.lv_recovery_mean = NaN;
    row.lv_peak = NaN;
    row.lv_min = NaN;
    row.vdc_mean = NaN;
    row.vdc_min = NaN;
    row.vdc_max = NaN;
    row.action_max_abs = NaN;
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
    row.gbt_category = "";
    row.gbt_voltage_margin_min = NaN;
    row.gbt_voltage_envelope_pass = false;
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
    row.gbt_reactive_status = "";
    row.gbt_reactive_pass = false;
    row.gbt_limit_status = "";
    row.gbt_certifiable = false;
    row.within_window = false;
    row.window_reason = "";
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

function [ok, reason] = assess_fault(row, caseSpec)
    reasons = strings(0, 1);
    if ~row.gbt_voltage_envelope_pass
        reasons(end+1) = "gbt_voltage_envelope"; %#ok<AGROW>
    end
    if ~row.gbt_recover_evaluated
        reasons(end+1) = "gbt_recover_not_evaluated"; %#ok<AGROW>
    elseif ~row.gbt_recover_pass
        reasons(end+1) = "gbt_recover"; %#ok<AGROW>
    end
    if ~row.gbt_vdc_survive_pass
        reasons(end+1) = "gbt_vdc_survive"; %#ok<AGROW>
    end
    if ~row.gbt_action_limit_pass
        reasons(end+1) = "action_limit"; %#ok<AGROW>
    end
    if ~row.gbt_grid_current_limit_pass
        reasons(end+1) = "grid_current_limit"; %#ok<AGROW>
    end
    if ~row.gbt_reactive_pass
        reasons(end+1) = string(row.gbt_reactive_status); %#ok<AGROW>
    end
    ok = isempty(reasons);
    reason = strjoin(reasons, ";");
end

function y = lvrt_lower_env(tRel, residual)
    if tRel < 0
        y = 0.9;
    elseif tRel <= 0.625
        y = max(0.20, residual);
    elseif tRel <= 2.0
        y = max(0.20, residual) + ...
            (0.9 - max(0.20, residual)) * (tRel - 0.625) / (2.0 - 0.625);
    else
        y = 0.9;
    end
end

function y = hvrt_upper_env(tRel)
    if tRel < 0
        y = 1.1;
    elseif tRel <= 0.5
        y = 1.30;
    elseif tRel <= 1.0
        y = 1.20;
    else
        y = 1.10;
    end
end

function phasePu = fault_phase_pu(faultPu, requestedPhasePu)
    phasePu = [faultPu, faultPu, faultPu];
    if isempty(requestedPhasePu)
        return;
    end
    phasePu = double(requestedPhasePu(:)');
    assert(numel(phasePu) == 3, ...
        'hpt_eval_fault_phase_pu must be [puA puB puC]');
    assert(all(isfinite(phasePu)) && all(phasePu > 0), ...
        'hpt_eval_fault_phase_pu values must be positive finite values');
end

function tf = is_unbalanced_fault(phasePu, faultPu)
    phasePu = double(phasePu(:)');
    tf = numel(phasePu) == 3 && max(abs(phasePu - double(faultPu))) > 1e-9;
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

    add_line(M, 'GridFaultClock/1', 'GridFaultWaveform/1', 'autorouting', 'on');
    add_line(M, 'GridFaultVline/1', 'GridFaultWaveform/2', 'autorouting', 'on');
    add_line(M, 'GridFaultF0/1', 'GridFaultWaveform/3', 'autorouting', 'on');
    add_line(M, 'GridFaultStart/1', 'GridFaultWaveform/4', 'autorouting', 'on');
    add_line(M, 'GridFaultClear/1', 'GridFaultWaveform/5', 'autorouting', 'on');
    add_line(M, 'GridFaultPuAbc/1', 'GridFaultWaveform/6', 'autorouting', 'on');
    add_line(M, 'GridFaultWaveform/1', 'GridFaultDemux/1', 'autorouting', 'on');

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

function write_trace_csv(path, rowCells)
    if isempty(rowCells)
        error('No trace rows to write.');
    end
    fields = fieldnames(rowCells{1});
    fid = fopen(path, 'w');
    cleaner = onCleanup(@() fclose(fid));
    for i = 1:numel(fields)
        if i > 1
            fprintf(fid, ',');
        end
        fprintf(fid, '%s', fields{i});
    end
    fprintf(fid, '\n');
    for r = 1:numel(rowCells)
        row = rowCells{r};
        for i = 1:numel(fields)
            if i > 1
                fprintf(fid, ',');
            end
            value = row.(fields{i});
            if isstring(value)
                fprintf(fid, '"%s"', char(value));
            elseif ischar(value)
                fprintf(fid, '"%s"', value);
            elseif isnumeric(value) || islogical(value)
                fprintf(fid, '%.15g', value);
            else
                fprintf(fid, '"%s"', char(string(value)));
            end
        end
        fprintf(fid, '\n');
    end
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

