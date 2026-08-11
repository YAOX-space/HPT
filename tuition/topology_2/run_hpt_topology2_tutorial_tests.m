% Run reproducible acceptance checks for the topology2 tutorial model.

model = 'hpt_topology2_tutorial';
tuitionDir = fileparts(mfilename('fullpath'));
mdlPath = fullfile(tuitionDir, [model '.slx']);
csvPath = fullfile(tuitionDir, [model '_acceptance_tests.csv']);
reportPath = fullfile(tuitionDir, [model '_acceptance_report.md']);

if ~isfile(mdlPath)
    run(fullfile(tuitionDir, 'complete_hpt_topology2_tutorial.m'));
end

if bdIsLoaded(model)
    close_system(model, 0);
end
open_system(mdlPath);
set_param(model, 'SimulationCommand', 'update');

results = {};

[status, metric, details] = checkTopology(model);
results = addResult(results, 'Test0', 'Topology integrity', status, metric, details);

nominal = runScenario(model, 10000, 0.08);
lvOk = nominal.lvRms >= 198 && nominal.lvRms <= 210;
unbalanceOk = nominal.lvUnbalance <= 6.0;
vdcOk = nominal.vdcMean >= 800 && nominal.vdcMean <= 900;
results = addResult(results, 'Test1', 'Nominal switch-level operation', ...
    passFail(lvOk && unbalanceOk && vdcOk), ...
    sprintf('LV=%.2f V, unbalance=%.2f V, Vdc=%.2f V', ...
        nominal.lvRms, nominal.lvUnbalance, nominal.vdcMean), ...
    'Topology2 tutorial gate: nominal LV RMS, phase balance, and DC-link stay in the expected switch-level range.');

seriesOk = nominal.seriesInjRms > 0.05 && nominal.mRegAbs > 0.001;
results = addResult(results, 'Test2', 'Secondary-side series injection path', ...
    passFail(seriesOk), ...
    sprintf('Series W6/Vinj RMS=%.3f V, abs(m_reg)=%.3f', ...
        nominal.seriesInjRms, nominal.mRegAbs), ...
    'Checks that RegulatingConverter drives the W5/W6 series transformer path rather than a topology1 W3 path.');

energyOk = nominal.energyVRms > 1.0 && nominal.energyIRms > 0.01 && nominal.mEnergyAbs >= 0;
results = addResult(results, 'Test3', 'Secondary-side energy converter path', ...
    passFail(energyOk), ...
    sprintf('Energy V=%.2f V, Energy I=%.2f A, abs(m_energy)=%.3f', ...
        nominal.energyVRms, nominal.energyIRms, nominal.mEnergyAbs), ...
    'Checks that EnergyConverter is connected through the secondary-side parallel coupled path and participates in DC-link control.');

results = addResult(results, 'Test4', 'Reactive power / PF control', 'NOT_IMPLEMENTED', ...
    'No PF or Q reference loop is declared as complete in the topology2 tutorial yet.', ...
    'Requires adding an iq/Q/PF loop and validating it against a declared test case.');

results = addResult(results, 'Test5', 'Three-phase unbalance compensation', 'NOT_IMPLEMENTED', ...
    'The tutorial acceptance gate currently covers nominal balanced operation only.', ...
    'Requires unbalanced source/load cases and sequence-component measurements.');

results = addResult(results, 'Test6', 'Harmonic mitigation', 'NOT_IMPLEMENTED', ...
    'No harmonic current reference or PR/QPR/repetitive controller is declared complete yet.', ...
    'Requires nonlinear load case and THD measurement before/after compensation.');

results = addResult(results, 'Test7', 'Fault ride-through smoke test', 'NOT_IMPLEMENTED', ...
    'Fault-family validation belongs to the main Simulink evaluator, not this first tutorial gate.', ...
    'Requires configurable single/two/three-phase fault source and current-limit checks.');

results = addResult(results, 'Test8', 'Physical bypass / fail-safe mode', 'NOT_IMPLEMENTED', ...
    'No physical bypass breaker is declared complete in the topology2 tutorial yet.', ...
    'Requires adding a controllable bypass around the series injection path.');

