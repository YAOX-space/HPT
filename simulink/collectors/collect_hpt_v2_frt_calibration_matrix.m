% collect_hpt_v2_frt_calibration_matrix
% Switch-level FRT calibration matrix for the version-2 HPT SAC proxy.
%
% Workspace overrides:
%   hpt_calib_mode       "pilot" | "full" | "holdout" | "edgeholdout" default: "full"
%   hpt_calib_topology   "topology1" | "topology2" | "all"
%   hpt_calib_fault_start optional fault start time, default 0.035 s
%   hpt_calib_fault_duration optional fault duration, default 0.060 s
%   hpt_calib_fault_stop_margin optional post-fault window, default 0.125 s
%   hpt_calib_fault_settle_s optional load-quality response window,
%                            default 0.0 s for strict assessment
%   hpt_calib_output_dir    optional explicit result directory
%
% The script records both aggregate metrics and 2-ms traces.  It uses fixed
% SAC commands so the averaged proxy can be calibrated against the physical
% switch-level response before scenario-specialist SAC training resumes.

clearvars -except hpt_calib_mode hpt_calib_topology hpt_calib_fault_start ...
    hpt_calib_fault_duration hpt_calib_fault_stop_margin hpt_calib_fault_settle_s ...
    hpt_calib_faults hpt_calib_output_dir;
close all;

if ~exist('hpt_calib_mode', 'var')
    hpt_calib_mode = "full";
end
if ~exist('hpt_calib_topology', 'var')
    hpt_calib_topology = "all";
end
if ~exist('hpt_calib_fault_start', 'var')
    hpt_calib_fault_start = 0.035;
end
if ~exist('hpt_calib_fault_duration', 'var')
    hpt_calib_fault_duration = 0.060;
end
if ~exist('hpt_calib_fault_stop_margin', 'var')
    hpt_calib_fault_stop_margin = 0.125;
end
if ~exist('hpt_calib_fault_settle_s', 'var')
    hpt_calib_fault_settle_s = 0.0;
end
hpt_calib_mode = string(hpt_calib_mode);
hpt_calib_topology = string(hpt_calib_topology);

rootDir = fileparts(fileparts(mfilename('fullpath')));
oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));
evaluatorDir = fullfile(rootDir, 'evaluators');
addpath(evaluatorDir);
pathCleanup = onCleanup(@() rmpath(evaluatorDir)); %#ok<NASGU>

cases = {
    fullfile(rootDir, 'topology1'), 'build_hpt_v2_1to1_switchlevel', 'hpt_v2_1to1_switchlevel', 'topology1', 'Zg';
    fullfile(rootDir, 'topology2'), 'build_hpt_v2_topology2_paper', 'hpt_v2_topology2_paper', 'topology2', 'Source_RL';
};

faults = {
    'sag_0p20',   0.20, 'LVRT';
    'sag_0p50',   0.50, 'LVRT';
    'sag_0p75',   0.75, 'LVRT';
    'sag_0p85',   0.85, 'LVRT';
    'sag_0p90',   0.90, 'LVRT';
    'swell_1p10', 1.10, 'HVRT';
    'swell_1p20', 1.20, 'HVRT';
    'swell_1p25', 1.25, 'HVRT';
    'swell_1p30', 1.30, 'HVRT';
};
customFaults = exist('hpt_calib_faults', 'var');
if customFaults
    faults = hpt_calib_faults;
end
usePhaseFaultSource = faults_have_phase_vector(faults);

targetPhaseRms = 207.0;
nominalGridVoltage = 10000;
faultStart = hpt_calib_fault_start;
faultClear = faultStart + hpt_calib_fault_duration;
stopTime = faultClear + hpt_calib_fault_stop_margin;
Ts = 20e-6;
sampleStride = 100;  % 2 ms, matching the Python SAC/proxy step.

if hpt_calib_mode == "pilot"
    regDValues = [-0.40, 0.00, 0.40];
    regQValues = 0.0;
    energyActions = [0.0, 0.0; 0.4, 0.0; 0.0, 0.2];
    jointEnergyValues = [0.0, 0.4];
    if ~customFaults
        faults = faults([5, 6], :);
    end
elseif hpt_calib_mode == "holdout"
    regDValues = [-0.70, -0.30, 0.30, 0.70];
    regQValues = 0.20;
    energyActions = [
        0.10, 0.00;
        0.30, 0.00;
        0.00, 0.10;
        0.30, 0.10
    ];
    jointEnergyValues = [0.10, 0.30];
    faults = {
        'sag_0p65',   0.65, 'LVRT';
        'swell_1p15', 1.15, 'HVRT';
    };
elseif hpt_calib_mode == "edgeholdout"
    regDValues = [-0.50, -0.10, 0.10, 0.50];
    regQValues = -0.20;
    energyActions = [
        0.15, 0.00;
        0.35, 0.00;
        0.00, 0.15;
        0.35, 0.15
    ];
    jointEnergyValues = [0.15, 0.35];
    faults = {
        'sag_0p575',    0.575, 'LVRT';
        'swell_1p175',  1.175, 'HVRT';
    };
else
    regDValues = [-0.80, -0.60, -0.40, -0.20, 0.00, 0.20, 0.40, 0.60, 0.80];
    regQValues = [-0.40, 0.00, 0.40];
    energyActions = [
        0.00,  0.00;
        0.20,  0.00;
       -0.20,  0.00;
        0.40,  0.00;
       -0.40,  0.00;
        0.00,  0.20;
        0.00, -0.20;
        0.20,  0.20;
        0.40,  0.20
    ];
    jointEnergyValues = [0.0, 0.2, 0.4];
