% sweep_hpt_v2_topology2_fault_fixed_reg
% Fixed-action dynamic sag/swell sweep for topology2.  This identifies which
% regulating-bridge d-axis commands keep the DC link alive during the same
% programmable-source fault window used by test_hpt_v2_sac_fault_transition.

clearvars;
close all;

rootDir = fileparts(fileparts(mfilename('fullpath')));
topologyDir = fullfile(rootDir, 'topology2');
oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));

cd(topologyDir);
build_hpt_v2_topology2_paper;
M = 'hpt_v2_topology2_paper';

targetPhaseRms = 207.0;
nominalGridVoltage = 10000;
faultStart = 0.035;
faultClear = 0.095;
stopTime = 0.16;
Ts = 20e-6;
replace_grid_with_programmable_source(M, 'Source_RL', nominalGridVoltage, ...
    1.0, faultStart, faultClear, stopTime);

faults = {
    'sag_0p90', 0.90;
    'swell_1p10', 1.10;
};
regDValues = [-0.60 -0.40 -0.20 0.00 0.20 0.40 0.45 0.50 0.55 0.60];

rowCells = {};
for f = 1:size(faults, 1)
    faultName = faults{f, 1};
    faultPu = faults{f, 2};
    configure_programmable_grid(M, nominalGridVoltage, faultPu, ...
        faultStart, faultClear, stopTime);
    rowCells{end+1} = run_case(M, faultName, faultPu, "baseline", 0.0, 0.0, ...
        targetPhaseRms, stopTime, Ts, faultStart, faultClear); %#ok<SAGROW>
    for regD = regDValues
        rowCells{end+1} = run_case(M, faultName, faultPu, "fixed_reg_d", 1.0, regD, ...
            targetPhaseRms, stopTime, Ts, faultStart, faultClear); %#ok<SAGROW>
    end
end
close_system(M, 0);

rows = [rowCells{:}];
outDir = fullfile(rootDir, '..', '..', 'lab', 'results', 'hpt_v2_topology2_fault_fixed_reg_sweep');
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
outMat = fullfile(outDir, ['topology2_fault_fixed_reg_sweep_' stamp '.mat']);
outCsv = fullfile(outDir, ['topology2_fault_fixed_reg_sweep_' stamp '.csv']);
save(outMat, 'rows', 'targetPhaseRms', 'nominalGridVoltage', ...
    'faultStart', 'faultClear', 'stopTime', 'regDValues');
writetable(struct2table(rows), outCsv);

fprintf('Topology2 fixed-reg dynamic sweep complete.\n');
fprintf('%-10s %-12s %8s %10s %10s %10s %9s %9s\n', ...
    'fault', 'mode', 'regD', 'LV_fault', 'LV_recov', 'LV_peak', 'VdcMin', 'VdcMean');
for i = 1:numel(rows)
    fprintf('%-10s %-12s %8.3f %10.3f %10.3f %10.3f %9.3f %9.3f\n', ...
        rows(i).fault, rows(i).mode, rows(i).reg_d, rows(i).lv_fault_rms_mean, ...
        rows(i).lv_recovery_rms_mean, rows(i).lv_peak_rms, rows(i).vdc_min, rows(i).vdc_mean);
end
fprintf('Saved MAT: %s\n', outMat);
fprintf('Saved CSV: %s\n', outCsv);

function row = run_case(M, faultName, faultPu, mode, sacEnable, regD, ...
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
    t = (0:size(Vlv, 1)-1)' * Ts;
    phaseRmsInst = sqrt(mean(Vlv(:, 1:3).^2, 2));
    faultIdx = t > (faultStart + 0.025) & t < (faultClear - 0.005);
    recoveryIdx = t > (faultClear + 0.035) & t < (stopTime - 0.005);

    row = struct();
    row.model = string(M);
    row.fault = string(faultName);
    row.fault_pu = faultPu;
    row.mode = string(mode);
    row.reg_d = regD;
    row.lv_fault_rms_mean = mean(phaseRmsInst(faultIdx));
    row.lv_recovery_rms_mean = mean(phaseRmsInst(recoveryIdx));
    row.lv_peak_rms = max(phaseRmsInst(t > faultStart & t < stopTime));
    row.lv_min_rms = min(phaseRmsInst(t > faultStart & t < stopTime));
    row.lv_abs_recovery_err = abs(row.lv_recovery_rms_mean - targetPhaseRms);
    row.vdc_mean = mean(Vdc(round(end*0.7):end, 1));
    row.vdc_min = min(Vdc(:, 1));
    row.vdc_max = max(Vdc(:, 1));
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

