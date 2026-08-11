param(
    [int]$Steps = 300000,
    [double]$ProxyGoal = 90.0,
    [int[]]$ExtraSeeds = @(7, 123),
    [switch]$SkipSwitching
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$Results = Join-Path $Root 'lab\results'
$Models = Join-Path $Root 'data\models'
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$Out = Join-Path $Results "overnight_residual_$Stamp"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$MainLog = Join-Path $Out 'overnight.log'

function Log([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    $line | Tee-Object -FilePath $MainLog -Append
}

function Invoke-Step([string]$Name, [scriptblock]$Block) {
    Log "BEGIN $Name"
    & $Block 2>&1 | Tee-Object -FilePath $MainLog -Append
    if ($LASTEXITCODE -ne $null -and $LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
    Log "END $Name"
}

function ResidualScore([string]$JsonPath) {
    if (!(Test-Path -LiteralPath $JsonPath)) { return -1.0 }
    $j = Get-Content -LiteralPath $JsonPath -Raw | ConvertFrom-Json
    $raw = if ($null -ne $j.best_raw) { [double]$j.best_raw } elseif ($null -ne $j.best) { [double]$j.best } else { -1.0 }
    $ema = if ($null -ne $j.best_ema) { [double]$j.best_ema } else { -1.0 }
    return [Math]::Max($raw, $ema)
}

function SnapshotSeed([int]$Seed, [string]$RunId) {
    $dir = Join-Path $Out "seed_$Seed"
    $mdir = Join-Path $dir 'models'
    New-Item -ItemType Directory -Force -Path $mdir | Out-Null
    Get-ChildItem -LiteralPath $Models -Filter 'sac_residual*' -File -ErrorAction SilentlyContinue |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $mdir $_.Name) -Force }
    $trainJson = Join-Path $Results 'residual_train.json'
    if (Test-Path -LiteralPath $trainJson) {
        Copy-Item -LiteralPath $trainJson -Destination (Join-Path $dir 'residual_train.json') -Force
    }
    [pscustomobject]@{
        seed = $Seed
        run_id = $RunId
        score = (ResidualScore (Join-Path $dir 'residual_train.json'))
        dir = $dir
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dir 'snapshot.json')
    return $dir
}

function MoveResidualTargets([string]$Tag) {
    $dst = Join-Path $Out "moved_$Tag"
    $mdst = Join-Path $dst 'models'
    New-Item -ItemType Directory -Force -Path $mdst | Out-Null
    Get-ChildItem -LiteralPath $Models -Filter 'sac_residual*' -File -ErrorAction SilentlyContinue |
        ForEach-Object { Move-Item -LiteralPath $_.FullName -Destination (Join-Path $mdst $_.Name) -Force }
    $trainJson = Join-Path $Results 'residual_train.json'
    if (Test-Path -LiteralPath $trainJson) {
        Move-Item -LiteralPath $trainJson -Destination (Join-Path $dst 'residual_train.json') -Force
    }
}

function TrainSeed([int]$Seed) {
    MoveResidualTargets "before_seed_$Seed"
    $runId = "residual_overnight_${Stamp}_sd$Seed"
    $env:HPT_RUN_ID = $runId
    $env:HPT_RUN_LOG = Join-Path $Out "train_seed_$Seed.log"
    $env:HPT_FORCE_CPU = '1'
    $env:CUDA_VISIBLE_DEVICES = '-1'
    $env:PYTHONUNBUFFERED = '1'
    $env:KMP_DUPLICATE_LIB_OK = 'TRUE'
    $env:MKL_THREADING_LAYER = 'SEQUENTIAL'
    Invoke-Step "train residual seed $Seed" {
        & $Py -m hpt_frt.device.train_single --kind residual --seed $Seed --steps $Steps
    }
    SnapshotSeed $Seed $runId | Out-Null
}

function PromoteBestSnapshot([array]$Snapshots) {
    $best = $Snapshots | Sort-Object -Property score -Descending | Select-Object -First 1
    Log "BEST seed=$($best.seed) score=$($best.score) dir=$($best.dir)"
    MoveResidualTargets 'before_promote_best'
    Get-ChildItem -LiteralPath (Join-Path $best.dir 'models') -File |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $Models $_.Name) -Force }
    Copy-Item -LiteralPath (Join-Path $best.dir 'residual_train.json') -Destination (Join-Path $Results 'residual_train.json') -Force
    Set-Content -LiteralPath (Join-Path $Results '.residual_best_seed') -Value $best.seed
    Set-Content -LiteralPath (Join-Path $Results '.residual_best_score') -Value $best.score
}