end

rowCells = {};
traceCells = {};
for c = 1:size(cases, 1)
    topology = string(cases{c, 4});
    if hpt_calib_topology ~= "all" && topology ~= hpt_calib_topology
        continue;
    end

    cd(cases{c, 1});
    feval(cases{c, 2});
    M = cases{c, 3};
    sourceBranch = cases{c, 5};
    if usePhaseFaultSource
        replace_grid_with_controlled_phase_source(M, sourceBranch, ...
            nominalGridVoltage, [1.0, 1.0, 1.0], faultStart, faultClear);
    else
        replace_grid_with_programmable_source(M, sourceBranch);
    end

    for f = 1:size(faults, 1)
        faultName = string(faults{f, 1});
        faultPu = faults{f, 2};
        category = string(faults{f, 3});
        faultPhasePu = fault_phase_pu(faults, f, faultPu);

        rowCells{end+1} = run_fixed_case(M, topology, faultName, category, faultPu, ...
            "baseline", 0.0, 0.0, 0.0, 0.0, [0.0, 0.0], targetPhaseRms, ...
            nominalGridVoltage, faultStart, faultClear, stopTime, Ts, ...
            hpt_calib_fault_settle_s, faultPhasePu, usePhaseFaultSource); %#ok<SAGROW>
        traceCells = append_trace_cells(traceCells, rowCells{end}, sampleStride); %#ok<AGROW>

        for rd = 1:numel(regDValues)
            for rq = 1:numel(regQValues)
                rowCells{end+1} = run_fixed_case(M, topology, faultName, category, faultPu, ...
                    "reg_sweep", 1.0, 0.0, regDValues(rd), regQValues(rq), [0.0, 0.0], ...
                    targetPhaseRms, nominalGridVoltage, faultStart, faultClear, ...
                    stopTime, Ts, hpt_calib_fault_settle_s, faultPhasePu, ...
                    usePhaseFaultSource); %#ok<SAGROW>
                traceCells = append_trace_cells(traceCells, rowCells{end}, sampleStride); %#ok<AGROW>
            end
        end

        for ea = 1:size(energyActions, 1)
            rowCells{end+1} = run_fixed_case(M, topology, faultName, category, faultPu, ...
                "energy_sweep", 0.0, 1.0, 0.0, 0.0, energyActions(ea, :), ...
                targetPhaseRms, nominalGridVoltage, faultStart, faultClear, ...
                stopTime, Ts, hpt_calib_fault_settle_s, faultPhasePu, ...
                usePhaseFaultSource); %#ok<SAGROW>
            traceCells = append_trace_cells(traceCells, rowCells{end}, sampleStride); %#ok<AGROW>
        end

        if (hpt_calib_mode == "holdout" || hpt_calib_mode == "edgeholdout") && faultPu < 1.0
            jointRegValues = [0.30, 0.50];
        elseif hpt_calib_mode == "holdout" || hpt_calib_mode == "edgeholdout"
            jointRegValues = [-0.30, -0.50];
        elseif faultPu < 1.0
            jointRegValues = [0.20, 0.40, 0.60];
        else
            jointRegValues = [-0.20, -0.40, -0.60];
        end
        for rd = 1:numel(jointRegValues)
            for ed = 1:numel(jointEnergyValues)
                rowCells{end+1} = run_fixed_case(M, topology, faultName, category, faultPu, ...
                    "joint_sweep", 1.0, 1.0, jointRegValues(rd), 0.0, ...
                    [jointEnergyValues(ed), 0.0], targetPhaseRms, nominalGridVoltage, ...
                    faultStart, faultClear, stopTime, Ts, hpt_calib_fault_settle_s, ...
                    faultPhasePu, usePhaseFaultSource); %#ok<SAGROW>
                traceCells = append_trace_cells(traceCells, rowCells{end}, sampleStride); %#ok<AGROW>
            end
        end
    end
    if bdIsLoaded(M)
        set_param(M, 'Dirty', 'off');
        close_system(M, 0);
    end
end

aggregateCells = cell(size(rowCells));
for i = 1:numel(rowCells)
    aggregateCells{i} = strip_trace(rowCells{i});
end
rows = [aggregateCells{:}];
if exist('hpt_calib_output_dir', 'var') && strlength(string(hpt_calib_output_dir)) > 0
    outDir = char(hpt_calib_output_dir);
else
    outDir = fullfile(rootDir, '..', 'results', 'calibration', ...
        'hpt_v2_frt_calibration_matrix');
end
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
safeName = char(regexprep(sprintf('%s_%s', hpt_calib_mode, hpt_calib_topology), '[^A-Za-z0-9_]+', '_'));
outMat = fullfile(outDir, ['frt_calibration_matrix_' safeName '_' stamp '.mat']);
outCsv = fullfile(outDir, ['frt_calibration_matrix_' safeName '_' stamp '.csv']);
traceCsv = fullfile(outDir, ['frt_calibration_traces_' safeName '_' stamp '.csv']);
save(outMat, 'rows', 'traceCells', 'faults', 'targetPhaseRms', ...
    'nominalGridVoltage', 'faultStart', 'faultClear', 'stopTime', ...
    'Ts', 'sampleStride', 'hpt_calib_mode', 'hpt_calib_topology', ...
    'hpt_calib_fault_start', 'hpt_calib_fault_duration', ...
    'hpt_calib_fault_stop_margin', 'hpt_calib_fault_settle_s');
