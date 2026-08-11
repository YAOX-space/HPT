function tests = test_hpt_gbt19963_envelope
% Regression tests for the exact GB/T 19963.1 voltage-time breakpoints.
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

function testLvrtBreakpoints(testCase)
    t = [0.0, 0.5, 0.625, 1.0, 2.0, 10.0];
    expected = [0.20, 0.20, 0.20, ...
        0.20 + 0.70 * (1.0 - 0.625) / (2.0 - 0.625), 0.90, 0.90];
    verifyEqual(testCase, hpt_gbt19963_envelope("LVRT", t), ...
        expected, 'AbsTol', 1e-12);
end

function testHvrtBreakpoints(testCase)
    t = [0.0, 0.5, 0.625, 1.0, 2.0, 10.0, 10.0001];
    expected = [1.30, 1.30, 1.25, 1.25, 1.20, 1.20, 1.10];
    verifyEqual(testCase, hpt_gbt19963_envelope("HVRT", t), ...
        expected, 'AbsTol', 1e-12);
end

function testInvalidCategory(testCase)
    verifyError(testCase, ...
        @() hpt_gbt19963_envelope("OTHER", 0.0), ...
        'hpt:gbt19963:InvalidCategory');
end
