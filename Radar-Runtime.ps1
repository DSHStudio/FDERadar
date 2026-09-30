function Resolve-RadarPython {
  param([string]$Root, [string]$Python='')
  if($Python){return $Python}
  foreach($radarRuntimeCandidate in @(
    (Join-Path $Root '.venv\Scripts\python.exe'),
    (Join-Path $Root '..\..\DOA\.venv\Scripts\python.exe')
  )){
    if(Test-Path -LiteralPath $radarRuntimeCandidate){
      return (Resolve-Path -LiteralPath $radarRuntimeCandidate).Path
    }
  }
  throw '请用-Python指定已安装requirements.txt的Python解释器。'
}