function BackupSwitchingMi14() {
    $bak = Join-Path $Out 'switching_baseline_backup'
    New-Item -ItemType Directory -Force -Path $bak | Out-Null
    foreach ($name in @('p3_full320_sw_mi14.mat', 'p3_full320_switching_summary.json')) {
        $p = Join-Path $Results $name
        if (Test-Path -LiteralPath $p) {
            Move-Item -LiteralPath $p -Destination (Join-Path $bak $name) -Force
        }
    }
}

Log "overnight residual pipeline start root=$Root steps=$Steps proxy_goal=$ProxyGoal"

$snapshots = @()
$currentPidPath = Join-Path $Results '.residual_current_pid'
if (Test-Path -LiteralPath $currentPidPath) {
    $pidVal = [int](Get-Content -LiteralPath $currentPidPath)
    $p = Get-Process -Id $pidVal -ErrorAction SilentlyContinue
    if ($p) {
        Log "waiting for current residual training pid=$pidVal"
        Wait-Process -Id $pidVal
    }
}

$currentRunId = ''
$currentRunPath = Join-Path $Results '.residual_current_runid'
if (Test-Path -LiteralPath $currentRunPath) { $currentRunId = Get-Content -LiteralPath $currentRunPath }
if (Test-Path -LiteralPath (Join-Path $Results 'residual_train.json')) {
    $snapshots += [pscustomobject]@{
        seed = 42
        run_id = $currentRunId
        score = (ResidualScore (Join-Path $Results 'residual_train.json'))
        dir = (SnapshotSeed 42 $currentRunId)
    }
} else {
    Log "current training did not produce residual_train.json; retraining seed 42"
    TrainSeed 42
    $snapshots += (Get-Content -LiteralPath (Join-Path $Out 'seed_42\snapshot.json') -Raw | ConvertFrom-Json)
}

$bestScore = ($snapshots | Sort-Object -Property score -Descending | Select-Object -First 1).score
foreach ($seed in $ExtraSeeds) {
    if ($bestScore -ge $ProxyGoal) {
        Log "proxy goal met ($bestScore >= $ProxyGoal); skipping remaining seeds"
        break
    }
    TrainSeed $seed
    $snap = Get-Content -LiteralPath (Join-Path $Out "seed_$Seed\snapshot.json") -Raw | ConvertFrom-Json
    $snapshots += $snap
    $bestScore = ($snapshots | Sort-Object -Property score -Descending | Select-Object -First 1).score
}

$snapshots | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Out 'seed_scores.json')
PromoteBestSnapshot $snapshots

Invoke-Step 'pytest focused after training' {
    & $Py -m pytest tests\test_error_analysis_visibility.py tests\test_metric_completeness.py tests\test_training_contract.py -q
}
Invoke-Step 'export residual weights' {
    $env:HPT_RESIDUAL_EXPORT_SELECT_FULL320 = '1'
    & $Py -m hpt_frt.device.export_residual
}
Invoke-Step 'ODE full-320 proxy' {
    & $Py -m hpt_frt.device.eval_full320_ode
}

if (!$SkipSwitching) {
    $matlab = Get-Command matlab -ErrorAction SilentlyContinue
    if ($matlab) {
        BackupSwitchingMi14
        $simDir = Join-Path $Root 'lab\simulink'
        Invoke-Step 'MATLAB full-320 switching mi14' {
            & $matlab.Source -batch "cd('$simDir'); frt_v2_full320_switching(14,1,320);"
        }
        Invoke-Step 'error analysis after switching' {
            & $Py -m hpt_frt.device.error_analysis_mi14
        }
    } else {
        Log 'MATLAB command not found; skipping switching full-320'
    }
}

Log 'overnight residual pipeline complete'
