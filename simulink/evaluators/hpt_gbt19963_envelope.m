function boundaryPu = hpt_gbt19963_envelope(category, timeAfterFaultS)
%HPT_GBT19963_ENVELOPE GB/T 19963.1-2021 voltage-time boundary.
%   LVRT returns the lower PCC voltage boundary. HVRT returns the upper PCC
%   voltage boundary. TIMEAFTERFAULTS may be scalar or an array.

    category = upper(string(category));
    t = double(timeAfterFaultS);
    if category == "LVRT"
        boundaryPu = 0.90 * ones(size(t));
        holdIdx = t >= 0.0 & t <= 0.625;
        rampIdx = t > 0.625 & t <= 2.0;
        boundaryPu(holdIdx) = 0.20;
        boundaryPu(rampIdx) = 0.20 + 0.70 .* ...
            (t(rampIdx) - 0.625) ./ (2.0 - 0.625);
    elseif category == "HVRT"
        boundaryPu = 1.10 * ones(size(t));
        boundaryPu(t >= 0.0 & t <= 0.5) = 1.30;
        boundaryPu(t > 0.5 & t <= 1.0) = 1.25;
        boundaryPu(t > 1.0 & t <= 10.0) = 1.20;
    else
        error('hpt:gbt19963:InvalidCategory', ...
            'category must be LVRT or HVRT, got %s', category);
    end
end
