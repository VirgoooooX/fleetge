param(
    [Parameter(Mandatory = $true)]
    [string] $Version,

    [string] $Remote = "origin",

    [switch] $WithAgent,

    [switch] $NoPush
)

$ErrorActionPreference = "Stop"

$Version = $Version.TrimStart("v")
if ($Version -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "Version must be semver, for example 0.1.1 or v0.1.1"
}

$status = git status --porcelain
if ($status) {
    throw "Working tree is not clean. Commit or stash changes before releasing."
}

function Assert-CommandSuccess([string] $Description) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

node scripts/set-version.mjs $Version
Assert-CommandSuccess "node scripts/set-version.mjs"

npm --prefix frontend test
Assert-CommandSuccess "frontend tests"

npm --prefix frontend run build
Assert-CommandSuccess "frontend build"

$PythonCmd = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } elseif (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" } else { "python" }

Push-Location backend
try {
    & $PythonCmd -m pytest tests
    Assert-CommandSuccess "backend tests"
}
finally {
    Pop-Location
}

if ($WithAgent) {
    Push-Location fleetge-agent
    try {
        & $PythonCmd -m pytest test_agent.py test_update_stage.py
        Assert-CommandSuccess "agent tests"
    }
    finally {
        Pop-Location
    }
}

git add VERSION backend/app/version.py frontend/package.json frontend/package-lock.json
$staged = git diff --cached --name-only
if ($staged) {
    git commit -m "chore: release v$Version"
}
else {
    git commit --allow-empty -m "chore: release v$Version"
}
$withAgentValue = if ($WithAgent) { "true" } else { "false" }
git tag -a "v$Version" -m "v$Version" -m "with-agent=$withAgentValue"

if (-not $NoPush) {
    git push $Remote HEAD
    git push $Remote "v$Version"
}

if ($WithAgent) {
    Write-Host "Release v$Version is ready. GitHub Actions will build app and agent images and create the release from the tag."
}
else {
    Write-Host "Release v$Version is ready. GitHub Actions will build the app image and create the release from the tag."
}
