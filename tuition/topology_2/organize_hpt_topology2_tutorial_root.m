function organize_hpt_topology2_tutorial_root(model)
% Organize topology2 tutorial root level to match the topology1 teaching view.
%
% The root level should expose only the major conceptual blocks:
% Grid, Zg, MeasMV, ElectromagneticTransformer, CouplingTransformer,
% SeriesTransformer, MeasLV, Load, RegulatingConverter, EnergyConverter,
% DCLink, DQControl, MeasurementAndLogging, and powergui.

if nargin < 1
    model = 'hpt_topology2_tutorial';
end

if ~bdIsLoaded(model)
    open_system(model);
end

rename_block_if_present(model, 'Source_RL', 'Zg');
rename_block_if_present(model, 'MeasPrimary', 'MeasMV');
rename_block_if_present(model, 'MainTransformer', 'ElectromagneticTransformer');

if isempty(find_system(model, 'SearchDepth', 1, 'Name', 'CouplingTransformer'))
    expand_subsystem_if_present(model, 'SeriesTransformer');
    expand_subsystem_if_present(model, 'CouplingAndInjection');
end

create_named_subsystem_if_needed(model, 'CouplingTransformer', { ...
    'ParallelCoupled_1', 'ParallelCoupled_2', 'ParallelCoupled_3', ...
    'S3_link_1', 'S3_link_2', 'S3_link_3', ...
    'TPF_L_1', 'TPF_L_2', 'TPF_L_3', ...
    'MeasEnergy', ...
    'PCT_primary_neutral_ground', 'PCT_secondary_neutral_ground'});

create_named_subsystem_if_needed(model, 'SeriesTransformer', { ...
    'Reg_I_1', 'Reg_I_2', 'Reg_I_3', ...
    'SwHBC_L_1', 'SwHBC_L_2', 'SwHBC_L_3', ...
    'SwHBC_C_1', 'SwHBC_C_2', 'SwHBC_C_3', ...
    'HBC_Cap_V_1', 'HBC_Cap_V_2', 'HBC_Cap_V_3', ...
    'SwRegSeries_W5W6_1', 'SwRegSeries_W5W6_2', 'SwRegSeries_W5W6_3', ...
    'SwW5_V_1', 'SwW5_V_2', 'SwW5_V_3', ...
    'SwW6_V_1', 'SwW6_V_2', 'SwW6_V_3', ...
    'HBC_return_ground'});

create_named_subsystem_if_needed(model, 'DCLink', { ...
    'Cdc', 'MeasVdc', 'Chopper', 'Rchop', 'Chopper_gate', 'Chopper_cmp', ...
    'Vdc_delay_for_Idc', 'Vdc_delta_for_Idc', 'Cdc_dvdt_gain'});

create_named_subsystem_if_needed(model, 'MeasurementAndLogging', { ...
    'Vpri_abc', 'Igrid_abc', 'Vlv_abc', 'Vdc', ...
    'Mreg_cmd', 'Mref6_cmd', 'Menergy_cmd', ...
    'Energy_Vabc', 'Energy_Iabc', 'Energy_dbg', ...
    'HPTSAC_obs', 'HPTSAC_action', ...
    'Reg_Iabc_mux', 'Reg_Iabc', ...
    'HBC_Cap_Vabc_mux', 'HBC_Cap_Vabc', ...
    'Series_W5_Vabc_mux', 'Series_W5_Vabc', ...
    'Series_W6_Vabc_mux', 'Series_W6_Vabc', ...
    'Vinj_abc_mux', 'Vinj_abc', 'Idc_cap'});

hide_series_measurement_ports(model);
rename_series_power_ports(model);
apply_teaching_layout(model);
add_or_update_annotation(model);
set_param(model, 'SimulationCommand', 'update');
save_system(model);
end

function rename_block_if_present(model, oldName, newName)
if ~isempty(find_system(model, 'SearchDepth', 1, 'Name', newName))
    return;
end
oldPath = [model '/' oldName];
if ~isempty(find_system(model, 'SearchDepth', 1, 'Name', oldName))
    set_param(oldPath, 'Name', newName);
end
end

