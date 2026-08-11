% sweep_hpt_v2_unbalanced_conventional_boundary
% Build a small unbalanced conventional-dq boundary matrix using the optional
% {name, pu, duration_s, [puA puB puC]} fault descriptor supported by
% eval_hpt_v2_control_comparison.m.

if ~exist('hpt_unbalanced_boundary_topology', 'var')
    hpt_unbalanced_boundary_topology = "all";
end
if ~exist('hpt_unbalanced_boundary_duration_s', 'var')
    hpt_unbalanced_boundary_duration_s = 0.060;
end
if ~exist('hpt_unbalanced_boundary_lvrt_depths', 'var')
    hpt_unbalanced_boundary_lvrt_depths = [0.98, 0.95, 0.90, 0.85];
end
if ~exist('hpt_unbalanced_boundary_hvrt_depths', 'var')
    hpt_unbalanced_boundary_hvrt_depths = [1.02, 1.05, 1.10, 1.15];
end
if ~exist('hpt_unbalanced_boundary_phase_sets', 'var')
    hpt_unbalanced_boundary_phase_sets = {
        'a',  [1 0 0];
        'ab', [1 1 0];
    };
end
if ~exist('hpt_unbalanced_boundary_run_label', 'var')
    hpt_unbalanced_boundary_run_label = "unbalanced_conventional_boundary";
end
if ~exist('hpt_unbalanced_boundary_conventional_params', 'var')
    hpt_unbalanced_boundary_conventional_params = struct( ...
        'hpt_conventional_reg_scale', 0.55, ...
        'hpt_conventional_energy_scale', 0.55);
end
if ~exist('hpt_unbalanced_boundary_model_params', 'var')
    hpt_unbalanced_boundary_model_params = struct();
end
if ~exist('hpt_unbalanced_boundary_modes', 'var')
    hpt_unbalanced_boundary_modes = "conventional_dq";
end

faults = {};
durationS = hpt_unbalanced_boundary_duration_s;

for p = 1:size(hpt_unbalanced_boundary_phase_sets, 1)
    phaseName = string(hpt_unbalanced_boundary_phase_sets{p, 1});
    phaseMask = double(hpt_unbalanced_boundary_phase_sets{p, 2});
    for k = 1:numel(hpt_unbalanced_boundary_lvrt_depths)
        depth = hpt_unbalanced_boundary_lvrt_depths(k);
        phasePu = ones(1, 3);
        phasePu(phaseMask > 0.5) = depth;
        faults(end+1, :) = {char(sprintf('%s_lvrt_060ms_%s', ...
            phaseName, pu_token(depth))), depth, durationS, phasePu}; %#ok<SAGROW>
    end
    for k = 1:numel(hpt_unbalanced_boundary_hvrt_depths)
        depth = hpt_unbalanced_boundary_hvrt_depths(k);
        phasePu = ones(1, 3);
        phasePu(phaseMask > 0.5) = depth;
        faults(end+1, :) = {char(sprintf('%s_hvrt_060ms_%s', ...
            phaseName, pu_token(depth))), depth, durationS, phasePu}; %#ok<SAGROW>
    end
end

hpt_compare_topology = hpt_unbalanced_boundary_topology;
hpt_compare_scenario_type = "fault";
hpt_compare_modes = string(hpt_unbalanced_boundary_modes);
hpt_compare_faults = faults;
hpt_compare_fault_start = 0.080;
hpt_compare_fault_stop_margin = 0.125;
hpt_compare_fault_settle_s = 0.020;
hpt_compare_model_params = hpt_unbalanced_boundary_model_params;
hpt_compare_conventional_params = hpt_unbalanced_boundary_conventional_params;
hpt_compare_conventional_profile = "tuned_v2_l1";
hpt_compare_run_label = hpt_unbalanced_boundary_run_label;

run(fullfile(fileparts(fileparts(mfilename('fullpath'))), ...
    'evaluators', 'eval_hpt_v2_control_comparison.m'));

function token = pu_token(x)
    token = regexprep(sprintf('%.3fpu', x), '\.', 'p');
end
