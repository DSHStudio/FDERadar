param(
  [ValidateSet('install','pack','verify','run')][string]$Action='install',
  [string]$Task='',
  [string]$Python=''
)
$ErrorActionPreference='Stop'
$pluginRoot=$PSScriptRoot
. (Join-Path $PSScriptRoot 'Radar-Runtime.ps1')
$Python=Resolve-RadarPython -Root $pluginRoot -Python $Python
if($Action -eq 'run' -and -not $Task.Trim()){throw '请用-Task提供要交给DSH插件的任务。'}
Push-Location -LiteralPath $pluginRoot
try {
  if($Action -in @('run','verify')){ & (Join-Path $pluginRoot 'Start-Radar.ps1') -Python $Python }
  if($Action -eq 'run'){ & $Python dsh_plugin.py run --task $Task }
  else { & $Python dsh_plugin.py $Action }
  if($LASTEXITCODE -ne 0){throw "DSH插件操作失败，退出代码：$LASTEXITCODE"}
} finally {Pop-Location}