function expand_subsystem_if_present(model, subsystemName)
path = [model '/' subsystemName];
if getSimulinkBlockHandle(path) <= 0
    return;
end

try
    Simulink.BlockDiagram.expandSubsystem(path, 'CreateArea', 'off');
catch ME
    error('Could not expand %s before root regrouping: %s', subsystemName, ME.message);
end
end

function create_named_subsystem_if_needed(model, subsystemName, blockNames)
if ~isempty(find_system(model, 'SearchDepth', 1, 'Name', subsystemName))
    return;
end

before = find_system(model, 'SearchDepth', 1, 'BlockType', 'SubSystem');
beforeHandles = cellfun(@(b) get_param(b, 'Handle'), before);
handles = [];
for i = 1:numel(blockNames)
    blockPath = [model '/' blockNames{i}];
    h = getSimulinkBlockHandle(blockPath);
    if h > 0
        handles(end + 1) = h; %#ok<AGROW>
    end
end
if isempty(handles)
    error('No root-level blocks found for subsystem %s.', subsystemName);
end

Simulink.BlockDiagram.createSubsystem(handles);
after = find_system(model, 'SearchDepth', 1, 'BlockType', 'SubSystem');
afterHandles = cellfun(@(b) get_param(b, 'Handle'), after);
newHandles = setdiff(afterHandles, beforeHandles);
if numel(newHandles) ~= 1
    error('Expected one new subsystem for %s, found %d.', ...
        subsystemName, numel(newHandles));
end
set_param(newHandles(1), 'Name', subsystemName, 'ShowName', 'on');
end

function hide_series_measurement_ports(model)
st = [model '/SeriesTransformer'];
ml = [model '/MeasurementAndLogging'];
if getSimulinkBlockHandle(st) <= 0 || getSimulinkBlockHandle(ml) <= 0
    return;
end

measurements = {
    'Reg_I_1', 'Series_Reg_I_A';
    'Reg_I_2', 'Series_Reg_I_B';
    'Reg_I_3', 'Series_Reg_I_C';
    'SwW6_V_1', 'Series_W6_V_A';
    'SwW6_V_2', 'Series_W6_V_B';
    'SwW6_V_3', 'Series_W6_V_C';
    'HBC_Cap_V_1', 'Series_HBC_Cap_V_A';
    'HBC_Cap_V_2', 'Series_HBC_Cap_V_B';
    'HBC_Cap_V_3', 'Series_HBC_Cap_V_C';
    'SwW5_V_1', 'Series_W5_V_A';
    'SwW5_V_2', 'Series_W5_V_B';
    'SwW5_V_3', 'Series_W5_V_C'};

items = struct('SourceBlock', {}, 'Tag', {}, 'OutportBlock', {}, ...
    'MlInportBlock', {}, 'MlDstBlocks', {}, 'MlDstPorts', {});
for i = 1:size(measurements, 1)
    item = capture_measurement_path(st, ml, measurements{i, 1}, measurements{i, 2});
    if ~isempty(item)
        items(end + 1) = item; %#ok<AGROW>
    end
end

for i = 1:numel(items)
    replace_logging_inport_with_from(ml, items(i));
end
for i = 1:numel(items)
    replace_series_outport_with_goto(st, items(i));
end
end

function item = capture_measurement_path(st, ml, sourceName, tag)
item = [];
sourcePath = [st '/' sourceName];
if getSimulinkBlockHandle(sourcePath) <= 0
    return;
end
sourcePh = get_param(sourcePath, 'PortHandles');
if isempty(sourcePh.Outport)
    return;
end
sourceLine = get_param(sourcePh.Outport(1), 'Line');
if sourceLine == -1
    return;
end

dstBlocks = get_param(sourceLine, 'DstBlockHandle');
outportBlock = '';
for k = 1:numel(dstBlocks)
    if dstBlocks(k) ~= -1 && strcmp(get_param(dstBlocks(k), 'BlockType'), 'Outport')
        outportBlock = getfullname(dstBlocks(k));
        break;
    end
end
if isempty(outportBlock)
    return;
end

outportNumber = str2double(get_param(outportBlock, 'Port'));
stPh = get_param(st, 'PortHandles');
if outportNumber > numel(stPh.Outport)
    return;
