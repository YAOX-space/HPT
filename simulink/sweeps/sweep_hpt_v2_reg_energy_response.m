% sweep_hpt_v2_reg_energy_response
% Small fixed-action calibration around one HPT per-case specialist.
%
% This is used after a per-case actor finds a regulating action that fixes
% LV voltage but depletes the DC link.  It sweeps the regulating bridge and
% energy bridge together so each specialist can receive a physical target.

clearvars -except hpt_sweep_topology hpt_sweep_grid hpt_sweep_reg_values hpt_sweep_energy_values;
close all;

if ~exist('hpt_sweep_topology', 'var')
    hpt_sweep_topology = "topology1";
end
if ~exist('hpt_sweep_grid', 'var')
    hpt_sweep_grid = 9000;
end
if ~exist('hpt_sweep_reg_values', 'var')
    hpt_sweep_reg_values = [0.65, 0.75, 0.85];
end
if ~exist('hpt_sweep_energy_values', 'var')
    hpt_sweep_energy_values = [-0.80, -0.40, 0.00, 0.40];
end
hpt_sweep_topology = string(hpt_sweep_topology);

rootDir = fileparts(fileparts(mfilename('fullpath')));
cases = {
    fullfile(rootDir, 'topology1'), 'build_hpt_v2_1to1_switchlevel', 'hpt_v2_1to1_switchlevel', 'topology1';
    fullfile(rootDir, 'topology2'), 'build_hpt_v2_topology2_paper', 'hpt_v2_topology2_paper', 'topology2';
};

targetPhaseRms = 207.0;
stopTime = 0.08;
settleStart = 0.05;
Ts = 20e-6;

oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));
rowCells = {};

for c = 1:size(cases, 1)
    topology = string(cases{c, 4});
    if topology ~= hpt_sweep_topology
        continue;
    end
    cd(cases{c, 1});
    feval(cases{c, 2});
    M = cases{c, 3};
    for r = 1:numel(hpt_sweep_reg_values)
        for e = 1:numel(hpt_sweep_energy_values)
            rowCells{end+1} = run_fixed_pair_case(M, topology, hpt_sweep_grid, ...
                targetPhaseRms, hpt_sweep_reg_values(r), ...
                hpt_sweep_energy_values(e), stopTime, settleStart, Ts); %#ok<SAGROW>
        end
    end
    close_system(M, 0);
end

rows = [rowCells{:}];
outDir = fullfile(rootDir, '..', '..', 'lab', 'results', ...
    'hpt_v2_sac_reg_energy_sweep');
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
safeName = regexprep(sprintf('%s_%gV', hpt_sweep_topology, hpt_sweep_grid), ...
    '[^A-Za-z0-9_]+', '_');
outMat = fullfile(outDir, ['hpt_v2_reg_energy_sweep_' char(safeName) '_' stamp '.mat']);
outCsv = fullfile(outDir, ['hpt_v2_reg_energy_sweep_' char(safeName) '_' stamp '.csv']);
save(outMat, 'rows', 'targetPhaseRms', 'hpt_sweep_topology', ...
    'hpt_sweep_grid', 'hpt_sweep_reg_values', 'hpt_sweep_energy_values');
writetable(struct2table(rows), outCsv);

fprintf('HPT fixed reg/energy switch-level sweep complete.\n');
fprintf('%-10s %8s %8s %8s %10s %9s %9s %9s\n', ...
    'topology', 'grid', 'regD', 'engD', 'LV_RMS', 'VdcMean', 'VdcMin', 'score');
for i = 1:numel(rows)
    fprintf('%-10s %8.0f %8.3f %8.3f %10.3f %9.3f %9.3f %9.3f\n', ...
        rows(i).topology, rows(i).grid_V, rows(i).cmd_m_reg_d, ...
        rows(i).cmd_m_energy_d, rows(i).lv_rms_mean, rows(i).vdc_mean, ...
        rows(i).vdc_min, rows(i).score);
end
fprintf('Saved CSV: %s\n', outCsv);

function row = run_fixed_pair_case(M, topology, gridVoltage, targetPhaseRms, ...
    mRegD, mEnergyD, stopTime, settleStart, Ts)

    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    in = in.setBlockParameter([M '/Grid'], 'Voltage', num2str(gridVoltage));
    in = in.setVariable('hpt_sac_enable', 1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_energy_enable', 1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_policy_mode', -1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_reg_d', mRegD, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_reg_q', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_energy_d', mEnergyD, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_energy_q', 0.0, 'Workspace', M);
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
    tailStart = max(1, round(size(actRows, 2) * 0.7));
    vdcTailStart = max(1, round(size(Vdc, 1) * 0.7));
    lvMean = mean(phaseRms);
    vdcMean = mean(Vdc(vdcTailStart:end, 1));
    vdcMin = min(Vdc(:, 1));
    score = abs(lvMean - targetPhaseRms) + max(0, 760 - vdcMean) / 4 + ...
        max(0, max(phaseRms) - min(phaseRms) - 6.0);

    row = struct();
    row.model = string(M);
    row.topology = string(topology);
    row.grid_V = gridVoltage;
    row.grid_pu = gridVoltage / 10000.0;
    row.cmd_m_reg_d = mRegD;
    row.cmd_m_reg_q = 0.0;
    row.cmd_m_energy_d = mEnergyD;
    row.cmd_m_energy_q = 0.0;
    row.lv_rms_mean = lvMean;
    row.lv_unbalance = max(phaseRms) - min(phaseRms);
    row.vdc_mean = vdcMean;
    row.vdc_min = vdcMin;
    row.vdc_max = max(Vdc(:, 1));
    row.score = score;
    row.obs_dim = size(obsRows, 1);
    row.action_dim = size(actRows, 1);
    row.action_max_abs = max(abs(actRows), [], 'all');
    row.reg_d_mean = mean(actRows(1, tailStart:end));
    row.reg_q_mean = mean(actRows(2, tailStart:end));
    row.energy_d_mean = mean(actRows(3, tailStart:end));
    row.energy_q_mean = mean(actRows(4, tailStart:end));
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

