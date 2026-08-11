% sweep_hpt_v2_fault_fixed_reg_response
% Compact fixed-action fault-transition sweep for both HPT topologies.
%
% This script collects switch-level dynamic response data for learned-proxy
% training.  The controller is put in fixed-command mode; HPTSAC_action logs
% the projected/effective modulation actually sent to the regulating bridge.

clearvars;
close all;

rootDir = fileparts(fileparts(mfilename('fullpath')));
oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));

cases = {
    fullfile(rootDir, 'topology1'), 'build_hpt_v2_1to1_switchlevel', 'hpt_v2_1to1_switchlevel', 'topology1', 'Zg';
    fullfile(rootDir, 'topology2'), 'build_hpt_v2_topology2_paper', 'hpt_v2_topology2_paper', 'topology2', 'Source_RL';
};

faults = {
    'sag_0p90', 0.90;
    'swell_1p10', 1.10;
};
regDValues = [-0.60 -0.40 -0.20 0.00 0.20 0.40 0.60];

targetPhaseRms = 207.0;
nominalGridVoltage = 10000;
faultStart = 0.035;
faultClear = 0.095;
stopTime = 0.16;
Ts = 20e-6;

rowCells = {};
for c = 1:size(cases, 1)
    cd(cases{c, 1});
    feval(cases{c, 2});
    M = cases{c, 3};
    topology = cases{c, 4};
    sourceBranch = cases{c, 5};
    replace_grid_with_programmable_source(M, sourceBranch, nominalGridVoltage, ...
        1.0, faultStart, faultClear, stopTime);

    for f = 1:size(faults, 1)
        faultName = faults{f, 1};
        faultPu = faults{f, 2};
        configure_programmable_grid(M, nominalGridVoltage, faultPu, ...
            faultStart, faultClear, stopTime);
        rowCells{end+1} = run_case(M, topology, faultName, faultPu, "baseline", ...
            0.0, 0.0, targetPhaseRms, stopTime, Ts, faultStart, faultClear); %#ok<SAGROW>
        for regD = regDValues
            rowCells{end+1} = run_case(M, topology, faultName, faultPu, "fixed_reg_d", ...
                1.0, regD, targetPhaseRms, stopTime, Ts, faultStart, faultClear); %#ok<SAGROW>
        end
    end
    close_system(M, 0);
end

rows = [rowCells{:}];
outDir = fullfile(rootDir, '..', '..', 'lab', 'results', 'hpt_v2_sac_fault_fixed_reg_sweep');
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
outMat = fullfile(outDir, ['hpt_v2_fault_fixed_reg_sweep_' stamp '.mat']);
outCsv = fullfile(outDir, ['hpt_v2_fault_fixed_reg_sweep_' stamp '.csv']);
save(outMat, 'rows', 'targetPhaseRms', 'nominalGridVoltage', ...
    'faultStart', 'faultClear', 'stopTime', 'regDValues');
writetable(struct2table(rows), outCsv);

fprintf('HPT fault fixed-reg sweep complete.\n');
fprintf('%-10s %-10s %-12s %8s %10s %10s %10s %9s %9s\n', ...
    'topology', 'fault', 'mode', 'regD', 'LV_fault', 'LV_recov', ...
    'LV_peak', 'VdcMin', 'max|a|');
for i = 1:numel(rows)
    fprintf('%-10s %-10s %-12s %8.3f %10.3f %10.3f %10.3f %9.3f %9.3f\n', ...
        rows(i).topology, rows(i).fault, rows(i).mode, rows(i).raw_m_reg_d, ...
        rows(i).lv_fault_rms_mean, rows(i).lv_recovery_rms_mean, ...
        rows(i).lv_peak_rms, rows(i).vdc_min, rows(i).action_max_abs);
end
fprintf('Saved MAT: %s\n', outMat);
fprintf('Saved CSV: %s\n', outCsv);

