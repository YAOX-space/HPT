% collect_hpt_v2_trajectory_trace
% Collect per-2-ms switch-level traces for a supplied HPT action trajectory.
%
% Workspace overrides:
%   hpt_trace_topology            "topology1" | "topology2"
%   hpt_trace_fault_pu            default 0.95
%   hpt_trace_fault_duration      default 0.08 s
%   hpt_trace_fault_phase_pu      optional [puA puB puC], default balanced
%   hpt_trace_fault_start         default 0.035 s
%   hpt_trace_fault_stop_margin   default 0.125 s
%   hpt_trace_trajectory_file     MAT with hpt_traj_t / hpt_traj_action
%   hpt_trace_policy_mode         default -2.0, use 1.0 for actor traces
%   hpt_trace_actor_select_mode   default 0.0, use 3.0 for always-on actor
%   hpt_trace_actor_filter_tau    default 0.001 s, set 0 for raw actor diagnostics
%   hpt_trace_model_params        optional struct of model-workspace overrides
%   hpt_trace_run_label           optional result-folder token
%   hpt_trace_sample_stride       default 100, i.e. 2 ms with Ts=20 us
%   hpt_trace_output_dir          optional explicit result directory

clearvars -except hpt_trace_topology hpt_trace_fault_pu hpt_trace_fault_phase_pu hpt_trace_fault_duration hpt_trace_fault_start hpt_trace_fault_stop_margin hpt_trace_trajectory_file hpt_trace_policy_mode hpt_trace_actor_select_mode hpt_trace_actor_filter_tau hpt_trace_model_params hpt_trace_run_label hpt_trace_sample_stride hpt_trace_output_dir;
close all;

if ~exist('hpt_trace_topology', 'var')
    hpt_trace_topology = "topology2";
end
if ~exist('hpt_trace_fault_pu', 'var')
    hpt_trace_fault_pu = 0.95;
end
if ~exist('hpt_trace_fault_phase_pu', 'var') || isempty(hpt_trace_fault_phase_pu)
    hpt_trace_fault_phase_pu = [hpt_trace_fault_pu, hpt_trace_fault_pu, hpt_trace_fault_pu];
end
hpt_trace_fault_phase_pu = reshape(double(hpt_trace_fault_phase_pu), 1, []);
assert(numel(hpt_trace_fault_phase_pu) == 3, ...
    'hpt_trace_fault_phase_pu must be [puA puB puC]');
usePhaseFaultSource = max(abs(hpt_trace_fault_phase_pu - hpt_trace_fault_pu)) > 1e-9;
if ~exist('hpt_trace_fault_duration', 'var')
    hpt_trace_fault_duration = 0.08;
end
if ~exist('hpt_trace_fault_start', 'var')
    hpt_trace_fault_start = 0.035;
end
if ~exist('hpt_trace_fault_stop_margin', 'var')
    hpt_trace_fault_stop_margin = 0.125;
end
if ~exist('hpt_trace_trajectory_file', 'var')
    hpt_trace_trajectory_file = "";
end
if ~exist('hpt_trace_policy_mode', 'var')
    hpt_trace_policy_mode = -2.0;
end
if ~exist('hpt_trace_actor_select_mode', 'var')
    hpt_trace_actor_select_mode = 0.0;
end
if ~exist('hpt_trace_actor_filter_tau', 'var')
    hpt_trace_actor_filter_tau = 0.001;
end
if ~exist('hpt_trace_model_params', 'var')
    hpt_trace_model_params = struct();
end
if ~exist('hpt_trace_run_label', 'var')
    hpt_trace_run_label = "";
end
if ~exist('hpt_trace_sample_stride', 'var')
    hpt_trace_sample_stride = 100;
end
if ~exist('hpt_trace_output_dir', 'var')
    hpt_trace_output_dir = "";
end

hpt_trace_topology = string(hpt_trace_topology);
hpt_trace_trajectory_file = string(hpt_trace_trajectory_file);
if hpt_trace_policy_mode <= -1.5
    assert(strlength(hpt_trace_trajectory_file) > 0, ...
        'hpt_trace_trajectory_file is required for trajectory mode');
    assert(exist(hpt_trace_trajectory_file, 'file') == 2, ...
        'Missing trajectory file: %s', hpt_trace_trajectory_file);