end
rootLine = get_param(stPh.Outport(outportNumber), 'Line');
mlPortNumber = [];
if rootLine ~= -1
    dstPorts = get_param(rootLine, 'DstPortHandle');
    for k = 1:numel(dstPorts)
        if dstPorts(k) ~= -1 && strcmp(get_param(dstPorts(k), 'Parent'), ml)
            mlPortNumber = get_param(dstPorts(k), 'PortNumber');
            break;
        end
    end
end
if isempty(mlPortNumber)
    return;
end

mlInportBlock = find_inport_by_number(ml, mlPortNumber);
if isempty(mlInportBlock)
    return;
end

mlPh = get_param(mlInportBlock, 'PortHandles');
mlLine = get_param(mlPh.Outport(1), 'Line');
if mlLine == -1
    return;
end
mlDstPorts = get_param(mlLine, 'DstPortHandle');
dstBlockPaths = {};
dstPortNumbers = [];
for k = 1:numel(mlDstPorts)
    if mlDstPorts(k) ~= -1
        dstBlockPaths{end + 1} = get_param(mlDstPorts(k), 'Parent'); %#ok<AGROW>
        dstPortNumbers(end + 1) = get_param(mlDstPorts(k), 'PortNumber'); %#ok<AGROW>
    end
end
if isempty(dstBlockPaths)
    return;
end

item.SourceBlock = sourcePath;
item.Tag = tag;
item.OutportBlock = outportBlock;
item.MlInportBlock = mlInportBlock;
item.MlDstBlocks = dstBlockPaths;
item.MlDstPorts = dstPortNumbers;
end

function replace_logging_inport_with_from(ml, item)
fromPath = [ml '/F_' item.Tag];
if getSimulinkBlockHandle(fromPath) <= 0
    pos = get_param(item.MlInportBlock, 'Position');
    add_block('simulink/Signal Routing/From', fromPath, ...
        'GotoTag', item.Tag, ...
        'Position', [pos(1) pos(2) pos(1) + 45 pos(2) + 20], ...
        'ShowName', 'off');
else
    set_param(fromPath, 'GotoTag', item.Tag, 'ShowName', 'off');
end

if getSimulinkBlockHandle(item.MlInportBlock) > 0
    ph = get_param(item.MlInportBlock, 'PortHandles');
    line = get_param(ph.Outport(1), 'Line');
    if line ~= -1
        delete_line(line);
    end
    delete_block(item.MlInportBlock);
end

fromPh = get_param(fromPath, 'PortHandles');
for k = 1:numel(item.MlDstBlocks)
    dstPh = get_param(item.MlDstBlocks{k}, 'PortHandles');
    dstPort = dstPh.Inport(item.MlDstPorts(k));
    if get_param(dstPort, 'Line') == -1
        add_line(ml, fromPh.Outport(1), dstPort, 'autorouting', 'on');
    end
end
end

function replace_series_outport_with_goto(st, item)
gotoPath = [st '/G_' item.Tag];
if getSimulinkBlockHandle(gotoPath) <= 0
    pos = get_param(item.SourceBlock, 'Position');
    add_block('simulink/Signal Routing/Goto', gotoPath, ...
        'GotoTag', item.Tag, ...
        'TagVisibility', 'global', ...
        'Position', [pos(3) + 35 pos(2) pos(3) + 90 pos(2) + 20], ...
        'ShowName', 'off');
else
    set_param(gotoPath, 'GotoTag', item.Tag, ...
        'TagVisibility', 'global', 'ShowName', 'off');
end

sourcePh = get_param(item.SourceBlock, 'PortHandles');
sourceLine = get_param(sourcePh.Outport(1), 'Line');
if sourceLine ~= -1
    delete_line(sourceLine);
end
if getSimulinkBlockHandle(item.OutportBlock) > 0
    delete_block(item.OutportBlock);
end

gotoPh = get_param(gotoPath, 'PortHandles');
if get_param(gotoPh.Inport(1), 'Line') == -1
    add_line(st, sourcePh.Outport(1), gotoPh.Inport(1), 'autorouting', 'on');
end
end

