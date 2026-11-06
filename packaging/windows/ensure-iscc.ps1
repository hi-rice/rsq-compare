# Prefer the compiler supplied by the official Windows runner image.
$ErrorActionPreference = 'Stop'

function Find-InnoCompiler {
    if ($env:ISCC_EXE) {
        if (!(Test-Path -LiteralPath $env:ISCC_EXE -PathType Leaf)) {
            throw "ISCC_EXE points to a missing compiler: $env:ISCC_EXE"
        }
        return (Resolve-Path -LiteralPath $env:ISCC_EXE).Path
    }
    foreach ($base in @(${env:ProgramFiles(x86)}, $env:ProgramFiles)) {
        if (!$base) { continue }
        $candidate = Join-Path $base 'Inno Setup 6\ISCC.exe'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    return $null
}

$compiler = Find-InnoCompiler
if (!$compiler) {
    # Do not invent a package version or overwrite the runner's installed tool.
    choco install innosetup --yes --no-progress
    if ($LASTEXITCODE -ne 0) { throw "Chocolatey Inno Setup install failed: $LASTEXITCODE" }
    $compiler = Find-InnoCompiler
}
if (!$compiler) { throw 'ISCC.exe was not found after installation.' }

$info = (Get-Item -LiteralPath $compiler).VersionInfo
$version = [version]("{0}.{1}.{2}" -f $info.FileMajorPart, $info.FileMinorPart, $info.FileBuildPart)
if ($version.Major -ne 6 -or $version -lt [version]'6.3.0') {
    throw "Unsupported Inno Setup version $version. Require Inno Setup 6.3 or later in the 6.x series."
}
$hash = (Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash
Write-Host "Using Inno Setup $version ($compiler)"
Write-Host "ISCC SHA256: $hash"
$env:ISCC_EXE = $compiler
$env:INNO_SETUP_VERSION = $version.ToString()
if ($env:GITHUB_ENV) {
    "ISCC_EXE=$compiler" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
    "INNO_SETUP_VERSION=$version" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
}
