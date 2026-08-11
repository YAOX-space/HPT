% Run reproducible acceptance checks for the topology1 tutorial model.

model = 'hpt_topology1_tutorial';
tuitionDir = fileparts(mfilename('fullpath'));
mdlPath = fullfile(tuitionDir, [model '.slx']);
csvPath = fullfile(tuitionDir, [model '_acceptance_tests.csv']);
reportPath = fullfile(tuitionDir, [model '_acceptance_report.md']);

if ~isfile(mdlPath)
    error('Tutorial model not found: %s', mdlPath);
end

if bdIsLoaded(model)
    close_system(model, 0);
end
open_system(mdlPath);
set_param(model, 'SimulationCommand', 'update');

results = {};

[status, metric, details] = checkTopology(model);
results = addResult(results, 'Test0', 'Topology integrity', status, metric, details);

nominal = runScenario(model, 10000, true, true, 0, 0, 0.35);
nominalErrPct = 100 * abs(nominal.lvRms - nominal.vlvRef) / nominal.vlvRef;
if nominalErrPct < 5
    status = 'PASS';
else
    status = 'FAIL';
end
results = addResult(results, 'Test1A', 'Nominal active operation', status, ...
    sprintf('LV=%.2f V, err=%.2f%%, Vdc=%.2f V', nominal.lvRms, nominalErrPct, nominal.vdcFinal), ...
    'Active voltage and Vdc regulators enabled at nominal grid voltage.');

passive = runScenario(model, 10000, false, false, 0, 0, 0.20);
passiveErrPct = 100 * abs(passive.lvRms - passive.vlvRef) / passive.vlvRef;
if passiveErrPct < 10
    status = 'PASS';
else
    status = 'FAIL';
end
results = addResult(results, 'Test1B', 'Converter-zero passive fallback', status, ...
    sprintf('LV=%.2f V, err=%.2f%%, Vdc=%.2f V', passive.lvRms, passiveErrPct, passive.vdcFinal), ...
    'This checks whether zero converter commands behave like a conventional transformer. A fail means a physical bypass switch is still needed.');

gridVals = [9000 10000 11000];
lvRows = strings(1, numel(gridVals));
vdcRows = strings(1, numel(gridVals));
lvOk = true;
vdcOk = true;
for k = 1:numel(gridVals)
    s = runScenario(model, gridVals(k), true, true, 0, 0, 0.35);
    lvErrPct = 100 * abs(s.lvRms - s.vlvRef) / s.vlvRef;
    lvRows(k) = sprintf('%.0fVgrid: LV %.2f V err %.2f%% m_reg %.3f', ...
        gridVals(k), s.lvRms, lvErrPct, s.mRegFinal);
    vdcPu = s.vdcFinal / s.vdcRef;
    vdcRows(k) = sprintf('%.0fVgrid: Vdc %.2f V %.3f pu m_energy %.3f', ...
        gridVals(k), s.vdcFinal, vdcPu, s.mEnergyFinal);
    lvOk = lvOk && lvErrPct < 5;
    vdcOk = vdcOk && vdcPu >= 0.85 && vdcPu <= 1.15;
end

results = addResult(results, 'Test2', 'Sag/swell voltage regulation', passFail(lvOk), ...
    strjoin(lvRows, ' | '), 'Tutorial gate: LV RMS phase-voltage error below 5% for 0.9/1.0/1.1 pu grid voltage.');

results = addResult(results, 'Test3', 'DC-link voltage control', passFail(vdcOk), ...
    strjoin(vdcRows, ' | '), 'Tutorial gate: Vdc remains within 0.85-1.15 pu for the same voltage-regulation cases.');

results = addResult(results, 'Test4', 'Reactive power / PF control', 'NOT_IMPLEMENTED', ...
    'No PF or Q reference loop in the tutorial controller yet.', ...
    'Requires adding an iq/Q/PF loop in EnergyConverter control.');

results = addResult(results, 'Test5', 'Three-phase unbalance compensation', 'NOT_IMPLEMENTED', ...
    'RegulatingConverter currently uses one scalar m_reg for all phases.', ...
    'Requires per-phase or sequence-component voltage injection and unbalanced source/load cases.');

results = addResult(results, 'Test6', 'Harmonic mitigation', 'NOT_IMPLEMENTED', ...
    'No harmonic current reference or PR/QPR/repetitive controller is present yet.', ...
    'Requires nonlinear load case and THD measurement before/after compensation.');

results = addResult(results, 'Test7', 'Fault ride-through smoke test', 'NOT_IMPLEMENTED', ...
    'Balanced sag is covered by Test2; asymmetrical fault cases are not modeled yet.', ...
    'Requires configurable single/two/three-phase fault source and current-limit checks.');

results = addResult(results, 'Test8', 'Passive fallback with bypass', 'NOT_IMPLEMENTED', ...
    'Zero-command behavior is measured in Test1B, but no physical bypass breaker exists.', ...
    'Requires adding a controllable bypass around the series injection path.');

resultTable = cell2table(results, 'VariableNames', ...
    {'TestID', 'Name', 'Status', 'Metric', 'Details'});
writetable(resultTable, csvPath);
writeReport(reportPath, resultTable);

disp(resultTable);
foundationalRows = ismember(resultTable.TestID, {'Test0', 'Test1A', 'Test2', 'Test3'});
foundationalPass = all(strcmp(resultTable.Status(foundationalRows), 'PASS'));
fprintf('Foundational tutorial gate: %s\n', passFail(foundationalPass));
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
et = [model '/ElectromagneticTransformer'];
energy = [model '/EnergyConverter'];
checks = strings(0);
ok = true;