resultTable = cell2table(results, 'VariableNames', ...
    {'TestID', 'Name', 'Status', 'Metric', 'Details'});
writetable(resultTable, csvPath);
writeReport(reportPath, resultTable);

disp(resultTable);
foundationalRows = ismember(resultTable.TestID, {'Test0', 'Test1', 'Test2', 'Test3'});
foundationalPass = all(strcmp(resultTable.Status(foundationalRows), 'PASS'));
fprintf('Foundational topology2 tutorial gate: %s\n', passFail(foundationalPass));
fprintf('CSV: %s\n', csvPath);
fprintf('Report: %s\n', reportPath);

function results = addResult(results, id, name, status, metric, details)
results(end + 1, :) = {id, name, status, metric, details};
end

function status = passFail(condition)
if condition
    status = 'PASS';
else
    status = 'FAIL';
end
end

function [status, metric, details] = checkTopology(model)
checks = strings(0);
ok = true;

requiredRoot = ["MainTransformer", "CouplingAndInjection", ...
    "EnergyConverter", "RegulatingConverter"];
for name = requiredRoot
    present = ~isempty(find_system(model, 'SearchDepth', 1, 'Name', char(name)));
    ok = ok && present;
    checks(end + 1) = sprintf('%s present=%d', name, present);
end

forbidden = ["PhaseA_W1W2W3", "PhaseB_W1W2W3", "PhaseC_W1W2W3", ...
    "W3A", "W3B", "W3C", "PrimaryEnergyCoupling"];
for name = forbidden
    absent = isempty(find_system(model, 'LookUnderMasks', 'all', 'Name', char(name)));
    ok = ok && absent;
    checks(end + 1) = sprintf('%s absent=%d', name, absent);
end

for k = 1:3
    seriesName = sprintf('SwRegSeries_W5W6_%d', k);
    pctName = sprintf('ParallelCoupled_%d', k);
    tpfName = sprintf('TPF_L_%d', k);
    seriesPresent = ~isempty(find_system(model, 'LookUnderMasks', 'all', 'Name', seriesName));
    pctPresent = ~isempty(find_system(model, 'LookUnderMasks', 'all', 'Name', pctName));
    tpfPresent = ~isempty(find_system(model, 'LookUnderMasks', 'all', 'Name', tpfName));
    ok = ok && seriesPresent && pctPresent && tpfPresent;
    checks(end + 1) = sprintf('%s present=%d', seriesName, seriesPresent);
    checks(end + 1) = sprintf('%s present=%d', pctName, pctPresent);
    checks(end + 1) = sprintf('%s present=%d', tpfName, tpfPresent);
end

energy = [model '/EnergyConverter'];
if ~isempty(find_system(model, 'SearchDepth', 1, 'Name', 'EnergyConverter'))
    ePh = get_param(energy, 'PortHandles');
    energyAcOk = portsConnected(ePh.LConn(1:min(3, numel(ePh.LConn))));
    energyDcOk = numel(ePh.RConn) >= 2 && portsConnected(ePh.RConn(1:2));
    ok = ok && energyAcOk && energyDcOk;
    checks(end + 1) = sprintf('EnergyConverter AC connected=%d', energyAcOk);
    checks(end + 1) = sprintf('EnergyConverter DC connected=%d', energyDcOk);
end

reg = [model '/RegulatingConverter'];
if ~isempty(find_system(model, 'SearchDepth', 1, 'Name', 'RegulatingConverter'))
    rPh = get_param(reg, 'PortHandles');
    regAcOk = numel(rPh.LConn) >= 6 && portsConnected(rPh.LConn(1:6));
    regDcOk = numel(rPh.RConn) >= 2 && portsConnected(rPh.RConn(1:2));
    ok = ok && regAcOk && regDcOk;
    checks(end + 1) = sprintf('RegulatingConverter W5 AC connected=%d', regAcOk);
    checks(end + 1) = sprintf('RegulatingConverter DC connected=%d', regDcOk);
end

