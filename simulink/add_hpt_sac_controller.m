function add_hpt_sac_controller(M, x, y)
% add_hpt_sac_controller
% Shared tutorial/evaluator SAC interface block.
%
% Inputs:
%   1 Vlv_abc
%   2 Vdc
%   3 Energy_Vabc
%   4 Energy_Iabc
%   5 Vpri_abc
%
% Outputs:
%   1 m_reg_ref6   placeholder regulating command for selector input
%   2 m_energy_abc placeholder energy command for selector input
%   3 obs24        logged 24-D observation placeholder
%   4 action4      logged 4-D action placeholder
%
% The block intentionally outputs zero commands unless a future exported actor
% is added inside this subsystem. Conventional DQ control remains the default
% path when hpt_sac_enable and hpt_sac_energy_enable are zero.

P = @(a, b, w, h) [a b a+w b+h];
S = [M '/HPTSACController'];
if ~isempty(find_system(M, 'SearchDepth', 1, 'Name', 'HPTSACController'))
    delete_block(S);
end

add_block('built-in/Subsystem', S, 'Position', P(x, y, 250, 170));
set_param(S, 'ShowName', 'on');
open_system(S);

inNames = {'Vlv_abc', 'Vdc', 'Energy_Vabc', 'Energy_Iabc', 'Vpri_abc'};
for k = 1:numel(inNames)
    add_block('simulink/Sources/In1', [S '/' inNames{k}], ...
        'Position', P(35, 20 + (k-1)*28, 30, 18));
end

add_block('simulink/Sources/Constant', [S '/ZeroRegABC'], ...
    'Position', P(115, 25, 55, 25), 'Value', 'zeros(6,1)');
add_block('simulink/Sources/Constant', [S '/ZeroEnergyABC'], ...
    'Position', P(115, 65, 55, 25), 'Value', 'zeros(3,1)');
add_block('simulink/Sources/Constant', [S '/Obs24Placeholder'], ...
    'Position', P(115, 105, 55, 25), 'Value', 'zeros(24,1)');
add_block('simulink/Sources/Constant', [S '/Action4Placeholder'], ...
    'Position', P(115, 145, 55, 25), 'Value', 'zeros(4,1)');

outNames = {'m_reg_ref6', 'm_energy_abc', 'obs24', 'action4'};
for k = 1:numel(outNames)
    add_block('simulink/Sinks/Out1', [S '/' outNames{k}], ...
        'Position', P(220, 25 + (k-1)*40, 30, 18));
end

add_line(S, 'ZeroRegABC/1', 'm_reg_ref6/1', 'autorouting', 'on');
add_line(S, 'ZeroEnergyABC/1', 'm_energy_abc/1', 'autorouting', 'on');
add_line(S, 'Obs24Placeholder/1', 'obs24/1', 'autorouting', 'on');
add_line(S, 'Action4Placeholder/1', 'action4/1', 'autorouting', 'on');

Simulink.Annotation(S, ['SAC interface placeholder: 24-D observation, ', ...
    '4-D action. Default outputs are zero; conventional DQ remains active.']);
end
