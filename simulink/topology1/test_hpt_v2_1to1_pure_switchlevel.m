% test_hpt_v2_1to1_pure_switchlevel
% Regression checks for the final physical 1:1 switch-level HPT model.

clearvars;
close all;

build_hpt_v2_1to1_switchlevel;
M = 'hpt_v2_1to1_switchlevel';
Ts = 20e-6;

for forbidden = ["AvgSeries", "Debug_DC", "switch_source_blend", "fund_lp"]
    hits = find_system(M, 'RegExp', 'on', 'Name', ['.*' char(forbidden) '.*']);
    assert(isempty(hits), 'Forbidden non-physical/debug block remains: %s', forbidden);
end

gridVoltages = [9000 10000 11000];
lvMean = zeros(size(gridVoltages));
lvUnbalance = zeros(size(gridVoltages));
vdcMean = zeros(size(gridVoltages));

for k = 1:numel(gridVoltages)
    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', '0.08');
    in = in.setBlockParameter([M '/Grid'], 'Voltage', num2str(gridVoltages(k)));
    out = sim(in);

    Vlv = out.get('Vlv_abc');
    Vdc = out.get('Vdc');

    t = (0:size(Vlv, 1)-1)' * Ts;
    idx = t > 0.05;
    phaseRms = sqrt(mean(Vlv(idx, 1:3).^2, 1));

    lvMean(k) = mean(phaseRms);
    lvUnbalance(k) = max(phaseRms) - min(phaseRms);
    vdcMean(k) = mean(Vdc(round(end*0.7):end, 1));

    assert(lvMean(k) >= 200 && lvMean(k) <= 206, ...
        'LV RMS out of regulated range for grid %.0f V: %.3f V', ...
        gridVoltages(k), lvMean(k));
    assert(lvUnbalance(k) <= 2.0, ...
        'LV phase unbalance too high for grid %.0f V: %.3f V', ...
        gridVoltages(k), lvUnbalance(k));
    assert(vdcMean(k) >= 800 && vdcMean(k) <= 880, ...
        'DC link out of range for grid %.0f V: %.3f V', ...
        gridVoltages(k), vdcMean(k));
end

fprintf('Pure switch-level HPT regression passed.\\n');
fprintf('Grid[V]  LV_RMS[V]  LV_unbalance[V]  Vdc[V]\\n');
for k = 1:numel(gridVoltages)
    fprintf('%7.0f  %9.3f  %15.3f  %7.3f\\n', ...
        gridVoltages(k), lvMean(k), lvUnbalance(k), vdcMean(k));
end
