$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$distRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "dist"))
foreach ($relativePath in @("data", "logs")) {
    $stalePath = [System.IO.Path]::GetFullPath((Join-Path $distRoot $relativePath))
    if ([System.IO.Path]::GetDirectoryName($stalePath) -ne $distRoot) {
        throw "拒绝清理意外路径：$stalePath"
    }
    if (Test-Path -LiteralPath $stalePath) {
        $item = Get-Item -LiteralPath $stalePath -Force
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "拒绝清理重解析目录：$stalePath"
        }
        Remove-Item -LiteralPath $stalePath -Recurse -Force
    }
}
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean AIFileOrganizer.spec
$exe = Join-Path $PSScriptRoot "dist\AI File Organizer.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "EXE 构建失败：未找到 $exe"
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "USAGE.md") -Destination (Join-Path $PSScriptRoot "dist\USAGE.md") -Force
Write-Host "构建完成：$exe"
