% test_hpt_v2_switch_models
% Runs the final successful pure switch-level HPT regressions.

rootDir = fileparts(fileparts(mfilename('fullpath')));

oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));

cd(rootDir);
run(fullfile(rootDir, 'tests', 'test_hpt_v2_sac_interface.m'));

% The interface regression is a script and clears its caller workspace.
% Reconstruct the test root before running the physical-model regressions.
rootDir = fileparts(fileparts(mfilename('fullpath')));
cd(fullfile(rootDir, 'topology1'));
run('test_hpt_v2_1to1_pure_switchlevel.m');

rootDir = fileparts(fileparts(mfilename('fullpath')));
cd(fullfile(rootDir, 'topology2'));
run('test_hpt_v2_topology2_pure_switchlevel.m');

fprintf('Both final pure switch-level HPT models passed.\\n');

