function [pccPu, assessmentSignal] = hpt_pcc_assessment_voltage( ...
    gridVRows, t, faultPhasePu, faultPu, baseLineRms, frequencyHz)
%HPT_PCC_ASSESSMENT_VOLTAGE Select the GB/T PCC voltage assessment signal.
%   Single-phase events use the affected phase RMS. Two-phase and balanced
%   events use line-to-line RMS. LVRT selects the minimum balanced line
%   voltage and HVRT selects the maximum balanced line voltage.

    arguments
        gridVRows double
        t double
        faultPhasePu double
        faultPu (1, 1) double
        baseLineRms (1, 1) double {mustBePositive}
        frequencyHz (1, 1) double {mustBePositive} = 50.0
    end

    assert(size(gridVRows, 1) >= 3, ...
        'PCC voltage log must contain A/B/C phase voltages');
    assert(size(gridVRows, 2) == numel(t), ...
        'PCC voltage log length must match the simulation time vector');

    phasePu = double(faultPhasePu(:)');
    changed = find(abs(phasePu - 1.0) > 1e-6);
    phaseRms = cycle_rms_rows(gridVRows(1:3, :), t, frequencyHz);
    phaseRmsPu = phaseRms ./ (baseLineRms / sqrt(3));
    lineRows = [
        gridVRows(1, :) - gridVRows(2, :);
        gridVRows(2, :) - gridVRows(3, :);
        gridVRows(3, :) - gridVRows(1, :)
    ];
    lineRmsPu = cycle_rms_rows(lineRows, t, frequencyHz) ./ baseLineRms;

    if numel(changed) == 1
        pccPu = phaseRmsPu(changed(1), :)';
        phaseNames = ["a", "b", "c"];
        assessmentSignal = "pcc_phase_" + phaseNames(changed(1)) + "_rms_pu";
    elseif numel(changed) == 2
        pair = sort(changed);
        if isequal(pair, [1, 2])
            lineIdx = 1;
            lineName = "ab";
        elseif isequal(pair, [2, 3])
            lineIdx = 2;
            lineName = "bc";
        else
            lineIdx = 3;
            lineName = "ca";
        end
        pccPu = lineRmsPu(lineIdx, :)';
        assessmentSignal = "pcc_line_" + lineName + "_rms_pu";
    else
        if faultPu < 1.0
            pccPu = min(lineRmsPu, [], 1)';
            assessmentSignal = "pcc_min_line_rms_pu";
        else
            pccPu = max(lineRmsPu, [], 1)';
            assessmentSignal = "pcc_max_line_rms_pu";
        end
    end
end

function rmsRows = cycle_rms_rows(signalRows, t, frequencyHz)
    dt = median(diff(t));
    samplesPerCycle = max(1, round(1.0 / (frequencyHz * dt)));
    leftSamples = floor((samplesPerCycle - 1) / 2);
    rightSamples = samplesPerCycle - 1 - leftSamples;
    rmsRows = sqrt(movmean(signalRows.^2, ...
        [leftSamples, rightSamples], 2, 'Endpoints', 'shrink'));
end