function block = find_inport_by_number(systemPath, portNumber)
block = '';
inports = find_system(systemPath, 'SearchDepth', 1, 'BlockType', 'Inport');
for k = 1:numel(inports)
    if str2double(get_param(inports{k}, 'Port')) == portNumber
        block = inports{k};
        return;
    end
end
end

function rename_series_power_ports(model)
st = [model '/SeriesTransformer'];
if getSimulinkBlockHandle(st) <= 0
    return;
end

leftNames = {'LV_in_A', 'LV_in_B', 'LV_in_C', 'Hbridge_return_ref', ...
    'W5_to_Hbridge_A_pos', 'W5_to_Hbridge_B_pos', 'W5_to_Hbridge_C_pos'};
rightNames = {'LV_out_A', 'LV_out_B', 'LV_out_C', ...
    'W5_to_Hbridge_A_neg', 'W5_to_Hbridge_B_neg', 'W5_to_Hbridge_C_neg'};

rename_pmio_ports(st, 'Left', leftNames);
rename_pmio_ports(st, 'Right', rightNames);
end

function rename_pmio_ports(systemPath, side, names)
ports = find_system(systemPath, 'SearchDepth', 1, 'BlockType', 'PMIOPort');
selected = {};
ys = [];
for k = 1:numel(ports)
    if strcmp(get_param(ports{k}, 'Side'), side)
        selected{end + 1} = ports{k}; %#ok<AGROW>
        pos = get_param(ports{k}, 'Position');
        ys(end + 1) = pos(2); %#ok<AGROW>
    end
end
if numel(selected) ~= numel(names)
    return;
end

[~, idx] = sort(ys);
for k = 1:numel(idx)
    set_param(selected{idx(k)}, 'Name', names{k}, 'ShowName', 'on');
end
end

function apply_teaching_layout(model)
set_pos(model, 'powergui', [520 210 590 235]);
set_pos(model, 'Grid', [90 490 160 595]);
set_pos(model, 'Zg', [205 510 270 585]);
set_pos(model, 'MeasMV', [310 490 395 605]);
set_pos(model, 'ElectromagneticTransformer', [465 485 620 615]);
set_pos(model, 'CouplingTransformer', [690 370 865 520]);
set_pos(model, 'SeriesTransformer', [690 585 865 720]);
set_pos(model, 'MeasLV', [965 490 1050 605]);
set_pos(model, 'Load', [1130 505 1215 595]);
set_pos(model, 'RegulatingConverter', [420 760 650 900]);
set_pos(model, 'DCLink', [740 805 815 870]);
set_pos(model, 'EnergyConverter', [900 750 1075 900]);
set_pos(model, 'DQControl', [690 1040 920 1185]);
set_pos(model, 'MeasurementAndLogging', [1225 270 1390 395]);

set_color(model, 'ElectromagneticTransformer', 'lightBlue');
set_color(model, 'CouplingTransformer', 'cyan');
set_color(model, 'SeriesTransformer', 'lightBlue');
set_color(model, 'RegulatingConverter', 'orange');
set_color(model, 'EnergyConverter', 'green');
set_color(model, 'DQControl', 'yellow');
set_color(model, 'MeasurementAndLogging', 'white');
end

function set_pos(model, name, pos)
path = [model '/' name];
if getSimulinkBlockHandle(path) > 0
    set_param(path, 'Position', pos);
end
end

function set_color(model, name, color)
path = [model '/' name];
if getSimulinkBlockHandle(path) > 0
    set_param(path, 'BackgroundColor', color);
end
end

function add_or_update_annotation(model)
text = sprintf(['Topology2 teaching view:\n', ...
    'MainTransformer is shown as ElectromagneticTransformer.\n', ...
    'CouplingTransformer contains the secondary-side parallel energy coupling path.\n', ...
    'SeriesTransformer contains only the W5/W6 series injection path.\n', ...
    'DCLink and MeasurementAndLogging hide implementation details.']);
anns = find_system(model, 'FindAll', 'on', 'Type', 'annotation');
for i = 1:numel(anns)
    try
        oldText = get_param(anns(i), 'PlainText');
        if contains(oldText, 'Topology2 teaching view')
            set_param(anns(i), 'PlainText', text);
            return;
        end
    catch
    end
end
Simulink.Annotation(model, text);
end
