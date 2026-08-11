param(
    [string]$Tag = "current_puresac_vs_traditional_20260712"
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Results = Join-Path $Root 'lab\results'

Get-ChildItem -LiteralPath $Results -File -Filter "passset_*_${Tag}_mi*.csv" |
    Sort-Object Name |
    ForEach-Object {
        $rows = Import-Csv -LiteralPath $_.FullName
        $trueCount = @($rows | Where-Object frt -eq 'True').Count
        $falseCount = @($rows | Where-Object frt -eq 'False').Count
        $none = @($rows | Where-Object frt -eq 'None').Count
        $errorRows = @($rows | Where-Object frt -eq 'ERROR').Count
        [pscustomobject]@{
            file = $_.Name
            n = @($rows).Count
            true = $trueCount
            false = $falseCount
            none = $none
            error = $errorRows
            updated = $_.LastWriteTime
        }
    } | Format-Table -AutoSize