end

rootDir = fileparts(fileparts(mfilename('fullpath')));
cases = {
    fullfile(rootDir, 'topology1'), 'build_hpt_v2_1to1_switchlevel', 'hpt_v2_1to1_switchlevel', 'topology1', 'Zg';
    fullfile(rootDir, 'topology2'), 'build_hpt_v2_topology2_paper', 'hpt_v2_topology2_paper', 'topology2', 'Source_RL';
};

targetPhaseRms = 207.0;
nominalGridVoltage = 10000;
Ts = 20e-6;
faultStart = hpt_trace_fault_start;
faultClear = faultStart + hpt_trace_fault_duration;
stopTime = faultClear + hpt_trace_fault_stop_margin;

caseIdx = find(string(cases(:, 4)) == hpt_trace_topology, 1);
assert(~isempty(caseIdx), 'Unknown topology: %s', hpt_trace_topology);

oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));
cd(cases{caseIdx, 1});
feval(cases{caseIdx, 2});
M = cases{caseIdx, 3};
sourceBranch = cases{caseIdx, 5};
if strlength(hpt_trace_trajectory_file) > 0
    localTrajectoryFile = fullfile(pwd, 'hpt_sac_trajectory.mat');
    if ~strcmpi(char(java.io.File(char(hpt_trace_trajectory_file)).getCanonicalPath()), ...
            char(java.io.File(localTrajectoryFile).getCanonicalPath()))
        copyfile(char(hpt_trace_trajectory_file), localTrajectoryFile, 'f');
    end
end

if usePhaseFaultSource
    replace_grid_with_controlled_phase_source(M, sourceBranch, nominalGridVoltage, ...
        hpt_trace_fault_phase_pu, faultStart, faultClear);
else
    replace_grid_with_programmable_source(M, sourceBranch, nominalGridVoltage, ...
        hpt_trace_fault_pu, faultStart, faultClear, stopTime);
end

in = Simulink.SimulationInput(M);
in = in.setModelParameter('StopTime', num2str(stopTime));
in = in.setVariable('hpt_sac_enable', 1.0, 'Workspace', M);
in = in.setVariable('hpt_sac_energy_enable', 1.0, 'Workspace', M);
in = in.setVariable('hpt_sac_policy_mode', hpt_trace_policy_mode, 'Workspace', M);
in = in.setVariable('hpt_sac_actor_select_mode', hpt_trace_actor_select_mode, 'Workspace', M);
in = in.setVariable('hpt_sac_actor_filter_tau', hpt_trace_actor_filter_tau, 'Workspace', M);
in = in.setVariable('hpt_sac_guard_enable', 0.0, 'Workspace', M);
in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
gridNormStartupS = min(0.070, max(0.030, faultStart - 0.005));
in = in.setVariable('hpt_sac_gridnorm_startup_s', gridNormStartupS, 'Workspace', M);
if strlength(hpt_trace_trajectory_file) > 0
    trajData = load(char(hpt_trace_trajectory_file), 'hpt_traj_t', 'hpt_traj_action');
    assert(isfield(trajData, 'hpt_traj_t') && isfield(trajData, 'hpt_traj_action'), ...
        'Trajectory file must contain hpt_traj_t and hpt_traj_action');
    trajT = double(trajData.hpt_traj_t(:));
    trajAction = double(trajData.hpt_traj_action);
    assert(size(trajAction, 1) == numel(trajT) && size(trajAction, 2) == 4, ...
        'hpt_traj_action must be Nx4 and match hpt_traj_t');
    in = in.setVariable('hpt_traj_t', trajT, 'Workspace', M);
    in = in.setVariable('hpt_traj_action', trajAction, 'Workspace', M);
end
modelNames = fieldnames(hpt_trace_model_params);
for modelIdx = 1:numel(modelNames)
    in = in.setVariable(modelNames{modelIdx}, hpt_trace_model_params.(modelNames{modelIdx}), ...
        'Workspace', M);
