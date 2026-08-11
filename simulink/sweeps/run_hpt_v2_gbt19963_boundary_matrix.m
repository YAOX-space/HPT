% run_hpt_v2_gbt19963_boundary_matrix
% Revalidate HPT controllers against GB/T 19963.1-2021 PCC voltage-time
% breakpoints. This campaign reports L1/L2/L3 separately; it does not claim
% certification when connection-state or active-power evidence is absent.
%
% Workspace overrides:
%   hpt_gbt_profile     "smoke" (default) | "full"
%   hpt_gbt_topology    "topology1" | "topology2" (default) | "all"
%   hpt_gbt_fault_scope "balanced" (default) | "a" | "ab" | "all"
%   hpt_gbt_modes       evaluator mode string array
%   hpt_gbt_output_dir  explicit result directory

clearvars -except hpt_gbt_profile hpt_gbt_topology hpt_gbt_fault_scope ...
    hpt_gbt_modes hpt_gbt_output_dir;

if ~exist('hpt_gbt_profile', 'var')
    hpt_gbt_profile = "smoke";
end
if ~exist('hpt_gbt_topology', 'var')
    hpt_gbt_topology = "topology2";
end
if ~exist('hpt_gbt_fault_scope', 'var')
    hpt_gbt_fault_scope = "balanced";
end
if ~exist('hpt_gbt_modes', 'var')
    hpt_gbt_modes = "conventional_dq";
end

hpt_gbt_profile = lower(string(hpt_gbt_profile));
hpt_gbt_fault_scope = lower(string(hpt_gbt_fault_scope));
if hpt_gbt_profile == "smoke"
    boundaryCases = {
        'gbt_lvrt_0p20_0p625s', 0.20, 0.625;
        'gbt_hvrt_1p30_0p500s', 1.30, 0.500;
    };
elseif hpt_gbt_profile == "full"
    boundaryCases = {
        'gbt_lvrt_0p20_0p625s', 0.20, 0.625;
        'gbt_lvrt_0p50_1p214s', 0.50, 1.214285714285714;
        'gbt_lvrt_0p75_1p705s', 0.75, 1.705357142857143;
        'gbt_lvrt_0p90_2p000s', 0.90, 2.000;
        'gbt_hvrt_1p30_0p500s', 1.30, 0.500;
        'gbt_hvrt_1p25_1p000s', 1.25, 1.000;
        'gbt_hvrt_1p20_10p000s', 1.20, 10.000;
    };
else
    error('hpt:gbt19963:InvalidProfile', ...
        'hpt_gbt_profile must be smoke or full');
end

faults = {};
for k = 1:size(boundaryCases, 1)
    name = string(boundaryCases{k, 1});
    pu = boundaryCases{k, 2};
    durationS = boundaryCases{k, 3};
    if hpt_gbt_fault_scope == "balanced" || hpt_gbt_fault_scope == "all"
        faults(end+1, :) = {char(name + "_abc"), pu, durationS, [pu pu pu]}; %#ok<SAGROW>
    end
    if hpt_gbt_fault_scope == "a" || hpt_gbt_fault_scope == "all"
        faults(end+1, :) = {char(name + "_a"), pu, durationS, [pu 1 1]}; %#ok<SAGROW>
    end
    if hpt_gbt_fault_scope == "ab" || hpt_gbt_fault_scope == "all"
        faults(end+1, :) = {char(name + "_ab"), pu, durationS, [pu pu 1]}; %#ok<SAGROW>
    end
end
assert(~isempty(faults), 'No fault cases selected for scope %s', hpt_gbt_fault_scope);

simulinkDir = fileparts(fileparts(mfilename('fullpath')));
hpt_compare_topology = string(hpt_gbt_topology);
hpt_compare_scenario_type = "fault";
hpt_compare_case_name = "all";
hpt_compare_modes = string(hpt_gbt_modes);
hpt_compare_faults = faults;
hpt_compare_fault_start = 0.035;
hpt_compare_fault_stop_margin = 0.250;
hpt_compare_fault_settle_s = 0.0;
hpt_compare_voltage_survival_current_gate = true;
hpt_compare_run_label = "gbt19963_" + hpt_gbt_profile + "_" + hpt_gbt_fault_scope;
if exist('hpt_gbt_output_dir', 'var')
    hpt_compare_output_dir = hpt_gbt_output_dir;
end
run(fullfile(simulinkDir, 'evaluators', 'eval_hpt_v2_control_comparison.m'));
