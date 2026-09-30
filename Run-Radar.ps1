param(
  [ValidateSet('init','doctor','run','report','test','collect','serve','cycle')][string]$Action='report',
  [string]$Task='检查已有信源并围绕Palantir本体与AI近期变化开展一轮研究，获取原文后提交有依据的理论笔记，报告局限。',
  [string]$Python=''
)
$ErrorActionPreference='Stop'
$taskRoot=$PSScriptRoot
. (Join-Path $PSScriptRoot 'Radar-Runtime.ps1')
$Python=Resolve-RadarPython -Root $taskRoot -Python $Python
Push-Location -LiteralPath $taskRoot
try {
  if($Action -eq 'test'){& $Python -m unittest discover -s . -p 'test_*.py' -v}
  elseif($Action -eq 'cycle'){& $Python cycle.py}
  elseif($Action -eq 'run'){& $Python agent.py run --task $Task}
  else{& $Python agent.py $Action}
  if($LASTEXITCODE -ne 0){throw "Radar退出代码：$LASTEXITCODE"}
} finally {Pop-Location}