end
out = sim(in);

obsRows = orient_channels(out.get('HPTSAC_obs'), 24);
actRows = orient_channels(out.get('HPTSAC_action'), 4);
vdcRows = orient_channels(out.get('Vdc'), 1);
gridVRows = orient_channels(out.get('Vpri_abc'), 3);
gridIRows = orient_channels(out.get('Igrid_abc'), 3);
if has_logged_var(out, 'Vgrid_cmd_abc')
    gridCmdVRows = orient_channels(out.get('Vgrid_cmd_abc'), 3);
else
    gridCmdVRows = NaN(size(gridVRows));
end
lvRows = orient_channels(out.get('Vlv_abc'), 3);
mrefRows = orient_channels(out.get('Mref6_cmd'), 6);
mengRows = orient_channels(out.get('Menergy_cmd'), 3);
mregDbgRows = orient_channels(out.get('Mreg_cmd'), 7);
energyDbgRows = orient_channels(out.get('Energy_dbg'), 12);
energyVRows = orient_channels(out.get('Energy_Vabc'), 3);
if has_logged_var(out, 'Energy_Iabc')
    energyIRows = orient_channels(out.get('Energy_Iabc'), 3);
else
    energyIRows = zeros(size(energyVRows));
end
regIRows = logged_or_nan_rows(out, 'Reg_Iabc', 3, lvRows);
hbcCapVRows = logged_or_nan_rows(out, 'HBC_Cap_Vabc', 3, lvRows);
seriesW5VRows = logged_or_nan_rows(out, 'Series_W5_Vabc', 3, lvRows);
seriesW6VRows = logged_or_nan_rows(out, 'Series_W6_Vabc', 3, lvRows);
vinjRows = logged_or_nan_rows(out, 'Vinj_abc', 3, lvRows);
idcCapRows = logged_or_nan_rows(out, 'Idc_cap', 1, vdcRows);
energyIdMax = getVariable(get_param(M, 'ModelWorkspace'), 'hpt_energy_id_max');
measActRows = measured_response_rows(actRows, mrefRows, mregDbgRows, ...
    energyDbgRows, energyVRows, energyIRows, energyIdMax);
phys = collect_physical_params(M, hpt_trace_topology, sourceBranch, targetPhaseRms, ...
    nominalGridVoltage, Srated_from_model(M), Ts);
missingStateReport = collect_missing_state_report();
n = min([size(obsRows, 2), size(actRows, 2), size(measActRows, 2), ...
    size(vdcRows, 2), size(gridVRows, 2), size(gridIRows, 2), ...
    size(gridCmdVRows, 2), size(lvRows, 2), size(energyVRows, 2), size(energyIRows, 2), ...
    size(regIRows, 2), size(hbcCapVRows, 2), size(seriesW5VRows, 2), ...
    size(seriesW6VRows, 2), size(vinjRows, 2), size(idcCapRows, 2), ...
    size(mrefRows, 2), size(mengRows, 2)]);
t = (0:n-1) * Ts;
sampleIdx = 1:hpt_trace_sample_stride:n;

rows = repmat(base_row(), 0, 1);
faultPrefix = "lvrt";
if hpt_trace_fault_pu > 1.0
    faultPrefix = "hvrt";