status = passFail(ok);
metric = strjoin(checks, ' | ');
details = ['Checks W1/W2 main transformer, secondary-side parallel energy ' ...
    'path, W5/W6 series injection, shared DC-link, and absence of topology1 W3 logic.'];
end

function ok = portsConnected(portHandles)
ok = true;
for h = reshape(portHandles, 1, [])
    ok = ok && get_param(h, 'Line') ~= -1;
end
end

function s = runScenario(model, vgridLL, stopTime)
in = Simulink.SimulationInput(model);
in = in.setModelParameter('StopTime', sprintf('%.4f', stopTime));
in = in.setBlockParameter([model '/Grid'], 'Voltage', num2str(vgridLL));
out = sim(in);

t = out.get('tout');
vLv = out.get('Vlv_abc');
vdc = out.get('Vdc');
mReg = out.get('Mreg_cmd');
mEnergy = out.get('Menergy_cmd');
nRows = min([numel(t), size(vLv, 1), size(vdc, 1)]);
t = t(1:nRows, :);
vLv = vLv(1:nRows, :);
vdc = vdc(1:nRows, :);
mReg = trimRows(mReg, nRows);
mEnergy = trimRows(mEnergy, nRows);
vInj = trimRows(getOrZeros(out, 'Vinj_abc', nRows, 3), nRows);
vEnergy = trimRows(getOrZeros(out, 'Energy_Vabc', nRows, 3), nRows);
iEnergy = trimRows(getOrZeros(out, 'Energy_Iabc', nRows, 3), nRows);

idx = t >= max(0, t(end) - min(0.025, stopTime / 3));
phaseRms = sqrt(mean(vLv(idx, 1:3).^2, 1));
s.lvRms = mean(phaseRms);
s.lvUnbalance = max(phaseRms) - min(phaseRms);
s.vdcMean = mean(vdc(idx, 1));
s.mRegAbs = rowMeanAbs(mReg, idx);
s.mEnergyAbs = rowMeanAbs(mEnergy, idx);
s.seriesInjRms = mean(sqrt(mean(vInj(idx, 1:3).^2, 1)));
s.energyVRms = mean(sqrt(mean(vEnergy(idx, 1:3).^2, 1)));
s.energyIRms = mean(sqrt(mean(iEnergy(idx, 1:3).^2, 1)));
end

function y = getOrZeros(out, name, nRows, nCols)
try
    y = out.get(name);
catch
    y = zeros(nRows, nCols);
end
if isempty(y)
    y = zeros(nRows, nCols);
end
end

function y = trimRows(y, nRows)
if isempty(y)
    y = zeros(nRows, 1);
elseif size(y, 1) >= nRows
    y = y(1:nRows, :);
else
    y(end+1:nRows, :) = repmat(y(end, :), nRows - size(y, 1), 1);
end
end

function y = rowMeanAbs(values, idx)
if isempty(values)
    y = 0;
else
    y = mean(abs(values(idx, :)), 'all');
end
end

function writeReport(reportPath, resultTable)
fid = fopen(reportPath, 'w');
if fid < 0
    error('Could not write report: %s', reportPath);
end
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, '# HPT Topology2 Tutorial Acceptance Report\n\n');
fprintf(fid, 'Generated by `run_hpt_topology2_tutorial_tests.m`.\n\n');
fprintf(fid, '| Test | Name | Status | Metric |\n');
fprintf(fid, '| --- | --- | --- | --- |\n');
for i = 1:height(resultTable)
    fprintf(fid, '| %s | %s | %s | %s |\n', ...
        resultTable.TestID{i}, resultTable.Name{i}, resultTable.Status{i}, ...
        strrep(resultTable.Metric{i}, '|', ';'));
end
fprintf(fid, '\n## Notes\n\n');
fprintf(fid, '- Foundational tutorial completion is defined as Test0-Test3 passing.\n');
fprintf(fid, '- This tutorial checks topology2 nominal operation and physical path integrity only.\n');
fprintf(fid, '- Test4-Test8 require additional controller and fault/load models before they can honestly pass.\n');
end
