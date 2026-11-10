# PokePal · 生成桌面快捷方式（右键 -> 使用 PowerShell 运行）
# 可选参数：
#   .\tools\install_shortcut.ps1                 # 只创建桌面快捷方式
#   .\tools\install_shortcut.ps1 -StartMenu      # 同时放进「开始」菜单

param([switch]$StartMenu)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Name = "PokePal · 宝可梦桌宠"
$Icon = Join-Path $Root "assets\app.ico"

# 挑一个能用的 pythonw（无控制台窗口），优先级：项目虚拟环境 > 已登记的 Python > PATH
$candidates = @(
    (Join-Path $Root ".venv\Scripts\pythonw.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\pythonw.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\pythonw.exe"),
    "pythonw.exe"
)
$pyw = $null
foreach ($c in $candidates) {
    if ($c -eq "pythonw.exe") {
        $cmd = Get-Command pythonw -ErrorAction SilentlyContinue
        if ($cmd) { $pyw = $cmd.Source; break }
        continue
    }
    if (Test-Path $c) { $pyw = $c; break }
}
if (-not $pyw) { throw "没有找到 pythonw.exe，请先安装 Python（并勾选 tkinter）" }

$shell = New-Object -ComObject WScript.Shell

function New-Shortcut([string]$Target, [string]$LnkPath) {
    $sc = $shell.CreateShortcut($LnkPath)
    $sc.TargetPath = $pyw
    $sc.Arguments = '"main.py"'
    $sc.WorkingDirectory = $Root
    $sc.Description = "桌面上的宝可梦电子宠物"
    if (Test-Path $Icon) { $sc.IconLocation = "$Icon,0" }
    $sc.Save()
    Write-Output "已创建：$LnkPath"
}

$dest = [Environment]::GetFolderPath("Desktop")
New-Shortcut -Target $Root -LnkPath (Join-Path $dest "$Name.lnk")

if ($StartMenu) {
    $menu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    New-Shortcut -Target $Root -LnkPath (Join-Path $menu "$Name.lnk")
}

Write-Output "解释器：$pyw"
if (Test-Path $Icon) { Write-Output "图标：$Icon" } else { Write-Output "图标：未生成（用 python tools/make_icon.py 生成）" }
