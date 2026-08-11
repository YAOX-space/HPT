param(
    [int]$Steps = 40000,
    [string]$RunId = "pure_sac_full320_simlabel_repair_20260712",
    [string[]]$Experts = @('sym', 'asym', 'hvrt_sym', 'hvrt_asym'),
    [string]$SourceDir = "",
    [string]$SourceCombo = "",
    [double]$SimFailRewardScale = 1.0,
    [int]$NEnvs = 1,
    [int]$EvalFreq = 10000
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$Results = Join-Path $Root 'lab\results'
$Out = Join-Path $Results $RunId
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Log = Join-Path $Out 'train.log'

$env:HPT_FORCE_CPU = '1'
$env:CUDA_VISIBLE_DEVICES = '-1'
$env:PYTHONUNBUFFERED = '1'
$env:KMP_DUPLICATE_LIB_OK = 'TRUE'
$env:MKL_THREADING_LAYER = 'SEQUENTIAL'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:HPT_RUN_ID = $RunId
$env:HPT_SIMFAIL_REWARD_SCALE = [string]$SimFailRewardScale

$extraArgs = @()
if ($Experts.Count -gt 0) {
  $extraArgs += '--experts'
  $extraArgs += $Experts
}
if ($SourceDir -ne "") {
  $extraArgs += '--source-dir'
  $extraArgs += $SourceDir
}
if ($SourceCombo -ne "") {
  $combo = Get-Content $SourceCombo -Raw | ConvertFrom-Json
  $extraArgs += '--source-sym'
  $extraArgs += (Join-Path $Root $combo.model_paths.sym)
  $extraArgs += '--source-asym'
  $extraArgs += (Join-Path $Root $combo.model_paths.asym)
  $extraArgs += '--source-hvrt-sym'
  $extraArgs += (Join-Path $Root $combo.model_paths.hvrt_sym)
  $extraArgs += '--source-hvrt-asym'
  $extraArgs += (Join-Path $Root $combo.model_paths.hvrt_asym)
}

& $Py -m hpt_frt.device.pure_sac_hard_curriculum `
  --scenarios lab\frt_scenarios.csv `
  --repair-target-csv lab\results\repair_targets_full320_sim_repair_20260712.csv `
  --steps $Steps `
  --eval-freq $EvalFreq `
  --n-envs $NEnvs `
  --lr 5e-5 `
  --traditional-only-weight 64 `
  --hard-weight 24 `
  --switch-weight 48 `
  --shallow-hvrt-weight 16 `
  --deep-sym-weight 12 `
  --target-bonus-weight 0.10 `
  --min-val-proxy-for-target-bonus 55 `
  @extraArgs `
  2>&1 | Tee-Object -FilePath $Log -Append

if ($LASTEXITCODE -ne 0) {
    throw "pure SAC full320 sim-label repair failed with exit code $LASTEXITCODE"
}