end
for kk = 1:numel(sampleIdx)
    j = sampleIdx(kk);
    row = base_row();
    row.model = string(M);
    row.topology = hpt_trace_topology;
    row.scenario_type = "fault";
    row.condition_class = condition_class(hpt_trace_fault_pu);
    row.case_name = string(sprintf('%s_%03dms_%.3fpu', faultPrefix, round(1000*hpt_trace_fault_duration), hpt_trace_fault_pu));
    row.t = t(j);
    row.grid_V = NaN;
    row.fault_pu = hpt_trace_fault_pu;
    row.grid_pu = hpt_trace_fault_pu;
    row.fault_a_pu = hpt_trace_fault_phase_pu(1);
    row.fault_b_pu = hpt_trace_fault_phase_pu(2);
    row.fault_c_pu = hpt_trace_fault_phase_pu(3);
    row.lv_rms_inst = sqrt(mean(lvRows(:, j).^2));
    row.vdc_inst = vdcRows(1, j);
    row.vdc_pu_inst = vdcRows(1, j) / max(phys.vdc_ref, 1e-9);
    row.idc_cap_inst = idcCapRows(1, j);
    row = add_abc_row(row, 'grid_v', gridVRows(:, j));
    row = add_abc_row(row, 'grid_cmd_v', gridCmdVRows(:, j));
    row = add_abc_row(row, 'grid_i', gridIRows(:, j));
    row = add_abc_row(row, 'lv_v', lvRows(:, j));
    row = add_abc_row(row, 'energy_v', energyVRows(:, j));
    row = add_abc_row(row, 'energy_i', energyIRows(:, j));
    row = add_abc_row(row, 'reg_i', regIRows(:, j));
    row = add_abc_row(row, 'hbc_cap_v', hbcCapVRows(:, j));
    row = add_abc_row(row, 'series_w5_v', seriesW5VRows(:, j));
    row = add_abc_row(row, 'series_w6_v', seriesW6VRows(:, j));
    row = add_abc_row(row, 'series_inj_v', vinjRows(:, j));
    row = add_dq_row(row, 'grid', gridVRows(:, j), gridIRows(:, j), ...
        phys.grid_v_phase_peak, phys.grid_i_base_peak, true);
    row = add_voltage_dq_row(row, 'grid_cmd', gridCmdVRows(:, j), phys.grid_v_phase_peak);
    row = add_voltage_dq_row(row, 'lv', lvRows(:, j), phys.lv_v_phase_peak);
    row = add_dq_row(row, 'energy', energyVRows(:, j), energyIRows(:, j), ...
        phys.lv_v_phase_peak, phys.lv_i_base_peak, false);
    row = add_voltage_dq_row(row, 'hbc_cap', hbcCapVRows(:, j), phys.lv_v_phase_peak);
    row = add_voltage_dq_row(row, 'series_w5', seriesW5VRows(:, j), phys.lv_v_phase_peak);
    row = add_voltage_dq_row(row, 'series_w6', seriesW6VRows(:, j), phys.lv_v_phase_peak);
    row = add_voltage_dq_row(row, 'series_inj', vinjRows(:, j), phys.lv_v_phase_peak);
    row = add_dq_row(row, 'reg', vinjRows(:, j), regIRows(:, j), ...
        phys.lv_v_phase_peak, phys.lv_i_base_peak, false);
    row.reg_current_available = all(isfinite(regIRows(:, j)));
    row.reg_current_missing_reason = "";
    row.window_zone = window_zone(t(j), faultStart, faultClear, stopTime);
    row.action_source = action_source(hpt_trace_policy_mode);
    row.actor_select_mode = hpt_trace_actor_select_mode;
    for ii = 1:24
        row.(sprintf('obs_%02d', ii)) = obsRows(ii, j);
    end
    for ii = 1:4
        row.(sprintf('action_%02d', ii)) = actRows(ii, j);
        row.(sprintf('actor_action_%02d', ii)) = actRows(ii, j);
        row.(sprintf('cmd_action_%02d', ii)) = actRows(ii, j);
        row.(sprintf('meas_action_%02d', ii)) = measActRows(ii, j);
        row.(sprintf('teacher_action_%02d', ii)) = measActRows(ii, j);
    end
    for ii = 1:6
        row.(sprintf('mref_%02d', ii)) = mrefRows(ii, j);
    end
    for ii = 1:3
        row.(sprintf('menergy_%02d', ii)) = mengRows(ii, j);
    end
    rows(end+1, 1) = row; %#ok<SAGROW>
end

if strlength(string(hpt_trace_output_dir)) > 0
    outDir = char(hpt_trace_output_dir);
else
    outDir = fullfile(rootDir, '..', '..', 'lab', 'results', ...
        'hpt_v2_trajectory_traces');
end
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
safeLabel = regexprep(sprintf('%s_%s', hpt_trace_topology, hpt_trace_run_label), ...
    '[^A-Za-z0-9_]+', '_');
