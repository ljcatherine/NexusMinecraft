param([Parameter(Mandatory)][string]$HostName,[Parameter(Mandatory)][string]$User,[string]$Key="$env:USERPROFILE\.ssh\ps5_panel")
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
  & npm.cmd ci --prefix frontend
  if ($LASTEXITCODE) { throw 'Frontend dependencies failed' }
  & npm.cmd run build --prefix frontend
  if ($LASTEXITCODE) { throw 'Frontend build failed' }
  $bundle=Join-Path $env:TEMP 'ps5-panel-release.tar.gz'
  & tar -czf $bundle panel deploy frontend/dist requirements.txt requirements.lock.txt config.example.json README.md docs tests
  if ($LASTEXITCODE) { throw 'Packaging failed' }
  & scp -i $Key $bundle "${User}@${HostName}:ps5-panel-release.tar.gz"
  if ($LASTEXITCODE) { throw 'Transfer failed' }
  & ssh -t -i $Key "${User}@${HostName}" 'mkdir -p ~/ps5-panel-release && tar -xzf ~/ps5-panel-release.tar.gz -C ~/ps5-panel-release && cd ~/ps5-panel-release && sudo bash deploy/install.sh'
  if ($LASTEXITCODE) { throw 'Installation failed' }
} finally { Pop-Location }