if isempty(find_system(model, 'SearchDepth', 1, 'Name', 'ElectromagneticTransformer'))
    ok = false;
    checks(end + 1) = 'ElectromagneticTransformer missing';
else
    checks(end + 1) = 'ElectromagneticTransformer present';
end

if ~isempty(find_system(model, 'SearchDepth', 1, 'Name', 'PrimaryEnergyCoupling'))
    ok = false;
    checks(end + 1) = 'old PrimaryEnergyCoupling still present';
else
    checks(end + 1) = 'old PrimaryEnergyCoupling removed';
end

if ~isempty(find_system(model, 'SearchDepth', 1, 'Name', 'ElectromagneticTransformer'))
    etPh = get_param(et, 'PortHandles');
    ok = ok && numel(etPh.LConn) == 3 && numel(etPh.RConn) >= 6;
    checks(end + 1) = sprintf('ET connection ports L=%d R=%d', numel(etPh.LConn), numel(etPh.RConn));
    if numel(etPh.RConn) >= 6
        secondaryOk = portsConnectTo(etPh.RConn(1:3), 'MeasLV');
        w3Ok = portsConnectTo(etPh.RConn(4:6), 'EnergyConverter');
        ok = ok && secondaryOk && w3Ok;
        checks(end + 1) = sprintf('secondary 1/2/3 -> MeasLV=%d', secondaryOk);
        checks(end + 1) = sprintf('W3A/W3B/W3C -> EnergyConverter=%d', w3Ok);
    end
    for phase = ["PhaseA_W1W2W3", "PhaseB_W1W2W3", "PhaseC_W1W2W3"]
        blk = [et '/' char(phase)];
        if isempty(find_system(et, 'SearchDepth', 1, 'Name', char(phase))) || ...
                ~strcmp(get_param(blk, 'ThreeWindings'), 'on')
            ok = false;
            checks(end + 1) = sprintf('%s not enabled as three-winding', phase);
        else
            checks(end + 1) = sprintf('%s W3 enabled', phase);
        end
    end
end

if isempty(find_system(model, 'SearchDepth', 1, 'Name', 'EnergyConverter'))
    ok = false;
    checks(end + 1) = 'EnergyConverter missing';
else
    ePh = get_param(energy, 'PortHandles');
    acConnected = true;
    for k = 1:min(3, numel(ePh.LConn))
        acConnected = acConnected && get_param(ePh.LConn(k), 'Line') ~= -1;
    end
    ok = ok && acConnected;
    checks(end + 1) = sprintf('EnergyConverter AC ports connected=%d', acConnected);
end

status = passFail(ok);
metric = strjoin(checks, ' | ');
details = 'Checks W1/W2/W3 visibility, old proxy removal, and EnergyConverter AC connection.';
end

function ok = portsConnectTo(portHandles, expectedBlockName)
ok = true;
for h = reshape(portHandles, 1, [])
    lineHandle = get_param(h, 'Line');
    if lineHandle == -1
        ok = false;
        return;
    end
    dstBlocks = get_param(lineHandle, 'DstBlockHandle');
    dstNames = strings(1, numel(dstBlocks));
    for k = 1:numel(dstBlocks)
        try
            dstNames(k) = string(get_param(dstBlocks(k), 'Name'));
        catch
            dstNames(k) = "";
        end
    end
    if ~any(dstNames == expectedBlockName)
        ok = false;
        return;
    end
end
end

function s = runScenario(model, vgridLL, vregAuto, energyAuto, mRegManual, mEnergyManual, stopTime)
mws = get_param(model, 'ModelWorkspace');
assignin(mws, 'Vgrid_LL', vgridLL);
assignin(mws, 'hpt_vreg_auto', double(vregAuto));
assignin(mws, 'hpt_energy_auto', double(energyAuto));
assignin(mws, 'm_reg_manual', mRegManual);
assignin(mws, 'm_energy_manual', mEnergyManual);

in = Simulink.SimulationInput(model);
in = in.setModelParameter('StopTime', sprintf('%.4f', stopTime));
out = sim(in);

t = out.get('tout');
vLv = out.get('Vlv_abc');
vdc = out.get('Vdc');
mReg = out.get('m_reg_cmd');
mEnergy = out.get('m_energy_cmd');

idx = t >= max(0, t(end) - min(0.08, stopTime / 3));
s.lvRms = mean(sqrt(sum(vLv(idx, 1:3).^2, 2) / 3));
s.vdcFinal = vdc(end);
s.mRegFinal = mReg(end);
s.mEnergyFinal = mEnergy(end);
s.vlvRef = getVariable(mws, 'Vlv_ref_phase');
s.vdcRef = getVariable(mws, 'Vdc_ref');
end

function writeReport(reportPath, resultTable)
fid = fopen(reportPath, 'w');
if fid < 0
    error('Could not write report: %s', reportPath);
end
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, '# HPT Topology1 Tutorial Acceptance Report\n\n');
fprintf(fid, 'Generated by `run_hpt_topology1_tutorial_tests.m`.\n\n');
fprintf(fid, '| Test | Name | Status | Metric |\n');
fprintf(fid, '| --- | --- | --- | --- |\n');
for i = 1:height(resultTable)
    fprintf(fid, '| %s | %s | %s | %s |\n', ...
        resultTable.TestID{i}, resultTable.Name{i}, resultTable.Status{i}, ...
        strrep(resultTable.Metric{i}, '|', ';'));
end
fprintf(fid, '\n## Notes\n\n');
fprintf(fid, '- Foundational tutorial completion is defined as Test0, Test1A, Test2, and Test3 passing.\n');
fprintf(fid, '- Test1B is reported separately because converter-zero behavior is not the same as a physical bypass.\n');
fprintf(fid, '- Test4-Test8 require additional controller and fault/load models before they can honestly pass.\n');
end