outMat = fullfile(outDir, ['trajectory_trace_' char(safeLabel) '_' stamp '.mat']);
outCsv = fullfile(outDir, ['trajectory_trace_' char(safeLabel) '_' stamp '.csv']);
outParamJson = fullfile(outDir, ['trajectory_trace_' char(safeLabel) '_' stamp '_physical_params.json']);
outMissingJson = fullfile(outDir, ['trajectory_trace_' char(safeLabel) '_' stamp '_missing_states.json']);
save(outMat, 'rows', 'targetPhaseRms', 'faultStart', 'faultClear', ...
    'stopTime', 'hpt_trace_trajectory_file', 'hpt_trace_model_params', ...
    'phys', 'missingStateReport');
writetable(struct2table(rows), outCsv);
write_json_file(outParamJson, phys);
write_json_file(outMissingJson, missingStateReport);
close_system(M, 0);
fprintf('Collected %d trajectory trace samples.\n', numel(rows));
fprintf('Saved MAT: %s\n', outMat);
fprintf('Saved CSV: %s\n', outCsv);
fprintf('Saved physical params: %s\n', outParamJson);
fprintf('Saved missing state report: %s\n', outMissingJson);

function row = base_row()
    row = struct();
    row.model = "";
    row.topology = "";
    row.scenario_type = "";
    row.condition_class = "";
    row.case_name = "";
    row.t = NaN;
    row.window_zone = "";
    row.action_source = "";
    row.actor_select_mode = NaN;
    row.grid_V = NaN;
    row.fault_pu = NaN;
    row.grid_pu = NaN;
    row.fault_a_pu = NaN;
    row.fault_b_pu = NaN;
    row.fault_c_pu = NaN;
    row.lv_rms_inst = NaN;
    row.vdc_inst = NaN;
    row.vdc_pu_inst = NaN;
    row.idc_cap_inst = NaN;
    row = add_abc_fields(row, 'grid_v');
    row = add_abc_fields(row, 'grid_cmd_v');
    row = add_abc_fields(row, 'grid_i');
    row = add_abc_fields(row, 'lv_v');
    row = add_abc_fields(row, 'energy_v');
    row = add_abc_fields(row, 'energy_i');
    row = add_abc_fields(row, 'reg_i');
    row = add_abc_fields(row, 'hbc_cap_v');
    row = add_abc_fields(row, 'series_w5_v');
    row = add_abc_fields(row, 'series_w6_v');
    row = add_abc_fields(row, 'series_inj_v');
    row = add_dq_fields(row, 'grid');
    row = add_voltage_dq_fields(row, 'grid_cmd');
    row = add_voltage_dq_fields(row, 'lv');
    row = add_dq_fields(row, 'energy');
    row = add_voltage_dq_fields(row, 'hbc_cap');
    row = add_voltage_dq_fields(row, 'series_w5');
    row = add_voltage_dq_fields(row, 'series_w6');
    row = add_voltage_dq_fields(row, 'series_inj');
    row = add_dq_fields(row, 'reg');
    row.reg_current_available = false;
    row.reg_current_missing_reason = "";
    for ii = 1:24
        row.(sprintf('obs_%02d', ii)) = NaN;
    end
    for ii = 1:4
        row.(sprintf('action_%02d', ii)) = NaN;
        row.(sprintf('actor_action_%02d', ii)) = NaN;
        row.(sprintf('cmd_action_%02d', ii)) = NaN;
        row.(sprintf('meas_action_%02d', ii)) = NaN;
        row.(sprintf('teacher_action_%02d', ii)) = NaN;
    end
    for ii = 1:6
        row.(sprintf('mref_%02d', ii)) = NaN;
    end
    for ii = 1:3
        row.(sprintf('menergy_%02d', ii)) = NaN;
    end
end

function row = add_abc_fields(row, prefix)
    row.(sprintf('%s_a_inst', prefix)) = NaN;
    row.(sprintf('%s_b_inst', prefix)) = NaN;
    row.(sprintf('%s_c_inst', prefix)) = NaN;
end

