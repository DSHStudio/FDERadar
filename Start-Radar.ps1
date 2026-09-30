param([switch]$Restart,[string]$Python='')
$ErrorActionPreference='Stop'
$radarRoot=$PSScriptRoot
$radarPidFile=Join-Path $radarRoot 'var\server.pid'
. (Join-Path $PSScriptRoot 'Radar-Runtime.ps1')
$Python=Resolve-RadarPython -Root $radarRoot -Python $Python
if($Restart -and (Test-Path -LiteralPath $radarPidFile)){
  $radarProcessId=[int](Get-Content -LiteralPath $radarPidFile -Raw).Trim()
  $radarExisting=Get-CimInstance Win32_Process -Filter "ProcessId=$radarProcessId"
  if($radarExisting -and $radarExisting.CommandLine -match 'agent\.py\s+serve\s+--port\s+8765'){
    Stop-Process -Id $radarProcessId
  } elseif($radarExisting){throw 'PID已属于其他进程，拒绝停止。'}
}
$radarReady=$false
try{$radarState=Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/state' -TimeoutSec 2;$radarReady=($null -ne $radarState.capabilities)}catch{}
if(-not $radarReady){
  $radarProcess=Start-Process -FilePath $Python -ArgumentList @('agent.py','serve','--port','8765') -WorkingDirectory $radarRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $radarRoot 'var\server.log') -RedirectStandardError (Join-Path $radarRoot 'var\server-error.log') -PassThru
  $radarProcess.Id | Set-Content -LiteralPath $radarPidFile
  for($radarTry=0;$radarTry -lt 15;$radarTry++){
    try{$radarState=Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/state' -TimeoutSec 1;$radarReady=($null -ne $radarState.capabilities);if($radarReady){break}}catch{}
    Start-Sleep -Milliseconds 200
  }
}
if(-not $radarReady){throw '本地服务未启动，请检查var/server-error.log。'}
Write-Output 'FDE研究工作台：http://127.0.0.1:8765'
