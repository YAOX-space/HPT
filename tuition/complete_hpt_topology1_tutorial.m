% Complete the topology1 tutorial model so the energy converter is connected
% to the main transformer's W3 tertiary/energy winding.

model = 'hpt_topology1_tutorial';
tuitionDir = fileparts(mfilename('fullpath'));
mdlPath = fullfile(tuitionDir, [model '.slx']);
backupPath = fullfile(tuitionDir, [model '_before_step16_w3_alignment.slx']);

fprintf('Tutorial directory: %s\n', tuitionDir);
fprintf('Tutorial model path: %s\n', mdlPath);

if ~isfile(mdlPath)
    error('Tutorial model not found: %s', mdlPath);
end

if ~isfile(backupPath)
    copyfile(mdlPath, backupPath);
end

if bdIsLoaded(model)
    close_system(model, 0);
end
open_system(mdlPath);
open_system(model);

if ~isempty(find_system(model, 'SearchDepth', 1, 'Name', 'main')) && ...
        isempty(find_system(model, 'SearchDepth', 1, 'Name', 'ElectromagneticTransformer'))
    set_param([model '/main'], 'Name', 'ElectromagneticTransformer');
end

et = [model '/ElectromagneticTransformer'];
if isempty(find_system(model, 'SearchDepth', 1, 'Name', 'ElectromagneticTransformer'))
    error('ElectromagneticTransformer subsystem is missing.');
end

phaseOld = {'Main_W1W2_1', 'Main_W1W2_2', 'Main_W1W2_3'};
phaseNew = {'PhaseA_W1W2W3', 'PhaseB_W1W2W3', 'PhaseC_W1W2W3'};

for k = 1:numel(phaseOld)
    oldPath = [et '/' phaseOld{k}];
    if ~isempty(find_system(et, 'SearchDepth', 1, 'Name', phaseOld{k})) && ...
            isempty(find_system(et, 'SearchDepth', 1, 'Name', phaseNew{k}))
        set_param(oldPath, 'Name', phaseNew{k});
    end
end

for k = 1:numel(phaseNew)
    blk = [et '/' phaseNew{k}];
    if isempty(find_system(et, 'SearchDepth', 1, 'Name', phaseNew{k}))
        error('Missing transformer phase block: %s', blk);
    end
    set_param(blk, ...
        'ThreeWindings', 'on', ...
        'winding3', '[Vaux_LL/sqrt(3),0.005,0.02]', ...
        'Measurements', 'None');
end

if isempty(find_system(et, 'SearchDepth', 1, 'Name', 'W3_neutral_ground'))
    add_block([et '/W2_neutral_ground'], [et '/W3_neutral_ground'], ...
        'MakeNameUnique', 'off', 'Position', [650 370 680 400]);
end

w3Ports = {'W3A', 'W3B', 'W3C'};
sourcePort = [et '/1'];
for k = 1:numel(w3Ports)
    portPath = [et '/' w3Ports{k}];
    if isempty(find_system(et, 'SearchDepth', 1, 'Name', w3Ports{k}))
        add_block(sourcePort, portPath, 'MakeNameUnique', 'off');
    end
    set_param(portPath, ...
        'Side', 'Right', ...
        'Orientation', 'right', ...
        'Port', num2str(3 + k), ...
        'Position', [395 320 + 30*k 425 334 + 30*k]);
end
for k = 1:numel(w3Ports)
    set_param([et '/' w3Ports{k}], 'Side', 'Right', 'Orientation', 'right');
end

% Keep the external transformer ports in a readable and deterministic order:
% secondary 1/2/3 first, then tertiary energy winding W3A/W3B/W3C.
rightPortNames = {'1', '2', '3', 'W3A', 'W3B', 'W3C'};
for k = 1:numel(rightPortNames)
    set_param([et '/' rightPortNames{k}], ...
        'Side', 'Right', ...
        'Orientation', 'right', ...
        'Port', num2str(3 + k), ...
        'Position', [395 70 + 45 * (k - 1) 425 84 + 45 * (k - 1)]);
end

% Connect each transformer's W3 phase terminal to a W3 external port, and
% ground the corresponding W3 neutral terminal in star configuration.
w3Ground = [et '/W3_neutral_ground'];
for k = 1:numel(phaseNew)
    blk = [et '/' phaseNew{k}];
    ph = get_param(blk, 'PortHandles');
    if numel(ph.RConn) < 4
        error('%s does not expose W3 ports after enabling ThreeWindings.', blk);
    end
    clearPortLine(ph.RConn(3));
    clearPortLine(ph.RConn(4));
    portPath = [et '/' w3Ports{k}];
    pph = get_param(portPath, 'PortHandles');
    clearPortLine(pph.RConn(1));
    add_line(et, ph.RConn(3), pph.RConn(1), 'autorouting', 'on');
    gph = get_param(w3Ground, 'PortHandles');
    add_line(et, ph.RConn(4), gph.LConn(1), 'autorouting', 'on');