function row = add_abc_row(row, prefix, xabc)
    row.(sprintf('%s_a_inst', prefix)) = xabc(1);
    row.(sprintf('%s_b_inst', prefix)) = xabc(2);
    row.(sprintf('%s_c_inst', prefix)) = xabc(3);
end

function row = add_voltage_dq_fields(row, prefix)
    row.(sprintf('%s_v_alpha_inst', prefix)) = NaN;
    row.(sprintf('%s_v_beta_inst', prefix)) = NaN;
    row.(sprintf('%s_v_d_inst', prefix)) = NaN;
    row.(sprintf('%s_v_q_inst', prefix)) = NaN;
    row.(sprintf('%s_v_mag_pu_inst', prefix)) = NaN;
end

function row = add_dq_fields(row, prefix)
    row = add_voltage_dq_fields(row, prefix);
    row.(sprintf('%s_i_alpha_inst', prefix)) = NaN;
    row.(sprintf('%s_i_beta_inst', prefix)) = NaN;
    row.(sprintf('%s_i_d_pu_inst', prefix)) = NaN;
    row.(sprintf('%s_i_q_pu_inst', prefix)) = NaN;
    row.(sprintf('%s_i_mag_pu_inst', prefix)) = NaN;
end

function row = add_voltage_dq_row(row, prefix, vabc, vBasePeak)
    [valpha, vbeta] = abc_to_alphabeta(vabc);
    theta = atan2(vbeta, valpha);
    vd = valpha*cos(theta) + vbeta*sin(theta);
    vq = -valpha*sin(theta) + vbeta*cos(theta);
    row.(sprintf('%s_v_alpha_inst', prefix)) = valpha;
    row.(sprintf('%s_v_beta_inst', prefix)) = vbeta;
    row.(sprintf('%s_v_d_inst', prefix)) = vd;
    row.(sprintf('%s_v_q_inst', prefix)) = vq;
    row.(sprintf('%s_v_mag_pu_inst', prefix)) = sqrt(valpha^2 + vbeta^2) / max(vBasePeak, 1e-9);
end

function row = add_dq_row(row, prefix, vabc, iabc, vBasePeak, iBasePeak, invertIq)
    row = add_voltage_dq_row(row, prefix, vabc, vBasePeak);
    [valpha, vbeta] = abc_to_alphabeta(vabc);
    [ialpha, ibeta] = abc_to_alphabeta(iabc);
    theta = atan2(vbeta, valpha);
    id = ialpha*cos(theta) + ibeta*sin(theta);
    iq = -ialpha*sin(theta) + ibeta*cos(theta);
    if invertIq
        iq = -iq;
    end
    row.(sprintf('%s_i_alpha_inst', prefix)) = ialpha;
    row.(sprintf('%s_i_beta_inst', prefix)) = ibeta;
    row.(sprintf('%s_i_d_pu_inst', prefix)) = id / max(iBasePeak, 1e-9);
    row.(sprintf('%s_i_q_pu_inst', prefix)) = iq / max(iBasePeak, 1e-9);
    row.(sprintf('%s_i_mag_pu_inst', prefix)) = sqrt(id^2 + iq^2) / max(iBasePeak, 1e-9);
end

function [alpha, beta] = abc_to_alphabeta(xabc)
    alpha = (2/3) * (xabc(1) - 0.5*xabc(2) - 0.5*xabc(3));
    beta = (sqrt(3)/3) * (xabc(2) - xabc(3));
end

