function organize_hpt_topology2_tutorial_root(model)
% Organize topology2 tutorial root level to match the topology1 teaching view.
%
% The root level should expose only the major conceptual blocks:
% Grid, Zg, MeasMV, SeriesTransformer, ElectromagneticTransformer, MeasLV,
% Load, RegulatingConverter, EnergyConverter, DCLink, DQControl,
% MeasurementAndLogging, and powergui.

if nargin < 1
    model = 'hpt_topology2_tutorial';
end

if ~bdIsLoaded(model)
    open_system(model);
end

rename_block_if_present(model, 'Source_RL', 'Zg');
rename_block_if_present(model, 'MeasPrimary', 'MeasMV');
rename_block_if_present(model, 'MainTransformer', 'ElectromagneticTransformer');
rename_block_if_present(model, 'CouplingAndInjection', 'SeriesTransformer');

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

function apply_teaching_layout(model)
set_pos(model, 'powergui', [520 210 590 235]);
set_pos(model, 'Grid', [90 490 160 595]);
set_pos(model, 'Zg', [205 510 270 585]);
set_pos(model, 'MeasMV', [310 490 395 605]);
set_pos(model, 'SeriesTransformer', [485 485 630 610]);
set_pos(model, 'ElectromagneticTransformer', [770 485 920 615]);
set_pos(model, 'MeasLV', [965 490 1050 605]);
set_pos(model, 'Load', [1130 505 1215 595]);
set_pos(model, 'RegulatingConverter', [420 760 650 900]);
set_pos(model, 'DCLink', [740 805 815 870]);
set_pos(model, 'EnergyConverter', [900 750 1075 900]);
set_pos(model, 'DQControl', [690 1040 920 1185]);
set_pos(model, 'MeasurementAndLogging', [1225 270 1390 395]);

set_color(model, 'SeriesTransformer', 'cyan');
set_color(model, 'ElectromagneticTransformer', 'lightBlue');
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
    'SeriesTransformer contains W5/W6 series injection and secondary energy coupling.\n', ...
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
