function smoke_hpt_v2_unbalanced_source()
% smoke_hpt_v2_unbalanced_source
% Verify the optional unbalanced fault-source path in
% eval_hpt_v2_control_comparison.m.  This smoke test does not train SAC and
% does not promote any controller; it checks that the new [puA puB puC] fault
% descriptor produces the expected Vgrid_abc phase ordering and sequence
% content at the grid/MV measurement point.

rootDir = fileparts(fileparts(mfilename('fullpath')));
oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));
cd(rootDir);

if evalin('base', 'exist(''hpt_unbalanced_smoke_topology'', ''var'')')
    topology = string(evalin('base', 'hpt_unbalanced_smoke_topology'));
else
    topology = "topology1";
end

faultStart = 0.080;
faultDuration = 0.060;
faultSettle = 0.020;
stamp = datestr(now, 'yyyymmdd_HHMMSS');
runId = "hpt_unbalanced_source_smoke_" + topology + "_" + string(stamp);

faults = {
    'a_lvrt_060ms_0p900pu',   0.90, faultDuration, [0.90 1.00 1.00];
    'b_lvrt_060ms_0p900pu',   0.90, faultDuration, [1.00 0.90 1.00];
    'c_lvrt_060ms_0p900pu',   0.90, faultDuration, [1.00 1.00 0.90];
    'ab_lvrt_060ms_0p900pu',  0.90, faultDuration, [0.90 0.90 1.00];
    'bc_lvrt_060ms_0p900pu',  0.90, faultDuration, [1.00 0.90 0.90];
    'ca_lvrt_060ms_0p900pu',  0.90, faultDuration, [0.90 1.00 0.90];
    'abc_lvrt_060ms_0p900pu', 0.90, faultDuration, [0.90 0.90 0.90];
    'a_hvrt_060ms_1p100pu',   1.10, faultDuration, [1.10 1.00 1.00];
    'b_hvrt_060ms_1p100pu',   1.10, faultDuration, [1.00 1.10 1.00];
    'c_hvrt_060ms_1p100pu',   1.10, faultDuration, [1.00 1.00 1.10];
    'ab_hvrt_060ms_1p100pu',  1.10, faultDuration, [1.10 1.10 1.00];
    'bc_hvrt_060ms_1p100pu',  1.10, faultDuration, [1.00 1.10 1.10];
    'ca_hvrt_060ms_1p100pu',  1.10, faultDuration, [1.10 1.00 1.10];
    'abc_hvrt_060ms_1p100pu', 1.10, faultDuration, [1.10 1.10 1.10];
};

outCsv = run_source_eval(rootDir, topology, faults, faultStart, faultSettle, runId);
T = readtable(outCsv, 'TextType', 'string');
assert(height(T) == size(faults, 1), 'Unexpected smoke row count');

phaseOrderTol = 0.020;
phaseRatioTol = 0.080;
preBalanceTol = 0.060;
recoveryRatioTol = 0.080;
recoveryBalanceTol = 0.070;
abcNegTol = 0.020;
unbalancedNegMin = 0.010;
recoveryNegTol = 0.030;
obsPreTol = 0.200;
obsFaultMin = 0.450;
obsRecoveryMin = 0.250;
rows = repmat(struct(), size(faults, 1), 1);

