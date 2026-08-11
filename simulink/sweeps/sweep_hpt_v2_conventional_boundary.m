% sweep_hpt_v2_conventional_boundary
% Find pass/fail boundaries for the tuned conventional dq controller.
%
% The matrix intentionally mixes mild, near-boundary, and severe FRT cases so
% the traditional controller should pass some rows and fail others.  SAC
% training/evaluation should later beat this measured boundary, not an
% artificially weak or impossible baseline.

clearvars -except hpt_boundary_durations hpt_boundary_lvrt_depths ...
    hpt_boundary_hvrt_depths hpt_boundary_topology ...
    hpt_boundary_conventional_params hpt_boundary_run_label ...
    hpt_boundary_fault_start hpt_boundary_fault_stop_margin ...
    hpt_boundary_fault_settle_s hpt_boundary_modes;
close all;

rootDir = fileparts(fileparts(mfilename('fullpath')));
oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));
cd(rootDir);

if exist('hpt_boundary_durations', 'var')
    durations = hpt_boundary_durations;
else
    durations = [0.040, 0.080, 0.120, 0.200];
end
if exist('hpt_boundary_lvrt_depths', 'var')
    lvrtDepths = hpt_boundary_lvrt_depths;
else
    lvrtDepths = [0.995, 0.990, 0.980, 0.950, 0.920, 0.900, 0.880, 0.850, 0.800, 0.750, 0.700, 0.650, 0.600, 0.500, 0.350, 0.200];
end
if exist('hpt_boundary_hvrt_depths', 'var')
    hvrtDepths = hpt_boundary_hvrt_depths;
else
    hvrtDepths = [1.005, 1.010, 1.020, 1.050, 1.080, 1.100, 1.120, 1.150, 1.180, 1.200, 1.250, 1.300];
end

faults = {};
for d = 1:numel(durations)
    dur = durations(d);
    durMs = round(1000 * dur);
    for k = 1:numel(lvrtDepths)
        pu = lvrtDepths(k);
        name = sprintf('lvrt_%03dms_%0.3fpu', durMs, pu);
        name = strrep(name, '.', 'p');
        faults(end+1, :) = {name, pu, dur}; %#ok<SAGROW>
    end
    for k = 1:numel(hvrtDepths)
        pu = hvrtDepths(k);
        name = sprintf('hvrt_%03dms_%0.3fpu', durMs, pu);
        name = strrep(name, '.', 'p');
        faults(end+1, :) = {name, pu, dur}; %#ok<SAGROW>
    end
end

if exist('hpt_boundary_topology', 'var')
    hpt_compare_topology = string(hpt_boundary_topology);
else
    hpt_compare_topology = "all";
end
hpt_compare_scenario_type = "fault";
hpt_compare_case_name = "all";
if exist('hpt_boundary_modes', 'var')
    hpt_compare_modes = string(hpt_boundary_modes);
else
    hpt_compare_modes = "conventional_dq";
end
hpt_compare_energy_enable = 1.0;
hpt_compare_conventional_profile = "tuned_v2_l1";
if exist('hpt_boundary_conventional_params', 'var')
    hpt_compare_conventional_params = hpt_boundary_conventional_params;
else
hpt_compare_conventional_params = struct();
end
hpt_compare_faults = faults;
if exist('hpt_boundary_fault_start', 'var')
    hpt_compare_fault_start = hpt_boundary_fault_start;
else
    hpt_compare_fault_start = 0.035;
end
if exist('hpt_boundary_fault_stop_margin', 'var')
    hpt_compare_fault_stop_margin = hpt_boundary_fault_stop_margin;
else
    hpt_compare_fault_stop_margin = 0.125;
end
if exist('hpt_boundary_fault_settle_s', 'var')
    hpt_compare_fault_settle_s = hpt_boundary_fault_settle_s;
end
if exist('hpt_boundary_run_label', 'var')
    hpt_compare_run_label = string(hpt_boundary_run_label);
else
    hpt_compare_run_label = "conventional_boundary";
end

run(fullfile(rootDir, 'evaluators', 'eval_hpt_v2_control_comparison.m'));