writetable(struct2table(rows), outCsv);
write_trace_csv(traceCsv, traceCells);

fprintf('HPT FRT calibration matrix complete.\n');
fprintf('Rows: %d, trace samples: %d\n', numel(rows), numel(traceCells));
fprintf('Saved aggregate CSV: %s\n', outCsv);
fprintf('Saved trace CSV: %s\n', traceCsv);

function row = run_fixed_case(M, topology, faultName, category, faultPu, mode, ...
    regEnable, energyEnable, mRegD, mRegQ, energyCmd, targetPhaseRms, ...
    nominalGridVoltage, faultStart, faultClear, stopTime, Ts, faultSettleS, ...
    faultPhasePu, usePhaseFaultSource)

    mEnergyD = energyCmd(1);
    mEnergyQ = energyCmd(2);
    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    if usePhaseFaultSource
        configure_controlled_phase_grid(M, nominalGridVoltage, faultPhasePu, ...
            faultStart, faultClear);
    else
        in = set_programmable_grid(in, M, nominalGridVoltage, faultPu, ...
            faultStart, faultClear, stopTime);
    end
    in = in.setVariable('hpt_sac_enable', regEnable, 'Workspace', M);
    in = in.setVariable('hpt_sac_energy_enable', energyEnable, 'Workspace', M);
    in = in.setVariable('hpt_sac_policy_mode', -1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_actor_select_mode', 2.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_guard_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_reg_d', mRegD, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_reg_q', mRegQ, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_energy_d', mEnergyD, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_energy_q', mEnergyQ, 'Workspace', M);
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

    obsRows = orient_channels(obs, 24);
    actRows = orient_channels(act, 4);
    mrefRows = orient_channels(mref, 6);
    mengRows = orient_channels(meng, 3);
    mregDbgRows = orient_channels(mregDbg, 7);
    energyDbgRows = orient_channels(energyDbg, 12);
    gridVRows = orient_channels(Vgrid, 3);
    gridIRows = orient_channels(Igrid, 3);
    energyVRows = orient_channels(Venergy, 3);
    iRows = orient_channels(Ienergy, 3);
    energyIdMax = getVariable(get_param(M, 'ModelWorkspace'), 'hpt_energy_id_max');
    measRows = measured_response_rows(actRows, mrefRows, mregDbgRows, ...
        energyDbgRows, energyVRows, iRows, energyIdMax);
    t = (0:size(Vlv, 1)-1)' * Ts;
    phaseRmsInst = sqrt(mean(Vlv(:, 1:3).^2, 2));
    faultIdx = t > (faultStart + 0.010) & t < (faultClear - 0.002);
    recoveryIdx = t > (faultClear + 0.035) & t < (stopTime - 0.005);
    activeIdx = t > faultStart & t < stopTime;
    tailStart = max(1, round(size(actRows, 2) * 0.7));
    phaseRmsFault = sqrt(mean(Vlv(faultIdx, 1:3).^2, 1));
    iRmsFault = sqrt(mean(iRows(:, faultIdx).^2, 2));

    row = struct();
    row.model = string(M);
    row.topology = string(topology);
    row.scenario_type = "fault";
    row.category = string(category);
    row.condition_class = lower(string(category));
    row.fault = string(faultName);
    row.case_name = string(faultName);
    row.fault_pu = faultPu;
    row.grid_pu = faultPu;
    row.fault_a_pu = faultPhasePu(1);
    row.fault_b_pu = faultPhasePu(2);
    row.fault_c_pu = faultPhasePu(3);
    row.mode = string(mode);
    row.target_phase_rms = targetPhaseRms;
    row.fault_start = faultStart;
    row.fault_clear = faultClear;
    row.stop_time = stopTime;
    row.fault_start_s = faultStart;
    row.fault_clear_s = faultClear;
    row.fault_duration_s = faultClear - faultStart;
    row.fault_settle_s = faultSettleS;
    row.stop_time_s = stopTime;
    row.raw_m_reg_d = mRegD;
    row.raw_m_reg_q = mRegQ;
    row.raw_m_energy_d = mEnergyD;
    row.raw_m_energy_q = mEnergyQ;
    row.reg_enable = regEnable;
    row.energy_enable = energyEnable;
    row.action_semantics = "fixed_frt_command_with_measured_response";
    row.validator_schema = "hpt-frt-gates-v3-gbt19963.1";
    row.action_raw_available = true;
    row.action_projected_available = true;
    row.action_effective_available = true;
    row.lv_fault_rms_mean = safe_mean(phaseRmsInst(faultIdx));
    row.lv_recovery_rms_mean = safe_mean(phaseRmsInst(recoveryIdx));
    row.lv_peak_rms = max(phaseRmsInst(activeIdx));
    row.lv_min_rms = min(phaseRmsInst(activeIdx));
    row.lv_pu_mean = row.lv_fault_rms_mean / targetPhaseRms;
    row.lv_recovery_pu_mean = row.lv_recovery_rms_mean / targetPhaseRms;
    row.lv_peak_pu = row.lv_peak_rms / targetPhaseRms;
    row.lv_min_pu = row.lv_min_rms / targetPhaseRms;
    row.lv_unbalance = max(phaseRmsFault) - min(phaseRmsFault);
    row.lv_unbalance_pu = row.lv_unbalance / targetPhaseRms;
    baseGridPhaseRms = nominalGridVoltage / sqrt(3);
    gridFaultIdx = t >= (faultStart + faultSettleS) & t <= faultClear;
    if any(gridFaultIdx)
        gridPhaseRms = sqrt(mean(gridVRows(:, gridFaultIdx).^2, 2));
        row.grid_va_fault_pu = gridPhaseRms(1) / baseGridPhaseRms;
        row.grid_vb_fault_pu = gridPhaseRms(2) / baseGridPhaseRms;
        row.grid_vc_fault_pu = gridPhaseRms(3) / baseGridPhaseRms;
        row.grid_vabc_unbalance_fault_pu = ...
            (max(gridPhaseRms) - min(gridPhaseRms)) / baseGridPhaseRms;
        [row.grid_vpos_seq_fault_pu, row.grid_vneg_seq_fault_pu] = ...
            sequence_voltage_pu(gridVRows, t, gridFaultIdx, baseGridPhaseRms, 50.0);
    else
        row.grid_va_fault_pu = NaN;
        row.grid_vb_fault_pu = NaN;
        row.grid_vc_fault_pu = NaN;
        row.grid_vabc_unbalance_fault_pu = NaN;
        row.grid_vpos_seq_fault_pu = NaN;
        row.grid_vneg_seq_fault_pu = NaN;
    end
    row = add_fault_quality_metrics(row, phaseRmsInst, gridVRows, t, ...
        targetPhaseRms, nominalGridVoltage, faultPu, faultPhasePu, ...
        faultStart, faultClear, stopTime, row.fault_settle_s);
    row.vdc_mean = safe_mean(Vdc(round(end*0.7):end, 1));
    row.vdc_min = min(Vdc(:, 1));
    row.vdc_max = max(Vdc(:, 1));
    row.vdc_pu_mean = row.vdc_mean / 800.0;
    row.vdc_min_pu = row.vdc_min / 800.0;
    row.vdc_max_pu = row.vdc_max / 800.0;
    row.energy_i_rms_mean = safe_mean(iRmsFault);
    row.cmd_action_max_abs = matrix_max_abs(actRows);
    row.bridge_modulation_abs_max = matrix_max_abs([mrefRows(:); mengRows(:)]);
    row.action_max_abs = row.bridge_modulation_abs_max;
    row.cmd_m_reg_d_mean = safe_mean(actRows(1, tailStart:end));
    row.cmd_m_reg_q_mean = safe_mean(actRows(2, tailStart:end));
    row.cmd_m_energy_d_mean = safe_mean(actRows(3, tailStart:end));
    row.cmd_m_energy_q_mean = safe_mean(actRows(4, tailStart:end));
    row.cmd_m_reg_d_fault_mean = window_row_mean(actRows, 1, gridFaultIdx);
    row.cmd_m_reg_q_fault_mean = window_row_mean(actRows, 2, gridFaultIdx);
    row.cmd_m_energy_d_fault_mean = window_row_mean(actRows, 3, gridFaultIdx);
    row.cmd_m_energy_q_fault_mean = window_row_mean(actRows, 4, gridFaultIdx);
    row.cmd_m_reg_d_recovery_mean = window_row_mean(actRows, 1, recoveryIdx);
    row.cmd_m_reg_q_recovery_mean = window_row_mean(actRows, 2, recoveryIdx);
    row.cmd_m_energy_d_recovery_mean = window_row_mean(actRows, 3, recoveryIdx);
    row.cmd_m_energy_q_recovery_mean = window_row_mean(actRows, 4, recoveryIdx);
    row.meas_reg_d_mean = tail_row_mean(measRows, 1);
    row.meas_reg_q_mean = tail_row_mean(measRows, 2);
    row.meas_energy_d_mean = tail_row_mean(measRows, 3);
    row.meas_energy_q_mean = tail_row_mean(measRows, 4);
    row.meas_reg_d_fault_mean = window_row_mean(measRows, 1, gridFaultIdx);
    row.meas_reg_q_fault_mean = window_row_mean(measRows, 2, gridFaultIdx);
    row.meas_energy_d_fault_mean = window_row_mean(measRows, 3, gridFaultIdx);
    row.meas_energy_q_fault_mean = window_row_mean(measRows, 4, gridFaultIdx);
    row.meas_reg_d_recovery_mean = window_row_mean(measRows, 1, recoveryIdx);
    row.meas_reg_q_recovery_mean = window_row_mean(measRows, 2, recoveryIdx);
    row.meas_energy_d_recovery_mean = window_row_mean(measRows, 3, recoveryIdx);
    row.meas_energy_q_recovery_mean = window_row_mean(measRows, 4, recoveryIdx);
    row.reg_d_mean = row.meas_reg_d_mean;
    row.reg_q_mean = row.meas_reg_q_mean;
    row.energy_d_mean = row.meas_energy_d_mean;
    row.energy_q_mean = row.meas_energy_q_mean;
    row = add_grid_current_metrics(row, gridVRows, gridIRows, t, ...
        faultStart, faultClear);
    row.simulation_completed = t(end) >= stopTime - 1.5 * Ts && ...
        all(isfinite(Vlv(:))) && all(isfinite(Vdc(:))) && ...
        all(isfinite(Igrid(:)));
    row.remained_connected_evaluated = false;
    row.remained_connected = false;
    row.remained_connected_evidence = ...
        "continuous_switch_level_run_no_explicit_trip_interface";
    row.equipment_safety_pass = row.vdc_min >= 650.0 && ...
        row.vdc_max <= 1000.0 && row.action_max_abs <= 0.9501 && ...
        row.gbt_grid_current_limit_pass;
    row.l1_load_voltage_survival_pass = row.load_quality_pass && ...
        row.equipment_safety_pass;
    row.l2_grid_code_ride_through_pass = row.l1_load_voltage_survival_pass && ...
        row.scenario_valid && row.remained_connected_evaluated && ...
        row.remained_connected;
    row.active_power_recovery_evaluated = false;
    row.active_power_recovery_pass = false;
    row.l3_full_frt_pass = false;
    row.obs_dim = size(obsRows, 1);
    row.action_dim = size(actRows, 1);
    row.trace_t = t;
    row.trace_vlv = phaseRmsInst;
    row.trace_vdc = Vdc(:, 1);
    row.trace_obs = obsRows;
    row.trace_act = actRows;
    row.trace_meas_act = measRows;
    row.trace_grid_vpos_pu = row.trace_grid_metrics.vpos_pu;
    row.trace_grid_vneg_seq_pu = zeros(size(t));
    row.trace_grid_vabc_unbalance_pu = zeros(size(t));
    row.trace_grid_vneg_seq_pu(gridFaultIdx) = row.grid_vneg_seq_fault_pu;
    row.trace_grid_vabc_unbalance_pu(gridFaultIdx) = row.grid_vabc_unbalance_fault_pu;
    row.trace_grid_iq_pu = row.trace_grid_metrics.iq_pu;
    row.trace_grid_iq_ref_pu = row.trace_grid_metrics.iq_ref_pu;
    row.trace_grid_i_peak_pu = row.trace_grid_metrics.i_peak_pu;
    row = rmfield(row, 'trace_grid_metrics');
end

function traceCells = append_trace_cells(traceCells, row, sampleStride)
    t = row.trace_t;
    n = numel(t);
    sampleIdx = 1:sampleStride:n;
    for kk = 1:numel(sampleIdx)
        j = sampleIdx(kk);
        tr = struct();
        tr.model = row.model;
        tr.topology = row.topology;
        tr.scenario_type = row.scenario_type;
        tr.category = row.category;
        tr.condition_class = row.condition_class;
        tr.fault = row.fault;
        tr.case_name = row.case_name;
        tr.mode = row.mode;
        tr.t = t(j);
        tr.fault_pu = row.fault_pu;
        tr.grid_pu = row.grid_pu;
        tr.fault_a_pu = row.fault_a_pu;
        tr.fault_b_pu = row.fault_b_pu;
        tr.fault_c_pu = row.fault_c_pu;
        tr.fault_start_s = row.fault_start_s;
        tr.fault_clear_s = row.fault_clear_s;
        tr.fault_duration_s = row.fault_duration_s;
        tr.fault_settle_s = row.fault_settle_s;
        tr.stop_time_s = row.stop_time_s;
        tr.raw_m_reg_d = row.raw_m_reg_d;
        tr.raw_m_reg_q = row.raw_m_reg_q;
        tr.raw_m_energy_d = row.raw_m_energy_d;
        tr.raw_m_energy_q = row.raw_m_energy_q;
        tr.lv_rms_inst = row.trace_vlv(j);
        tr.lv_pu_inst = row.trace_vlv(j) / row.target_phase_rms;
        tr.vdc_inst = row.trace_vdc(j);
        tr.vdc_pu_inst = row.trace_vdc(j) / 800.0;
        tr.grid_vpos_pu_inst = row.trace_grid_vpos_pu(j);
        tr.grid_vneg_seq_pu_inst = row.trace_grid_vneg_seq_pu(j);
        tr.grid_vabc_unbalance_pu_inst = row.trace_grid_vabc_unbalance_pu(j);
        tr.grid_iq_pu_inst = row.trace_grid_iq_pu(j);
        tr.grid_iq_ref_pu_inst = row.trace_grid_iq_ref_pu(j);
        tr.grid_i_peak_pu_inst = row.trace_grid_i_peak_pu(j);
        tr.envelope_lower_pu = row.trace_envelope_lower_pu(j);
        tr.envelope_upper_pu = row.trace_envelope_upper_pu(j);
        tr.envelope_violation_pu = row.trace_envelope_violation_pu(j);
        tr.pcc_assessment_voltage_pu = row.trace_pcc_assessment_voltage_pu(j);
        tr.pcc_envelope_lower_pu = row.trace_pcc_envelope_lower_pu(j);
        tr.pcc_envelope_upper_pu = row.trace_pcc_envelope_upper_pu(j);
        tr.pcc_envelope_violation_pu = row.trace_pcc_envelope_violation_pu(j);
        tr.fault_lv_band_violation_pu = row.trace_fault_lv_band_violation_pu(j);
        tr.recovery_violation_pu = row.trace_recovery_violation_pu(j);
        tr.window_zone = classify_zone(t(j), row.fault_start, row.fault_clear, row.stop_time);
        for ii = 1:24
            tr.(sprintf('obs_%02d', ii)) = row.trace_obs(ii, j);
        end
        for ii = 1:4
            tr.(sprintf('actor_action_%02d', ii)) = row.trace_act(ii, j);
            tr.(sprintf('cmd_action_%02d', ii)) = row.trace_act(ii, j);
            if size(row.trace_meas_act, 2) >= j
                tr.(sprintf('meas_action_%02d', ii)) = row.trace_meas_act(ii, j);
            else
                tr.(sprintf('meas_action_%02d', ii)) = NaN;
            end
        end
        traceCells{end+1} = tr; %#ok<AGROW>
    end
end

function zone = classify_zone(t, faultStart, faultClear, stopTime)
    if t < faultStart
        zone = "pre_fault";
    elseif t < faultClear
        zone = "fault";
    elseif t < stopTime - 0.005
        zone = "recovery";
    else
        zone = "final";
    end
end

function tf = faults_have_phase_vector(faults)
    tf = false;
    for k = 1:size(faults, 1)
        if size(faults, 2) >= 4 && ~isempty(faults{k, 4})
            tf = true;
            return;
        end
    end
end

function phasePu = fault_phase_pu(faults, rowIdx, faultPu)
    if size(faults, 2) >= 4 && ~isempty(faults{rowIdx, 4})
        phasePu = double(faults{rowIdx, 4});
    else
        phasePu = [faultPu, faultPu, faultPu];
    end
    phasePu = reshape(phasePu, 1, []);
    assert(numel(phasePu) == 3, ...
        'Fault phase multiplier must be [puA puB puC]');
    assert(all(isfinite(phasePu)) && all(phasePu > 0), ...
        'Fault phase multipliers must be positive finite values');
end

function in = set_programmable_grid(in, M, nominalGridVoltage, faultPu, faultStart, faultClear, stopTime)
    grid = [M '/Grid'];
    t1 = max(0.0, faultStart - 1e-4);
    t2 = faultStart;
    t3 = faultClear;
    t4 = min(stopTime, faultClear + 1e-4);
    in = in.setBlockParameter(grid, 'PositiveSequence', ...
        sprintf('[%.12g 0 50]', nominalGridVoltage));
    in = in.setBlockParameter(grid, 'VariationEntity', 'Amplitude');
    in = in.setBlockParameter(grid, 'VariationType', 'Table of time-amplitude pairs');
    in = in.setBlockParameter(grid, 'TimeValues', ...
        sprintf('[0 %.12g %.12g %.12g %.12g %.12g]', t1, t2, t3, t4, stopTime));
    in = in.setBlockParameter(grid, 'Amplitudes', ...
        sprintf('[1 1 %.12g %.12g 1 1]', faultPu, faultPu));
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

function replace_grid_with_programmable_source(M, sourceBranch)
    grid = [M '/Grid'];
    pos = get_param(grid, 'Position');
    delete_block(grid);
    add_block('powerlib/Electrical Sources/Three-Phase Programmable Voltage Source', ...
        grid, 'Position', pos);
    for k = 1:3
        connect_if_free(M, ph(grid, 'RConn', k), ...
            ph([M '/' sourceBranch], 'LConn', k));
    end
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

function y = orient_channels(x, nChannels)
    x = squeeze(x);
    if size(x, 1) == nChannels
        y = x;
    elseif size(x, 2) == nChannels
        y = x';
    else
        y = reshape(x, nChannels, []);
    end
end

function row = add_grid_current_metrics(row, gridVRows, gridIRows, t, faultStart, faultClear)
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

    [vPosPu, idPu, iqPu, iPeakPu] = grid_dq_from_voltage_angle( ...
        gridVRows, gridIRows, vPhasePeak, iBasePeak);
    refPu = arrayfun(@(v) grid_iq_reference(v, iqPeLimitPu), vPosPu);
    assessIdx = t >= faultStart + reactiveDelay & t <= faultClear;
    demandIdx = assessIdx & abs(refPu) > reactiveTol;

    row.grid_vpos_pu_min = min(vPosPu(t >= faultStart & t <= faultClear));
    row.grid_vpos_pu_mean = safe_mean(vPosPu(t >= faultStart & t <= faultClear));
    row.grid_id_mean_pu = safe_mean(idPu(assessIdx));
    row.grid_iq_mean_pu = safe_mean(iqPu(assessIdx));
    row.grid_iq_ref_mean_pu = safe_mean(refPu(assessIdx));
    currentEvalStart = faultStart + currentBlanking;
    currentEvalIdx = t >= currentEvalStart;
    currentFaultIdx = t >= currentEvalStart & t <= faultClear;
    currentRecoveryIdx = t >= faultClear + currentBlanking;
    row.grid_current_limit_pu = currentLimitPu;
    row.grid_current_eval_start_s = currentEvalStart;
    row.grid_current_peak_global_pu = max(iPeakPu);
    row.grid_current_peak_fault_pu = safe_max(iPeakPu(currentFaultIdx));
    row.grid_current_peak_recovery_pu = safe_max(iPeakPu(currentRecoveryIdx));
    row.grid_current_peak_pu = safe_max(iPeakPu(currentEvalIdx));
    row.grid_idq_peak_pu = max(sqrt(idPu.^2 + iqPu.^2));
    row.gbt_grid_current_limit_pass = row.grid_current_peak_pu <= currentLimitPu;

    wrongSign = (vPosPu < 0.9 & iqPu < -signEps) | ...
        (vPosPu > 1.1 & iqPu > signEps);
    row.grid_iq_wrong_sign = any(wrongSign(assessIdx));

    if ~any(assessIdx)
        row.grid_iq_shortfall_max_pu = NaN;
        row.grid_iq_met_fraction = NaN;
        row.gbt_reactive_status = "not_evaluated_no_fault_current_window";
        row.gbt_reactive_evaluated = false;
        row.gbt_reactive_pass = false;
    elseif ~any(demandIdx)
        row.grid_iq_shortfall_max_pu = 0.0;
        row.grid_iq_met_fraction = NaN;
        row.gbt_reactive_status = "not_evaluated_no_sustained_reactive_demand_after_delay";
        row.gbt_reactive_evaluated = false;
        row.gbt_reactive_pass = false;
    else
        row.gbt_reactive_evaluated = true;
        shortfall = zeros(size(refPu));
        lvrtIdx = refPu > reactiveTol;
        hvrtIdx = refPu < -reactiveTol;
        shortfall(lvrtIdx) = max(0.0, (refPu(lvrtIdx) - reactiveTol) - iqPu(lvrtIdx));
        shortfall(hvrtIdx) = max(0.0, iqPu(hvrtIdx) - (refPu(hvrtIdx) + reactiveTol));
        metIdx = demandIdx & shortfall <= 1e-9;
        row.grid_iq_shortfall_max_pu = max(shortfall(demandIdx));
        row.grid_iq_met_fraction = nnz(metIdx) / nnz(demandIdx);
        if row.grid_iq_wrong_sign
            row.gbt_reactive_status = "reactive_wrong_sign";
            row.gbt_reactive_pass = false;
        elseif row.grid_iq_met_fraction < reactiveDwell
            row.gbt_reactive_status = "reactive_shortfall";
            row.gbt_reactive_pass = false;
        else
            row.gbt_reactive_status = "pass";
            row.gbt_reactive_pass = true;
        end
    end
    row.trace_grid_metrics = struct( ...
        'vpos_pu', vPosPu, ...
        'iq_pu', iqPu, ...
        'iq_ref_pu', refPu, ...
        'i_peak_pu', iPeakPu);
end

function [vPosPu, idPu, iqPu, iPeakPu] = grid_dq_from_voltage_angle( ...
    gridVRows, gridIRows, vPhasePeak, iBasePeak)
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
    iqPu = -iq ./ iBasePeak;
    iPeakPu = max(abs(gridIRows), [], 1)' ./ iBasePeak;
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

function row = add_fault_quality_metrics(row, lvRmsInst, gridVRows, t, ...
    targetPhaseRms, nominalGridVoltage, faultPu, faultPhasePu, faultStart, ...
    faultClear, stopTime, faultSettleS)

    solverTol = 1e-3;
    lvPu = lvRmsInst ./ targetPhaseRms;
    assessIdx = t >= faultStart + max(0.0, faultSettleS) & t <= stopTime;
    recoveryIdx = t >= faultClear + 0.035 & t <= stopTime;

    recoveryViolation = max(0.0, abs(lvPu - 1.0) - 0.07);
    recoveryViolation(~recoveryIdx) = 0.0;

    faultBandIdx = t >= faultStart + max(0.0, faultSettleS) & t <= faultClear;
    faultLoPu = 176.0 / targetPhaseRms;
    faultHiPu = 238.0 / targetPhaseRms;
    faultBandViolation = max(max(0.0, faultLoPu - lvPu), ...
        max(0.0, lvPu - faultHiPu));
    faultBandViolation(~faultBandIdx) = 0.0;
    loadQualityViolation = max(faultBandViolation, recoveryViolation);

    dt = median(diff(t));
    row.load_quality_violation_max_pu = safe_max(loadQualityViolation(assessIdx));
    row.load_quality_violation_mean_pu = safe_mean(loadQualityViolation(assessIdx));
    row.load_quality_violation_duration_s = dt * ...
        nnz(loadQualityViolation(assessIdx) > solverTol);
    row.load_quality_pass = row.load_quality_violation_max_pu <= solverTol;

    % Compatibility aliases. These fields are load-quality metrics and must
    % not be interpreted as the GB/T PCC voltage envelope.
    row.envelope_violation_max_pu = row.load_quality_violation_max_pu;
    row.envelope_violation_mean_pu = row.load_quality_violation_mean_pu;
    row.envelope_violation_duration_s = row.load_quality_violation_duration_s;
    row.envelope_margin_min_pu = -row.load_quality_violation_max_pu;
    row.envelope_pass = row.load_quality_pass;
    if any(faultBandIdx)
        row.fault_lv_min = min(lvRmsInst(faultBandIdx));
        row.fault_lv_max = max(lvRmsInst(faultBandIdx));
        row.fault_lv_band_violation_max_pu = safe_max(faultBandViolation(faultBandIdx));
        row.fault_lv_band_violation_mean_pu = safe_mean(faultBandViolation(faultBandIdx));
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
    row.recovery_violation_max_pu = safe_max(recoveryViolation(recoveryIdx));
    row.recovery_violation_mean_pu = safe_mean(recoveryViolation(recoveryIdx));
    row.recovery_violation_duration_s = dt * nnz(recoveryViolation(recoveryIdx) > solverTol);
    row.recovery_envelope_pass = row.recovery_violation_max_pu <= solverTol;
    row.timestep_envelope_pass = row.load_quality_pass && ...
        row.fault_lv_band_pass && row.recovery_envelope_pass;
    row.trace_envelope_lower_pu = NaN(size(t));
    row.trace_envelope_upper_pu = NaN(size(t));
    row.trace_envelope_violation_pu = loadQualityViolation;
    row.trace_fault_lv_band_violation_pu = faultBandViolation;
    row.trace_recovery_violation_pu = recoveryViolation;

    [pccPu, assessmentSignal] = hpt_pcc_assessment_voltage( ...
        gridVRows, t, faultPhasePu, faultPu, nominalGridVoltage, 50.0);
    pccLower = -Inf(size(t));
    pccUpper = Inf(size(t));
    if faultPu < 1.0
        pccLower = hpt_gbt19963_envelope("LVRT", t - faultStart);
    else
        pccUpper = hpt_gbt19963_envelope("HVRT", t - faultStart);
    end
    pccViolation = max(max(0.0, pccLower - pccPu), ...
        max(0.0, pccPu - pccUpper));
    pccViolation(~assessIdx) = 0.0;
    pccMargin = min(pccPu - pccLower, pccUpper - pccPu);
    pccMargin(~assessIdx) = Inf;
    row.pcc_assessment_signal = assessmentSignal;
    row.pcc_voltage_min_pu = safe_min(pccPu(assessIdx));
    row.pcc_voltage_max_pu = max(pccPu(assessIdx));
    row.pcc_envelope_violation_max_pu = safe_max(pccViolation(assessIdx));
    row.pcc_envelope_violation_mean_pu = safe_mean(pccViolation(assessIdx));
    row.pcc_envelope_violation_duration_s = dt * ...
        nnz(pccViolation(assessIdx) > solverTol);
    row.pcc_envelope_margin_min_pu = safe_min(pccMargin(assessIdx));
    row.pcc_envelope_pass = row.pcc_envelope_violation_max_pu <= solverTol;
    row.scenario_valid = row.pcc_envelope_pass;
    if row.scenario_valid
        row.scenario_valid_reason = "pass";
    else
        row.scenario_valid_reason = "pcc_voltage_outside_gbt_envelope";
    end
    row.trace_pcc_assessment_voltage_pu = pccPu;
    row.trace_pcc_envelope_lower_pu = pccLower;
    row.trace_pcc_envelope_upper_pu = pccUpper;
    row.trace_pcc_envelope_violation_pu = pccViolation;
end

function m = safe_mean(x)
    if isempty(x)
        m = NaN;
    else
        y = x(:);
        y = y(~isnan(y));
        if isempty(y)
            m = NaN;
        else
            m = mean(y);
        end
    end
end

function m = safe_min(x)
    if isempty(x)
        m = NaN;
    else
        y = x(:);
        y = y(~isnan(y));
        if isempty(y)
            m = NaN;
        else
            m = min(y);
        end
    end
end

function m = safe_max(x)
    if isempty(x)
        m = NaN;
    else
        y = x(:);
        y = y(~isnan(y));
        if isempty(y)
            m = NaN;
        else
            m = max(y);
        end
    end
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
            % Measure the physical energy-branch current directly.  The dq
            % frame is aligned to the measured energy-branch voltage, and
            % the result is normalized to the command contract scale where
            % act4(3:4)=idq_ref/hpt_energy_id_max.
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
            actRows(3, k) = (ialpha*cos(theta) + ibeta*sin(theta)) / max(energyIdMax, 1e-9);
            actRows(4, k) = (-ialpha*sin(theta) + ibeta*cos(theta)) / max(energyIdMax, 1e-9);
        elseif size(energyDbgRows, 1) >= 5 && k <= size(energyDbgRows, 2)
            % Conventional energy controller debug order is
            % [theta; vd; vq; id; iq; id_ref; ...].  Use actual id/iq, not
            % id_ref, when HPTSAC observations are unavailable.
            actRows(3, k) = energyDbgRows(4, k) / max(energyIdMax, 1e-9);
            actRows(4, k) = energyDbgRows(5, k) / max(energyIdMax, 1e-9);
        else
            actRows(3, k) = hptActRows(3, k);
            actRows(4, k) = hptActRows(4, k);
        end
    end
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
    v = safe_mean(rows(idx, tailStart:end));
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
    v = safe_mean(rows(rowIdx, mask));
end

function row = strip_trace(row)
    row = rmfield(row, {'trace_t', 'trace_vlv', 'trace_vdc', 'trace_obs', ...
        'trace_act', 'trace_meas_act', 'trace_grid_vpos_pu', ...
        'trace_grid_vneg_seq_pu', 'trace_grid_vabc_unbalance_pu', ...
        'trace_grid_iq_pu', ...
        'trace_grid_iq_ref_pu', 'trace_grid_i_peak_pu', ...
        'trace_envelope_lower_pu', 'trace_envelope_upper_pu', ...
        'trace_envelope_violation_pu', 'trace_fault_lv_band_violation_pu', ...
        'trace_recovery_violation_pu', 'trace_pcc_assessment_voltage_pu', ...
        'trace_pcc_envelope_lower_pu', 'trace_pcc_envelope_upper_pu', ...
        'trace_pcc_envelope_violation_pu'});
end

function write_trace_csv(path, rowCells)
    if isempty(rowCells)
        fid = fopen(path, 'w');
        fclose(fid);
        return;
    end
    T = struct2table([rowCells{:}]);
    writetable(T, path);
end