function phys = collect_physical_params(M, topologyName, sourceBranch, targetPhaseRms, ...
    nominalGridVoltage, srated, Ts)
    mw = get_param(M, 'ModelWorkspace');
    phys = struct();
    phys.model = char(M);
    phys.topology = char(topologyName);
    phys.sample_time_s = Ts;
    phys.grid_frequency_hz = get_mw_numeric(mw, 'hpt_grid_f0', 50.0);
    phys.grid_line_rms_v = nominalGridVoltage;
    phys.lv_phase_rms_ref_v = targetPhaseRms;
    phys.lv_line_rms_nominal_v = sqrt(3) * targetPhaseRms;
    phys.rated_power_va = srated;
    phys.vdc_ref = get_mw_numeric(mw, 'hpt_vdc_ref', ...
        get_mw_numeric(mw, 'hpt_sac_vdc_ref', 800.0));
    phys.vdc_chopper_threshold_v = get_mw_numeric(mw, 'hpt_chopper_threshold', 850.0);
    phys.source_branch = char(sourceBranch);
    phys.source_r_ohm = get_block_numeric(M, sourceBranch, 'Resistance', NaN);
    phys.source_l_h = get_block_numeric(M, sourceBranch, 'Inductance', NaN);
    phys.hbc_filter_r_ohm = get_block_numeric(M, 'SwHBC_L_1', 'Resistance', NaN);
    phys.hbc_filter_l_h = get_block_numeric(M, 'SwHBC_L_1', 'Inductance', NaN);
    phys.hbc_filter_c_f = get_block_numeric(M, 'SwHBC_C_1', 'Capacitance', NaN);
    phys.energy_filter_l_h = get_block_numeric(M, 'TPF_L_1', 'Inductance', NaN);
    phys.dc_link_c_f = get_block_numeric(M, 'Cdc', 'Capacitance', NaN);
    phys.chopper_r_ohm = get_block_numeric(M, 'Rchop', 'Resistance', ...
        get_mw_numeric(mw, 'hpt_rchop', NaN));
    phys.main_transformer_nominal_power = get_param_if_exists(M, 'Main_W1W2_1', 'NominalPower');
    phys.main_transformer_winding1 = get_param_if_exists(M, 'Main_W1W2_1', 'winding1');
    phys.main_transformer_winding2 = get_param_if_exists(M, 'Main_W1W2_1', 'winding2');
    phys.parallel_coupled_nominal_power = get_param_if_exists(M, 'ParallelCoupled_1', 'NominalPower');
    phys.parallel_coupled_winding1 = get_param_if_exists(M, 'ParallelCoupled_1', 'winding1');
    phys.parallel_coupled_winding2 = get_param_if_exists(M, 'ParallelCoupled_1', 'winding2');
    phys.reg_series_nominal_power = get_param_if_exists(M, 'SwRegSeries_W5W6_1', 'NominalPower');
    phys.reg_series_winding1 = get_param_if_exists(M, 'SwRegSeries_W5W6_1', 'winding1');
    phys.reg_series_winding2 = get_param_if_exists(M, 'SwRegSeries_W5W6_1', 'winding2');
    phys.reg_action_limit = get_mw_numeric(mw, 'hpt_sac_reg_max', 0.80);
    phys.energy_action_limit = get_mw_numeric(mw, 'hpt_sac_energy_max', 0.95);
    phys.energy_current_id_max_a = get_mw_numeric(mw, 'hpt_energy_id_max', 20.0);
    phys.lv_v_phase_peak = sqrt(2) * targetPhaseRms;
    phys.grid_v_phase_peak = sqrt(2) * nominalGridVoltage / sqrt(3);
    phys.lv_i_base_peak = get_mw_numeric(mw, 'hpt_sac_i_base_peak', ...
        sqrt(2) * srated / (sqrt(3) * max(sqrt(3)*targetPhaseRms, 1e-9)));
    phys.grid_i_base_peak = sqrt(2) * srated / (sqrt(3) * nominalGridVoltage);
    phys.converter_voltage_relation = 'averaged dq voltage is approximated as proportional to Vdc times modulation command';
end

