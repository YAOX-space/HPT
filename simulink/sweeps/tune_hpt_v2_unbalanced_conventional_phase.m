function tune_hpt_v2_unbalanced_conventional_phase()
% tune_hpt_v2_unbalanced_conventional_phase
% Diagnostic sweep for the unbalanced conventional_dq baseline.
%
% The unbalanced boundary generator calls eval_hpt_v2_control_comparison.m,
% which clears its caller workspace.  This function keeps the sweep state in
% a function workspace and launches each case in the MATLAB base workspace.

rootDir = fileparts(fileparts(mfilename('fullpath')));

if evalin('base', "exist('hpt_unbalanced_tune_topology','var')")
    topology = string(evalin('base', 'hpt_unbalanced_tune_topology'));
else
    topology = "topology1";
end

if evalin('base', "exist('hpt_unbalanced_tune_lvrt_depths','var')")
    lvrtDepths = evalin('base', 'hpt_unbalanced_tune_lvrt_depths');
else
    lvrtDepths = [0.98];
end

if evalin('base', "exist('hpt_unbalanced_tune_hvrt_depths','var')")
    hvrtDepths = evalin('base', 'hpt_unbalanced_tune_hvrt_depths');
else
    hvrtDepths = [1.02];
end

if evalin('base', "exist('hpt_unbalanced_tune_phase_sets','var')")
    phaseSets = evalin('base', 'hpt_unbalanced_tune_phase_sets');
else
    phaseSets = {'a', [1 0 0]};
end

if evalin('base', "exist('hpt_unbalanced_tune_reg_polarities','var')")
    regPolarities = evalin('base', 'hpt_unbalanced_tune_reg_polarities');
else
    regPolarities = [-1 1];
end

if evalin('base', "exist('hpt_unbalanced_tune_inj_phases','var')")
    injPhases = evalin('base', 'hpt_unbalanced_tune_inj_phases');
else
    injPhases = [-2.10 -1.05 0 1.05];
end

if evalin('base', "exist('hpt_unbalanced_tune_run_label','var')")
    runLabel = string(evalin('base', 'hpt_unbalanced_tune_run_label'));
else
    runLabel = "unbalanced_conventional_phase_tune";
end

if evalin('base', "exist('hpt_unbalanced_tune_reg_scale','var')")
    regScale = evalin('base', 'hpt_unbalanced_tune_reg_scale');
else
    regScale = 0.55;
end

if evalin('base', "exist('hpt_unbalanced_tune_energy_scale','var')")
    energyScale = evalin('base', 'hpt_unbalanced_tune_energy_scale');
else
    energyScale = 0.55;
end

if evalin('base', "exist('hpt_unbalanced_tune_model_params','var')")
    modelParams = evalin('base', 'hpt_unbalanced_tune_model_params');
else
    modelParams = struct();
end

fprintf('Unbalanced conventional phase tune: topology=%s, %d polarities, %d phases\n', ...
    topology, numel(regPolarities), numel(injPhases));

for ipol = 1:numel(regPolarities)
    for iph = 1:numel(injPhases)
        regPolarity = regPolarities(ipol);
        injPhase = injPhases(iph);
        token = sprintf('%s_pol%+g_phi%+0.2f', runLabel, regPolarity, injPhase);
        token = regexprep(token, '[^A-Za-z0-9_+-]', '_');

        params = struct( ...
            'hpt_conventional_reg_scale', regScale, ...
            'hpt_conventional_energy_scale', energyScale, ...
            'hpt_sac_reg_polarity', regPolarity, ...
            'hpt_inj_phase_offset', injPhase);

        assignin('base', 'hpt_unbalanced_boundary_topology', topology);
        assignin('base', 'hpt_unbalanced_boundary_lvrt_depths', lvrtDepths);
        assignin('base', 'hpt_unbalanced_boundary_hvrt_depths', hvrtDepths);
        assignin('base', 'hpt_unbalanced_boundary_phase_sets', phaseSets);
        assignin('base', 'hpt_unbalanced_boundary_run_label', string(token));
        assignin('base', 'hpt_unbalanced_boundary_model_params', modelParams);
        assignin('base', 'hpt_unbalanced_boundary_conventional_params', params);

        fprintf('Running polarity=%+g inj_phase=%+0.3f label=%s\n', ...
            regPolarity, injPhase, token);
        evalin('base', sprintf("run('%s')", ...
            fullfile(rootDir, 'sweeps', 'sweep_hpt_v2_unbalanced_conventional_boundary.m')));
    end
end
end
