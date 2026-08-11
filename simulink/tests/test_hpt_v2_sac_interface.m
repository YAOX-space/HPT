% test_hpt_v2_sac_interface
% Verifies the shared 24-D observation / 4-D action SAC interface in both
% final switch-level HPT topology builders.

clearvars;
close all;

rootDir = fileparts(fileparts(mfilename('fullpath')));
addpath(rootDir);
ensure_hpt_sac_placeholder(rootDir);

cases = {
    fullfile(rootDir, 'topology1'), 'build_hpt_v2_1to1_switchlevel', 'hpt_v2_1to1_switchlevel';
    fullfile(rootDir, 'topology2'), 'build_hpt_v2_topology2_paper', 'hpt_v2_topology2_paper';
};

oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));

for c = 1:size(cases, 1)
    cd(cases{c, 1});
    feval(cases{c, 2});
    M = cases{c, 3};

    hits = find_system(M, 'LookUnderMasks', 'all', ...
        'FollowLinks', 'on', 'Name', 'HPTSACController');
    assert(~isempty(hits), '%s does not contain HPTSACController', M);

    hpt_traj_t = (0:0.002:0.03)';
    hpt_traj_action = repmat([0.12, 0.0, 0.02, 0.0], numel(hpt_traj_t), 1);
    save(fullfile(pwd, 'hpt_sac_trajectory.mat'), 'hpt_traj_t', 'hpt_traj_action');

    for policyMode = [0.0, 1.0, -2.0]
        in = Simulink.SimulationInput(M);
        if policyMode == 0.0
            in = in.setModelParameter('StopTime', '0.03');
        elseif policyMode == 1.0
            in = in.setModelParameter('StopTime', '0.006');
        else
            in = in.setModelParameter('StopTime', '0.012');
        end
        in = in.setBlockParameter([M '/Grid'], 'Voltage', '10000');
        in = in.setVariable('hpt_sac_enable', 1.0, 'Workspace', M);
        in = in.setVariable('hpt_sac_policy_mode', policyMode, 'Workspace', M);
        out = sim(in);

        obs = out.get('HPTSAC_obs');
        act = out.get('HPTSAC_action');
        obsRows = reshape(obs, size(obs, 1), []);
        actRows = reshape(act, size(act, 1), []);
        assert(size(obsRows, 1) == 24, '%s SAC observation must be 24-D', M);
        assert(size(actRows, 1) == 4, '%s SAC action must be 4-D', M);
        assert(all(isfinite(obsRows(:))), '%s SAC observation contains non-finite values', M);
        assert(all(isfinite(actRows(:))), '%s SAC action contains non-finite values', M);
        assert(max(abs(actRows(1:2, :)), [], 'all') <= 0.8001, '%s regulating action exceeds limit', M);
        assert(max(abs(actRows(3:4, :)), [], 'all') <= 0.9501, '%s energy action exceeds limit', M);
    end
end

fprintf('HPT SAC 24/4 interface regression passed for topology1 and topology2.\\n');

function ensure_hpt_sac_placeholder(rootDir)
files = {
    fullfile(rootDir, 'hpt_sac_actor_weights.mat');
    fullfile(rootDir, 'hpt_sac_actor_weights_dynamic.mat');
};
for f = 1:numel(files)
    outFile = files{f};
    if exist(outFile, 'file')
        s = load(outFile, 'n_obs', 'n_act');
        if isfield(s, 'n_obs') && isfield(s, 'n_act') && double(s.n_obs) == 24 && double(s.n_act) == 4
            continue;
        end
    end
    write_placeholder(outFile);
end
end

function write_placeholder(outFile)
latent_pi_0_weight = zeros(256, 24);
latent_pi_0_bias = zeros(256, 1);
latent_pi_2_weight = zeros(256, 256);
latent_pi_2_bias = zeros(256, 1);
latent_pi_4_weight = zeros(256, 256);
latent_pi_4_bias = zeros(256, 1);
mu_weight = zeros(4, 256);
mu_bias = zeros(4, 1);
act_low = [-0.8; -0.8; -0.95; -0.95];
act_high = [0.8; 0.8; 0.95; 0.95];
n_obs = 24;
n_act = 4;
controller = 'hpt-voltage-sac-placeholder';
save(outFile, 'latent_pi_0_weight', 'latent_pi_0_bias', ...
    'latent_pi_2_weight', 'latent_pi_2_bias', ...
    'latent_pi_4_weight', 'latent_pi_4_bias', ...
    'mu_weight', 'mu_bias', 'act_low', 'act_high', ...
    'n_obs', 'n_act', 'controller');
end

