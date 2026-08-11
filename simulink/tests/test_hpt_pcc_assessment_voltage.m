function tests = test_hpt_pcc_assessment_voltage
% Verify the PCC measurement channel selected for each fault phase family.
    tests = functiontests(localfunctions);
end

function setupOnce(testCase)
    simulinkDir = fileparts(fileparts(mfilename('fullpath')));
    evaluatorDir = fullfile(simulinkDir, 'evaluators');
    addpath(evaluatorDir);
    testCase.TestData.evaluatorDir = evaluatorDir;
end

function teardownOnce(testCase)
    rmpath(testCase.TestData.evaluatorDir);
end

function testSinglePhaseUsesAffectedPhaseRms(testCase)
    [t, abc] = synthetic_grid([0.5, 1.0, 1.0]);
    [pccPu, signal] = hpt_pcc_assessment_voltage( ...
        abc, t, [0.5, 1.0, 1.0], 0.5, 10000.0, 50.0);
    verifyEqual(testCase, signal, "pcc_phase_a_rms_pu");
    verifyEqual(testCase, median(pccPu(600:1400)), 0.5, 'AbsTol', 2e-3);
end

function testTwoPhaseUsesAffectedLineRms(testCase)
    [t, abc] = synthetic_grid([0.5, 0.5, 1.0]);
    [pccPu, signal] = hpt_pcc_assessment_voltage( ...
        abc, t, [0.5, 0.5, 1.0], 0.5, 10000.0, 50.0);
    verifyEqual(testCase, signal, "pcc_line_ab_rms_pu");
    verifyEqual(testCase, median(pccPu(600:1400)), 0.5, 'AbsTol', 2e-3);
end

function testBalancedLvrtUsesMinimumLineRms(testCase)
    [t, abc] = synthetic_grid([0.75, 0.75, 0.75]);
    [pccPu, signal] = hpt_pcc_assessment_voltage( ...
        abc, t, [0.75, 0.75, 0.75], 0.75, 10000.0, 50.0);
    verifyEqual(testCase, signal, "pcc_min_line_rms_pu");
    verifyEqual(testCase, median(pccPu(600:1400)), 0.75, 'AbsTol', 2e-3);
end

function [t, abc] = synthetic_grid(scale)
    dt = 20e-6;
    t = (0:dt:0.04)';
    phasePeak = (10000.0 / sqrt(3)) * sqrt(2);
    theta = 2*pi*50*t;
    abc = [
        scale(1) * phasePeak * sin(theta)';
        scale(2) * phasePeak * sin(theta - 2*pi/3)';
        scale(3) * phasePeak * sin(theta + 2*pi/3)'
    ];
end
