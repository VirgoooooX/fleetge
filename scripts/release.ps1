param(
    [Parameter(Mandatory = $true)]
    [string] $Version,

    [string] $Remote = "origin",

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

node scripts/set-version.mjs $Version

npm --prefix frontend run build
Push-Location backend
try {
    python -m pytest tests
}
finally {
    Pop-Location
}

git add VERSION backend/app/version.py frontend/package.json frontend/package-lock.json
git commit -m "chore: release v$Version"
git tag -a "v$Version" -m "v$Version"

if (-not $NoPush) {
    git push $Remote HEAD
    git push $Remote "v$Version"
}

Write-Host "Release v$Version is ready. GitHub Actions will build images and create the release from the tag."
