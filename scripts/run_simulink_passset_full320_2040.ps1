param(
    [string]$Tag = "current_puresac_vs_traditional_20260712",
    [int[]]$Modes = @(12, 7, 8),
    [switch]$SkipFull320,
    [switch]$SkipExpanded2040
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$SimDir = Join-Path $Root 'lab\simulink'
$Results = Join-Path $Root 'lab\results'
$RunDir = Join-Path $Results "simulink_passset_full320_2040_$Tag"
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
$MainLog = Join-Path $RunDir 'run.log'

function Log([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    $line | Tee-Object -FilePath $MainLog -Append
}

function Invoke-MatlabPassset([string]$ScenarioSet, [int]$Mode, [int]$LastSid) {
    $matlab = Get-Command matlab -ErrorAction Stop
    $log = Join-Path $RunDir "${ScenarioSet}_mi${Mode}.log"
    $code = "cd('$SimDir'); frt_v2_passset_batch_switching('$ScenarioSet', $Mode, 1, $LastSid, '$Tag');"
    Log "BEGIN $ScenarioSet mi=$Mode last_sid=$LastSid"
    & $matlab.Source -batch $code 2>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -ne 0) {
        Log "FAILED $ScenarioSet mi=$Mode exit=$LASTEXITCODE"
        throw "$ScenarioSet mi=$Mode failed with exit code $LASTEXITCODE"
    }
    Log "END $ScenarioSet mi=$Mode"
}

Log "Simulink pass-set batch start root=$Root tag=$Tag modes=$($Modes -join ',')"
if (!$SkipFull320) {
    foreach ($mode in $Modes) {
        Invoke-MatlabPassset 'full320' $mode 320
    }
}
if (!$SkipExpanded2040) {
    foreach ($mode in $Modes) {
        Invoke-MatlabPassset 'expanded2040' $mode 2040
    }
}
Log 'Simulink pass-set batch complete'