function row = run_case(M, topology, faultName, faultPu, mode, sacEnable, regD, ...
    targetPhaseRms, stopTime, Ts, faultStart, faultClear)

    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    in = in.setVariable('hpt_sac_enable', sacEnable, 'Workspace', M);
    in = in.setVariable('hpt_sac_energy_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_policy_mode', -1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_reg_d', regD, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_reg_q', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_energy_d', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_energy_q', 0.0, 'Workspace', M);
    out = sim(in);

    Vlv = out.get('Vlv_abc');
    Vdc = out.get('Vdc');
    act = out.get('HPTSAC_action');

    t = (0:size(Vlv, 1)-1)' * Ts;
    phaseRmsInst = sqrt(mean(Vlv(:, 1:3).^2, 2));
    faultIdx = t > (faultStart + 0.025) & t < (faultClear - 0.005);
    recoveryIdx = t > (faultClear + 0.035) & t < (stopTime - 0.005);
    activeIdx = t > faultStart & t < stopTime;
    phaseRmsFault = sqrt(mean(Vlv(faultIdx, 1:3).^2, 1));
    actRows = orient_channels(act, 4);
    steadyStart = max(1, round(size(actRows, 2) * 0.7));

    row = struct();
    row.model = string(M);
    row.topology = string(topology);
    row.fault = string(faultName);
    row.fault_pu = faultPu;
    row.grid_pu = faultPu;
    row.mode = string(mode);
    row.target_phase_rms = targetPhaseRms;
    row.fault_start = faultStart;
    row.fault_clear = faultClear;
    row.stop_time = stopTime;
    if sacEnable <= 0.5
        row.action_semantics = "controller_disabled_fault_sweep";
    else
        row.action_semantics = "fixed_fault_command_through_controller_projection";
    end
    row.action_raw_available = true;
    row.action_projected_available = true;
    row.action_effective_available = true;
    row.action_raw_source = "fixed_command";
    row.action_projected_source = "HPTSAC_action";
    row.action_effective_source = "HPTSAC_action";
    row.raw_m_reg_d = regD;
    row.raw_m_reg_q = 0.0;
    row.raw_m_energy_d = 0.0;
    row.raw_m_energy_q = 0.0;
    row.lv_fault_rms_mean = mean(phaseRmsInst(faultIdx));
    row.lv_recovery_rms_mean = mean(phaseRmsInst(recoveryIdx));
    row.lv_peak_rms = max(phaseRmsInst(activeIdx));
    row.lv_min_rms = min(phaseRmsInst(activeIdx));
    row.lv_pu_mean = row.lv_fault_rms_mean / targetPhaseRms;
    row.lv_recovery_pu_mean = row.lv_recovery_rms_mean / targetPhaseRms;
    row.lv_peak_pu = row.lv_peak_rms / targetPhaseRms;
    row.lv_min_pu = row.lv_min_rms / targetPhaseRms;
    row.lv_unbalance = max(phaseRmsFault) - min(phaseRmsFault);
    row.vdc_mean = mean(Vdc(round(end*0.7):end, 1));
    row.vdc_min = min(Vdc(:, 1));
    row.vdc_max = max(Vdc(:, 1));
    row.action_max_abs = max(abs(actRows), [], 'all');
    row.reg_d_mean = mean(actRows(1, steadyStart:end));
    row.reg_q_mean = mean(actRows(2, steadyStart:end));
    row.energy_d_mean = mean(actRows(3, steadyStart:end));
    row.energy_q_mean = mean(actRows(4, steadyStart:end));
    row.projected_m_reg_d_mean = row.reg_d_mean;
    row.projected_m_reg_q_mean = row.reg_q_mean;
    row.projected_m_energy_d_mean = row.energy_d_mean;
    row.projected_m_energy_q_mean = row.energy_q_mean;
    row.effective_m_reg_d_mean = row.reg_d_mean;
    row.effective_m_reg_q_mean = row.reg_q_mean;
    row.effective_m_energy_d_mean = row.energy_d_mean;
    row.effective_m_energy_q_mean = row.energy_q_mean;
end

function replace_grid_with_programmable_source(M, sourceBranch, nominalGridVoltage, ...
    faultPu, faultStart, faultClear, stopTime)

    grid = [M '/Grid'];
    pos = get_param(grid, 'Position');
    delete_block(grid);
    add_block('powerlib/Electrical Sources/Three-Phase Programmable Voltage Source', ...
        grid, 'Position', pos);
    configure_programmable_grid(M, nominalGridVoltage, faultPu, faultStart, faultClear, stopTime);
    for k = 1:3
        connect_if_free(M, ph(grid, 'RConn', k), ...
            ph([M '/' sourceBranch], 'LConn', k));
    end
end

function configure_programmable_grid(M, nominalGridVoltage, faultPu, faultStart, faultClear, stopTime)
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

function y = orient_channels(x, nChannels)
    if size(x, 1) == nChannels
        y = x;
    elseif size(x, 2) == nChannels
        y = x';
    else
        y = reshape(x, nChannels, []);
    end
end

