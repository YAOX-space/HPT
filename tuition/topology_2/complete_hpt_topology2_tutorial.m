% Build the topology2 tutorial model from the maintained paper-style
% switch-level topology2 builder.
%
% Topology2 tutorial configuration:
%   - MainTransformer is W1/W2 only.
%   - EnergyConverter is connected through a secondary-side parallel coupled
%     transformer path, not through a W3 tertiary winding.
%   - RegulatingConverter drives the W5 side of per-phase series transformers;
%     W6 is inserted in the secondary/load path.
%   - EnergyConverter and RegulatingConverter share the DC-link capacitor.

model = 'hpt_topology2_tutorial';
sourceModel = 'hpt_v2_topology2_paper';
tuitionDir = fileparts(mfilename('fullpath'));
repoRoot = fileparts(fileparts(tuitionDir));
sourceDir = fullfile(repoRoot, 'simulink', 'topology2');
mdlPath = fullfile(tuitionDir, [model '.slx']);
archiveDir = fullfile(repoRoot, 'legacy', 'tuition_intermediate', 'topology_2');

fprintf('Topology2 tutorial directory: %s\n', tuitionDir);
fprintf('Maintained topology2 source: %s\n', sourceDir);
fprintf('Tutorial model path: %s\n', mdlPath);

if ~isfolder(sourceDir)
    error('Maintained topology2 source directory not found: %s', sourceDir);
end

if ~isfolder(archiveDir)
    mkdir(archiveDir);
end

if isfile(mdlPath)
    stamp = datestr(now, 'yyyymmdd_HHMMSS');
    backupPath = fullfile(archiveDir, [model '_before_rebuild_' stamp '.slx']);
    copyfile(mdlPath, backupPath);
    fprintf('Previous tutorial model archived: %s\n', backupPath);
else
    backupPath = '';
end

if bdIsLoaded(model)
    close_system(model, 0);
end
if bdIsLoaded(sourceModel)
    close_system(sourceModel, 0);
end

addpath(sourceDir);
addpath(fileparts(sourceDir));
build_hpt_v2_topology2_paper;

if ~bdIsLoaded(sourceModel)
    error('Source builder did not create expected model: %s', sourceModel);
end

save_system(sourceModel, mdlPath);
close_system(sourceModel, 0);

open_system(mdlPath);
set_param(model, 'SimulationCommand', 'update');
addOrUpdateAnnotation(model, sprintf(['Topology2 tutorial alignment:\n', ...
    'MainTransformer is W1/W2 only.\n', ...
    'EnergyConverter is on secondary-side parallel coupling.\n', ...
    'RegulatingConverter drives W5/W6 series injection.\n', ...
    'Both converters share the DC-link capacitor.']));
save_system(model);

fprintf('Completed topology2 tutorial rebuild.\n');
fprintf('Model: %s\n', mdlPath);
if ~isempty(backupPath)
    fprintf('Backup: %s\n', backupPath);
end

function addOrUpdateAnnotation(model, text)
anns = find_system(model, 'FindAll', 'on', 'Type', 'annotation');
for i = 1:numel(anns)
    try
        oldText = get_param(anns(i), 'PlainText');
        if contains(oldText, 'Topology2 tutorial alignment')
            set_param(anns(i), 'PlainText', text);
            return;
        end
    catch
    end
end
Simulink.Annotation(model, text);
end