for k = 1:size(faults, 1)
    name = string(faults{k, 1});
    idx = find(T.case_name == name, 1);
    assert(~isempty(idx), 'Missing smoke row: %s', name);
    expected = double(faults{k, 4});
    got = [
        T.source_va_fault_pu(idx), ...
        T.source_vb_fault_pu(idx), ...
        T.source_vc_fault_pu(idx)
    ];
    pre = [
        T.source_va_pre_pu(idx), ...
        T.source_vb_pre_pu(idx), ...
        T.source_vc_pre_pu(idx)
    ];
    rec = [
        T.source_va_recovery_pu(idx), ...
        T.source_vb_recovery_pu(idx), ...
        T.source_vc_recovery_pu(idx)
    ];
    faultRatio = got ./ max(pre, 1e-9);
    recoveryRatio = rec ./ max(pre, 1e-9);
    isBalanced = max(expected) - min(expected) < 1e-9;
    vneg = T.source_vneg_seq_fault_pu(idx);
    preVpos = T.source_vpos_seq_pre_pu(idx);
    recoveryVneg = T.source_vneg_seq_recovery_pu(idx);
    preOk = all(isfinite(pre)) && ...
        ((max(pre) - min(pre)) / max(mean(pre), 1e-9) <= preBalanceTol) && ...
        isfinite(preVpos) && preVpos > 0.20;
    magnitudeOk = all(isfinite(faultRatio)) && ...
        max(abs(faultRatio - expected)) <= phaseRatioTol;
    recoveryOk = all(isfinite(recoveryRatio)) && ...
        max(abs(recoveryRatio - 1.0)) <= recoveryRatioTol && ...
        ((max(rec) - min(rec)) / max(mean(rec), 1e-9) <= recoveryBalanceTol) && ...
        (recoveryVneg / max(preVpos, 1e-9) <= recoveryNegTol);
    if isBalanced
        seqOk = vneg / max(preVpos, 1e-9) <= abcNegTol;
        phaseOk = (max(got) - min(got)) <= phaseOrderTol;
    else
        seqOk = vneg / max(preVpos, 1e-9) >= unbalancedNegMin;
        if faults{k, 2} < 1.0
            lowExpected = expected < max(expected);
            phaseOk = max(got(lowExpected)) <= min(got(~lowExpected)) + phaseOrderTol;
        else
            highExpected = expected > min(expected);
            phaseOk = min(got(highExpected)) + phaseOrderTol >= max(got(~highExpected));
        end
    end
    obsPreOk = T.obs_fault_flag_pre_mean(idx) <= obsPreTol && ...
        T.obs_recovery_flag_pre_mean(idx) <= obsPreTol;
    obsFaultOk = all(isfinite([ ...
        T.obs_vpu_fault_mean(idx), T.obs_vpos_fault_mean(idx), ...
        T.obs_vneg_fault_mean(idx), T.obs_vdcpu_fault_mean(idx)]));
    obsRecoveryOk = all(isfinite([ ...
        T.obs_vpu_recovery_mean(idx), T.obs_vpos_recovery_mean(idx), ...
        T.obs_vneg_recovery_mean(idx), T.obs_vdcpu_recovery_mean(idx)]));
    obsOk = obsPreOk && obsFaultOk && obsRecoveryOk;
    rows(k).case_name = name;
    rows(k).expected_a = expected(1);
    rows(k).expected_b = expected(2);
    rows(k).expected_c = expected(3);
    rows(k).pre_a = pre(1);
    rows(k).pre_b = pre(2);
    rows(k).pre_c = pre(3);
    rows(k).meas_a = got(1);
    rows(k).meas_b = got(2);
    rows(k).meas_c = got(3);
    rows(k).ratio_a = faultRatio(1);
    rows(k).ratio_b = faultRatio(2);
    rows(k).ratio_c = faultRatio(3);
    rows(k).recovery_a = rec(1);
    rows(k).recovery_b = rec(2);
    rows(k).recovery_c = rec(3);
    rows(k).recovery_ratio_a = recoveryRatio(1);
    rows(k).recovery_ratio_b = recoveryRatio(2);
    rows(k).recovery_ratio_c = recoveryRatio(3);
    rows(k).meas_unbalance = T.source_vabc_unbalance_fault_pu(idx);
    rows(k).meas_vpos_seq = T.source_vpos_seq_fault_pu(idx);
    rows(k).meas_vneg_seq = vneg;
    rows(k).pre_vpos_seq = preVpos;
    rows(k).recovery_vneg_seq = recoveryVneg;
    rows(k).grid_vpos_pre = T.grid_vpos_seq_pre_pu(idx);
    rows(k).grid_vpos_fault = T.grid_vpos_seq_fault_pu(idx);
    rows(k).grid_vpos_recovery = T.grid_vpos_seq_recovery_pu(idx);
    rows(k).grid_vneg_pre = T.grid_vneg_seq_pre_pu(idx);
    rows(k).grid_vneg_fault = T.grid_vneg_seq_fault_pu(idx);
    rows(k).grid_vneg_recovery = T.grid_vneg_seq_recovery_pu(idx);
    rows(k).obs_fault_pre = T.obs_fault_flag_pre_mean(idx);
    rows(k).obs_fault_fault = T.obs_fault_flag_fault_mean(idx);
    rows(k).obs_fault_recovery = T.obs_fault_flag_recovery_mean(idx);
    rows(k).obs_recovery_pre = T.obs_recovery_flag_pre_mean(idx);
    rows(k).obs_recovery_fault = T.obs_recovery_flag_fault_mean(idx);
    rows(k).obs_recovery_recovery = T.obs_recovery_flag_recovery_mean(idx);
    rows(k).obs_fault_detected = T.obs_fault_flag_fault_mean(idx) >= obsFaultMin;
    rows(k).obs_recovery_detected = T.obs_recovery_flag_recovery_mean(idx) >= obsRecoveryMin;
    rows(k).pre_pass = preOk;
    rows(k).phase_order_pass = phaseOk;
    rows(k).magnitude_pass = magnitudeOk;
    rows(k).sequence_pass = seqOk;
    rows(k).recovery_pass = recoveryOk;
    rows(k).obs_pass = obsOk;
    rows(k).pass = preOk && phaseOk && magnitudeOk && seqOk && recoveryOk && obsOk;
    assert(rows(k).pass, ...
        ['Unbalanced source smoke failed for %s: pre=%d phase=%d mag=%d ', ...
        'seq=%d rec=%d obs=%d ratios=[%.3f %.3f %.3f] ', ...
        'obsFault=[%.2f %.2f %.2f] obsRecovery=[%.2f %.2f %.2f]'], ...
        name, preOk, phaseOk, magnitudeOk, seqOk, recoveryOk, obsOk, ...
        faultRatio(1), faultRatio(2), faultRatio(3), ...
        rows(k).obs_fault_pre, rows(k).obs_fault_fault, rows(k).obs_fault_recovery, ...
        rows(k).obs_recovery_pre, rows(k).obs_recovery_fault, ...
        rows(k).obs_recovery_recovery);
