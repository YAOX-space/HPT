param(
    [ValidateSet('full320', 'expanded2040')]
    [string]$ScenarioSet,
    [string]$Tag = "current_puresac_vs_traditional_20260712"
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Results = Join-Path $Root 'lab\results'
$sacPath = Join-Path $Results "passset_${ScenarioSet}_switching_${Tag}_mi12.csv"
$fixedPath = Join-Path $Results "passset_${ScenarioSet}_switching_${Tag}_mi7.csv"
$mpcPath = Join-Path $Results "passset_${ScenarioSet}_switching_${Tag}_mi8.csv"

foreach ($p in @($sacPath, $fixedPath, $mpcPath)) {
    if (!(Test-Path -LiteralPath $p)) { throw "missing result file: $p" }
}

$sac = Import-Csv -LiteralPath $sacPath
$fixed = Import-Csv -LiteralPath $fixedPath
$mpc = Import-Csv -LiteralPath $mpcPath
$fixedBy = @{}; $mpcBy = @{}
foreach ($r in $fixed) { $fixedBy[[int]$r.sid] = $r }
foreach ($r in $mpc) { $mpcBy[[int]$r.sid] = $r }

$rows = foreach ($r in $sac) {
    $sid = [int]$r.sid
    if (!$fixedBy.ContainsKey($sid) -or !$mpcBy.ContainsKey($sid)) { continue }
    $f = $fixedBy[$sid]; $m = $mpcBy[$sid]
    $sacStrict = ($r.frt -eq 'True')
    $tradStrict = (($f.frt -eq 'True') -or ($m.frt -eq 'True'))
    $sacProxy = (($r.frt -eq 'True') -or ($r.frt -eq 'None'))
    $tradProxy = (($f.frt -eq 'True') -or ($f.frt -eq 'None') -or ($m.frt -eq 'True') -or ($m.frt -eq 'None'))
    [pscustomobject]@{
        sid = $sid
        category = $r.category
        fault_type = $r.fault_type
        scr = $r.scr
        target_V_pu = $r.target_V_pu
        sac_mi12 = $r.frt
        fixed_mi7 = $f.frt
        mpc_mi8 = $m.frt
        strict_category = $(if ($sacStrict -and $tradStrict) { 'both-pass' } elseif ($sacStrict -and !$tradStrict) { 'SAC-only' } elseif (!$sacStrict -and $tradStrict) { 'traditional-only' } else { 'both-fail' })
        proxy_category = $(if ($sacProxy -and $tradProxy) { 'both-pass' } elseif ($sacProxy -and !$tradProxy) { 'SAC-only' } elseif (!$sacProxy -and $tradProxy) { 'traditional-only' } else { 'both-fail' })
        sac_reactive = $r.reactive
        sac_recover = $r.recover
        fixed_reactive = $f.reactive
        fixed_recover = $f.recover
        mpc_reactive = $m.reactive
        mpc_recover = $m.recover
    }
}

$base = Join-Path $Results "simulink_passset_${ScenarioSet}_${Tag}_pure_sac_vs_traditional"
$rows | Sort-Object sid | Export-Csv "${base}.csv" -NoTypeInformation
$strict = @{}; $rows | Group-Object strict_category | ForEach-Object { $strict[$_.Name] = $_.Count }
$proxy = @{}; $rows | Group-Object proxy_category | ForEach-Object { $proxy[$_.Name] = $_.Count }
[pscustomobject]@{
    metrics_version = 'frt-v2'
    layer = 'Simulink switching'
    scenario_set = $ScenarioSet
    tag = $Tag
    strict_pass_definition = 'frt == True'
    proxy_pass_definition = 'frt == True or frt == None'
    strict_counts = $strict
    proxy_counts = $proxy
    n_joined = @($rows).Count
    rows = $rows
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "${base}.json" -Encoding UTF8

"STRICT"
$rows | Group-Object strict_category | Sort-Object Name | Select-Object Name,Count | Format-Table -AutoSize
"PROXY"
$rows | Group-Object proxy_category | Sort-Object Name | Select-Object Name,Count | Format-Table -AutoSize
"wrote ${base}.csv/json"