function report = collect_missing_state_report()
    report = struct();
    report.recorded_low_level_signals = { ...
        'Vpri_abc', 'Igrid_abc', 'Vlv_abc', 'Vdc', ...
        'Vgrid_cmd_abc when phase-fault source is used', ...
        'Energy_Vabc', 'Energy_Iabc', 'Mref6_cmd', 'Menergy_cmd', ...
        'Reg_Iabc when available', 'HBC_Cap_Vabc when available', ...
        'Series_W5_Vabc when available', 'Series_W6_Vabc when available', ...
        'Vinj_abc when available', 'Idc_cap when available', ...
        'HPTSAC_obs', 'HPTSAC_action'};
    report.added_derived_timestep_states = { ...
        'grid_v_dq', 'grid_cmd_v_dq', 'grid_i_dq', 'lv_v_dq', 'energy_v_dq', ...
        'energy_i_dq', 'reg_i_dq', 'hbc_cap_v_dq', 'series_inj_v_dq', ...
        'idc_cap', 'vdc_pu'};
    report.missing_states = struct( ...
        'name', {'reg_i_abc', 'reg_i_dq', 'hbc_filter_cap_voltage_abc', ...
            'series_injection_voltage_abc', 'dc_link_current'}, ...
        'needed_for', {'regulating-converter current ODE', ...
            'regulating-converter current ODE in dq frame', ...
            'LC filter capacitor state', ...
            'load-side voltage injection equation', ...
            'DC-link capacitor energy equation'}, ...
        'status', {'logged_for_topology2', 'derived_when_reg_i_abc_available', ...
            'logged_for_topology2', 'logged_for_topology2', 'estimated_from_cdc_dvdc_dt'}, ...
        'reason', {'Reg_Iabc is logged from added current measurement blocks', ...
            'reg_i_dq is derived from Reg_Iabc and Vinj_abc', ...
            'HBC_Cap_Vabc is logged from added voltage measurement blocks', ...
            'Vinj_abc is logged from series W6 voltage measurement blocks', ...
            'Idc_cap is computed as Cdc*dVdc/dt to avoid altering the DC-link electrical topology'} ...
        );
    report.recommendation = ['For a final plant-grade proxy, replace Idc_cap with a ', ...
        'direct DC-link current sensor if the resulting topology is verified unchanged.'];
end

function value = Srated_from_model(M)
    value = get_block_numeric(M, 'Load', 'ActivePower', 400e3);
end

function value = get_mw_numeric(mw, name, fallback)
    try
        value = double(getVariable(mw, name));
        if ~isscalar(value)
            value = fallback;
        end
    catch
        value = fallback;
    end
end

function value = get_block_numeric(M, blockName, paramName, fallback)
    blockPath = [M '/' blockName];
    try
        raw = get_param(blockPath, paramName);
    catch
        value = fallback;
        return;
    end
    value = str2double(raw);
    if ~isfinite(value)
        try
            value = double(getVariable(get_param(M, 'ModelWorkspace'), raw));
        catch
            value = fallback;
        end
    end
end

function value = get_param_if_exists(M, blockName, paramName)
    try
        value = get_param([M '/' blockName], paramName);
    catch
        value = '';
    end
end

function write_json_file(path, data)
    try
        txt = jsonencode(data, 'PrettyPrint', true);
    catch
        txt = jsonencode(data);
    end
    fid = fopen(path, 'w');
    assert(fid > 0, 'Could not open JSON output: %s', path);
    cleanup = onCleanup(@() fclose(fid));
    fprintf(fid, '%s', txt);
end

function rows = logged_or_nan_rows(out, name, nChannels, referenceRows)
    if has_logged_var(out, name)
        rows = orient_channels(out.get(name), nChannels);
    else
        rows = NaN(nChannels, size(referenceRows, 2));
    end
end

function tf = has_logged_var(out, name)
    try
        out.get(name);
        tf = true;
    catch
        tf = false;
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

function s = action_source(policyMode)
    if policyMode <= -1.5
        s = "trajectory_action";
    elseif policyMode >= 0.5
        s = "actor_action";
    else
        s = "rule_action";
    end
end

function c = condition_class(faultPu)
    if faultPu < 0.80
        c = "deep_lvrt";
    elseif faultPu < 1.0
        c = "shallow_lvrt";
    elseif faultPu <= 1.20
        c = "shallow_hvrt";
    else
        c = "high_hvrt";
    end
end

function z = window_zone(t, faultStart, faultClear, stopTime)
    if t < faultStart
        z = "prefault";
    elseif t < faultClear
        z = "fault";
    elseif t < stopTime - 0.005
        z = "recovery";
    else
        z = "tail";
    end
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
        'Position', [x0+95 y0+85 x0+185 y0+110], ...
        'VariableName', 'Vgrid_cmd_abc', 'SaveFormat', 'Array');

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