end

outDir = fullfile(rootDir, '..', '..', 'lab', 'results', char(runId));
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
summaryCsv = fullfile(outDir, 'unbalanced_source_smoke_summary.csv');
writetable(struct2table(rows), summaryCsv);

report = fullfile(outDir, 'REPORT.md');
fid = fopen(report, 'w');
fprintf(fid, '# HPT Unbalanced Source Smoke\n\n');
fprintf(fid, '- Run ID: `%s`\n', runId);
fprintf(fid, '- Topology: `%s`\n', topology);
fprintf(fid, '- Evaluator CSV: `%s`\n', outCsv);
fprintf(fid, '- Summary CSV: `%s`\n', summaryCsv);
fprintf(fid, '- Result: `%d / %d` source cases passed pre/fault/recovery source and observation checks.\n', ...
    nnz([rows.pass]), numel(rows));
fclose(fid);

fprintf('HPT unbalanced source smoke passed: %s\n', report);
end

function outCsv = run_source_eval(rootDir, topology, faults, faultStart, faultSettle, runId)
    assignin('base', 'hpt_compare_topology', topology);
    assignin('base', 'hpt_compare_scenario_type', "fault");
    assignin('base', 'hpt_compare_modes', string({'no_control'}));
    assignin('base', 'hpt_compare_faults', faults);
    assignin('base', 'hpt_compare_fault_start', faultStart);
    assignin('base', 'hpt_compare_fault_stop_margin', 0.125);
    assignin('base', 'hpt_compare_fault_settle_s', faultSettle);
    assignin('base', 'hpt_compare_run_label', runId);
    assignin('base', 'hpt_compare_model_params', struct());
    assignin('base', 'hpt_compare_conventional_params', struct());
    assignin('base', 'hpt_compare_conventional_profile', "tuned_v2_l1");
    evaluator = fullfile(rootDir, 'evaluators', 'eval_hpt_v2_control_comparison.m');
    evaluator = strrep(evaluator, '''', '''''');
    evalin('base', sprintf('run(''%s'');', evaluator));
    outCsv = evalin('base', 'outCsv');
    assert(exist(outCsv, 'file') == 2, ...
        'Evaluator did not produce outCsv');
end