end

% Remove the old external proxy coupling and connect the energy converter
% directly to the W3 ports of the main electromagnetic transformer.
energyPath = [model '/EnergyConverter'];
ePh = get_param(energyPath, 'PortHandles');
for k = 1:min(3, numel(ePh.LConn))
    clearPortLine(ePh.LConn(k));
end

oldCoupling = [model '/PrimaryEnergyCoupling'];
if ~isempty(find_system(model, 'SearchDepth', 1, 'Name', 'PrimaryEnergyCoupling'))
    oldPh = get_param(oldCoupling, 'PortHandles');
    for h = [oldPh.LConn(:); oldPh.RConn(:)]'
        clearPortLine(h);
    end
    delete_block(oldCoupling);
end

for k = 1:numel(w3Ports)
    set_param([et '/' w3Ports{k}], 'Side', 'Right', 'Orientation', 'right');
end
etPh = get_param(et, 'PortHandles');
if numel(etPh.RConn) < 6
    error('ElectromagneticTransformer does not expose the three W3 output ports.');
end

measPath = [model '/MeasLV'];
if isempty(find_system(model, 'SearchDepth', 1, 'Name', 'MeasLV'))
    error('MeasLV subsystem is missing.');
end
measPh = get_param(measPath, 'PortHandles');
for k = 1:3
    clearPortLine(etPh.RConn(k));
    clearPortLine(measPh.LConn(k));
    add_line(model, etPh.RConn(k), measPh.LConn(k), 'autorouting', 'on');
end

for k = 1:3
    clearPortLine(etPh.RConn(3 + k));
    clearPortLine(ePh.LConn(k));
    add_line(model, etPh.RConn(3 + k), ePh.LConn(k), 'autorouting', 'on');
end

% The corrected W3 connection changes the average DC-link dynamics, so retune
% the tutorial's simple proxy controller around the new operating point.
mws = get_param(model, 'ModelWorkspace');
assignin(mws, 'Vdc_ref', 875);
assignin(mws, 'K_vdc', 0.0018);

% Re-layout only the tutorial-level blocks we own.
set_param(et, 'Position', [255 360 355 505]);
set_param([model '/SeriesTransformer'], 'Position', [20 365 145 475]);
set_param([model '/EnergyConverter'], 'Position', [470 620 645 740]);
set_param([model '/DCLink'], 'Position', [735 675 775 722]);
set_param([model '/RegulatingConverter'], 'Position', [45 650 280 842]);
set_param([model '/DQControl'], 'Position', [430 1030 650 1190]);
set_param([model '/MeasLV'], 'Position', [610 380 695 486]);

annotationText = sprintf(['Step 16 paper alignment:\n', ...
    'ElectromagneticTransformer exposes W1/W2/W3.\n', ...
    'EnergyConverter AC side connects to W3 only.\n', ...
    'RegulatingConverter remains primary-side series injection.']);
addOrUpdateAnnotation(model, annotationText);

set_param(model, 'SimulationCommand', 'update');
save_system(model);

previewPath = fullfile(tuitionDir, [model '_step16_w3_energy_alignment.png']);
try
    print(['-s' model], '-dpng', '-r160', previewPath);
catch printErr
    warning(printErr.identifier, '%s', printErr.message);
end

fprintf('Completed Step 16 W3 alignment.\n');
fprintf('Model: %s\n', mdlPath);
fprintf('Backup: %s\n', backupPath);
if exist(previewPath, 'file') == 2
    fprintf('Preview: %s\n', previewPath);
end

function clearPortLine(portHandle)
lineHandle = get_param(portHandle, 'Line');
if lineHandle ~= -1 && ishandle(lineHandle)
    delete_line(lineHandle);
end
end

function addOrUpdateAnnotation(model, text)
anns = find_system(model, 'FindAll', 'on', 'Type', 'annotation');
for i = 1:numel(anns)
    try
        oldText = get_param(anns(i), 'PlainText');
        if contains(oldText, 'Step 16 paper alignment')
            set_param(anns(i), 'PlainText', text);
            return;
        end
    catch
    end
end
Simulink.Annotation(model, text);
end
