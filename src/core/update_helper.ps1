$ErrorActionPreference = 'Stop'
$job = [IO.Path]::GetFullPath($PSScriptRoot)
$root = Split-Path -LiteralPath $job
$lock = Join-Path $root 'active.json'
$owned = $false
$changed = [Collections.Generic.List[string]]::new()
$success = $false
$config = $null

function Assert-NoLink([string] $path) {
    $current = [IO.Path]::GetFullPath($path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            if ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Linked path: $current"
            }
        }
        $parent = [IO.Path]::GetDirectoryName($current)
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

function Assert-Tree([string] $path) {
    Assert-NoLink $path
    foreach ($entry in Get-ChildItem -LiteralPath $path -Force) {
        Assert-NoLink $entry.FullName
        if ($entry.PSIsContainer) { Assert-Tree $entry.FullName }
    }
}

function Program-Path([string] $base, [string] $relative) {
    $parts = $relative -split '[\\/]'
    if ([IO.Path]::IsPathRooted($relative)) { throw 'Absolute program path' }
    foreach ($part in $parts) {
        if (!$part -or $part -in @('.', '..', '.git', 'data', 'data_dev', 'profiles', 'recordings',
            'cache', 'logs', 'update_tmp', 'audio_visual', 'audio_visual_dev', 'tests', '__pycache__') -or
            $part -match '[:<>"|?*\x00-\x1f]|[. ]$|^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)') {
            throw "Unsafe program path: $relative"
        }
    }
    $full = [IO.Path]::GetFullPath((Join-Path $base $relative))
    if (!$full.StartsWith($base.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Program path escapes target'
    }
    Assert-NoLink $full
    return $full
}

function Program-Files([string] $base, [bool] $verify) {
    $manifest = Join-Path $base 'program-files.sha256'
    Assert-NoLink $manifest
    $files = @{}
    foreach ($line in [IO.File]::ReadAllLines($manifest, [Text.Encoding]::UTF8)) {
        if ($line -notmatch '^([a-fA-F0-9]{64})  (.+)$') { throw 'Invalid program manifest' }
        $hash = $Matches[1]
        $relative = $Matches[2]
        $full = Program-Path $base $relative
        if ($files.ContainsKey($relative)) { throw 'Duplicate program path' }
        if ($verify -and (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash -ne $hash) {
            throw "Program hash mismatch: $relative"
        }
        $files[$relative] = $hash
    }
    if (!$files.ContainsKey('Mayotter.exe')) { throw 'Missing program executable' }
    return $files
}

function Assert-Target {
    $target = [IO.Path]::GetFullPath($config.target).TrimEnd('\')
    Assert-NoLink $target
    if ($target -eq [IO.Path]::GetPathRoot($target).TrimEnd('\') -or
        !(Test-Path -LiteralPath (Join-Path $target 'Mayotter.exe'))) { throw 'Invalid target' }
    $parent = $target
    while ($parent) {
        if ((Test-Path -LiteralPath (Join-Path $parent '.git')) -or
            (Test-Path -LiteralPath (Join-Path $parent 'pyproject.toml'))) { throw 'Development workspace' }
        if ((Split-Path $parent -Leaf) -in @('data', 'data_dev', 'profiles', 'recordings', 'audio_visual', 'audio_visual_dev')) {
            throw 'User data directory'
        }
        $parent = [IO.Path]::GetDirectoryName($parent)
    }
    foreach ($name in @('src', 'data_dev')) {
        if (Test-Path -LiteralPath (Join-Path $target $name)) { throw 'Development directory' }
    }
    foreach ($base in @($env:SystemRoot, $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramData,
                        (Join-Path $env:LOCALAPPDATA 'Mayotter'))) {
        if ($base -and ($target -eq $base -or $target.StartsWith($base.TrimEnd('\') + '\',
                         [StringComparison]::OrdinalIgnoreCase))) { throw 'Protected directory' }
    }
    if ($target -eq (Join-Path $env:USERPROFILE 'Documents\Mayotter')) { throw 'Protected workspace' }
    foreach ($entry in Get-ChildItem -LiteralPath $target -Force) {
        Assert-NoLink $entry.FullName
        if ($entry.Extension -eq '.exe' -and $entry.Name -notin @('Mayotter.exe', 'unins000.exe')) {
            throw 'Another application is present'
        }
    }
    if ($config.installed) {
        $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($config.registry)
        if (!$key) { throw 'Missing installation registration' }
        try { $registered = $key.GetValue('InstallLocation') } finally { $key.Dispose() }
        if (!$registered -or [IO.Path]::GetFullPath($registered).TrimEnd('\') -ne $target -or
            !(Test-Path -LiteralPath (Join-Path $target 'mayotter-installed.ini'))) { throw 'Installation mismatch' }
    } elseif (Test-Path -LiteralPath (Join-Path $target 'mayotter-installed.ini')) { throw 'Setup required' }
}

try {
    Assert-NoLink $job
    if ((Split-Path $job -Leaf) -notmatch '^job-([0-9a-f]{32})$') { throw 'Invalid job name' }
    $token = $Matches[1]
    $owner = Get-Content -LiteralPath (Join-Path $job 'owner.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $config = Get-Content -LiteralPath (Join-Path $job 'apply.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-NoLink $lock
    $active = Get-Content -LiteralPath $lock -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($owner.application -ne 'Mayotter' -or $owner.token -ne $token -or
        $config.token -ne $token -or $active.token -ne $token -or $active.pid -ne $config.parent_pid) {
        throw 'Update ownership mismatch'
    }
    $owned = $true
    Assert-Target
    if ([IO.Path]::GetDirectoryName($config.package) -ne $job) { throw 'Package outside session' }
    Assert-NoLink $config.package
    if ((Get-FileHash -LiteralPath $config.package -Algorithm SHA256).Hash -ne $config.sha256) {
        throw 'Package hash mismatch'
    }
    $owner.pid = $PID
    $owner | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $job 'owner.json') -Encoding UTF8
    $owner | ConvertTo-Json -Compress | Set-Content -LiteralPath $lock -Encoding UTF8
    [IO.File]::WriteAllText((Join-Path $job 'ready'), 'ready')
    # Show a progress window from now until this helper exits (after the restart), so the user does not
    # think the application has disappeared while Setup is running. A failure here never stops the update.
    if ($config.notice_title) {
        try {
            $quote = { param($text) "'" + ([string]$text).Replace("'", "''") + "'" }
            $notice = @'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$title = __TITLE__; $text = __TEXT__; $helperPid = __PID__
$colors = @{ bg = __BG__; border = __BORDER__; fg = __FG__; muted = __MUTED__; accent = __ACCENT__ }
$family = __FONT__
$tint = @{}
foreach ($name in $colors.Keys) { $tint[$name] = [Drawing.ColorTranslator]::FromHtml($colors[$name]) }
$width = 440; $height = 128; $radius = 12
$form = New-Object Windows.Forms.Form
# Double buffering avoids flicker (DoubleBuffered is a protected property).
[Windows.Forms.Control].GetProperty('DoubleBuffered', [Reflection.BindingFlags]'Instance,NonPublic').SetValue($form, $true)
$form.Text = $title; $form.FormBorderStyle = 'None'; $form.ShowInTaskbar = $false; $form.TopMost = $true
$form.StartPosition = 'CenterScreen'; $form.ClientSize = New-Object Drawing.Size($width, $height); $form.BackColor = $tint.bg
$form.Opacity = 0
function New-RoundedPath([single] $x, [single] $y, [single] $w, [single] $h, [single] $r) {
    $p = New-Object Drawing.Drawing2D.GraphicsPath
    $d = $r * 2
    $p.AddArc($x, $y, $d, $d, 180, 90); $p.AddArc($x + $w - $d, $y, $d, $d, 270, 90)
    $p.AddArc($x + $w - $d, $y + $h - $d, $d, $d, 0, 90); $p.AddArc($x, $y + $h - $d, $d, $d, 90, 90)
    $p.CloseFigure()
    return $p
}
$path = New-RoundedPath 0 0 ($width - 1) ($height - 1) $radius
$form.Region = New-Object Drawing.Region((New-RoundedPath 0 0 $width $height $radius))
$titleFont = New-Object Drawing.Font($family, 11, [Drawing.FontStyle]::Bold, [Drawing.GraphicsUnit]::Point)
$bodyFont = New-Object Drawing.Font($family, 9, [Drawing.FontStyle]::Regular, [Drawing.GraphicsUnit]::Point)
$bar = @{ x = 20; y = 102; w = ($width - 40); h = 6 }
$state = @{ phase = 0.0 }
$trackPath = New-RoundedPath $bar.x $bar.y $bar.w $bar.h 3
$trackRect = New-Object Drawing.Rectangle($bar.x, ($bar.y - 1), $bar.w, ($bar.h + 2))
$form.Add_Paint({
    param($sender, $e)
    $g = $e.Graphics
    $g.SmoothingMode = 'AntiAlias'; $g.TextRenderingHint = 'ClearTypeGridFit'
    $g.DrawPath((New-Object Drawing.Pen($tint.border, 1)), $path)
    $g.DrawString($title, $titleFont, (New-Object Drawing.SolidBrush($tint.fg)), 20, 18)
    $g.DrawString($text, $bodyFont, (New-Object Drawing.SolidBrush($tint.muted)), (New-Object Drawing.RectangleF(20, 48, ($width - 40), 46)))
    $g.FillPath((New-Object Drawing.SolidBrush($tint.border)), $trackPath)
    $g.SetClip($trackPath)
    $segment = $bar.w * 0.34
    $left = $bar.x - $segment + ($bar.w + $segment) * $state.phase
    $g.FillPath((New-Object Drawing.SolidBrush($tint.accent)), (New-RoundedPath $left $bar.y $segment $bar.h 3))
    $g.ResetClip()
})
# Frame-rate independent motion: the bar eases back and forth (sine) and the window fades in and out.
$clock = [Diagnostics.Stopwatch]::StartNew()
$state.closing = $null
$timer = New-Object Windows.Forms.Timer
$timer.Interval = 16
$timer.Add_Tick({
    $ms = $clock.ElapsedMilliseconds
    $state.phase = 0.5 - 0.5 * [Math]::Cos([Math]::PI * 2 * (($ms % 1500) / 1500.0))
    $form.Invalidate($trackRect, $false)
    if ($state.closing -eq $null) {
        $t = [Math]::Min(1.0, $ms / 220.0)
        $form.Opacity = 1 - [Math]::Pow(1 - $t, 3)
        if ($ms % 500 -lt 16 -and $ms -gt 600 -and (!(Get-Process -Id $helperPid -ErrorAction SilentlyContinue) -or $ms -gt 900000)) { $state.closing = $ms }
    } else {
        $t = [Math]::Min(1.0, ($ms - $state.closing) / 200.0)
        $form.Opacity = 1 - $t * $t
        if ($t -ge 1.0) { $form.Close() }
    }
})
$timer.Start()
$form.Add_Shown({ $form.Activate() })
[Windows.Forms.Application]::Run($form)
'@
            $style = @{ __BG__ = $config.notice_bg; __BORDER__ = $config.notice_border; __FG__ = $config.notice_fg
                        __MUTED__ = $config.notice_muted; __ACCENT__ = $config.notice_accent; __FONT__ = $config.notice_font }
            $fallback = @{ __BG__ = '#181c26'; __BORDER__ = '#2b3242'; __FG__ = '#f1f3f7'; __MUTED__ = '#aeb6c5'
                           __ACCENT__ = '#5b8fd6'; __FONT__ = 'Yu Gothic UI' }
            foreach ($key in $fallback.Keys) {
                $value = if ($style[$key]) { $style[$key] } else { $fallback[$key] }
                $notice = $notice.Replace($key, (& $quote $value))
            }
            $notice = $notice.Replace('__TITLE__', (& $quote $config.notice_title)).Replace('__TEXT__', (& $quote $config.notice_text)).Replace('__PID__', [string]$PID)
            $encodedNotice = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($notice))
            Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -WindowStyle Hidden -ArgumentList @(
                '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Sta', '-EncodedCommand', $encodedNotice) | Out-Null
        } catch {}
    }
    $parent = Get-Process -Id $config.parent_pid -ErrorAction SilentlyContinue
    if ($parent -and !$parent.WaitForExit(120000)) { throw 'Application did not exit; update cancelled' }
    Assert-Target
    if ($config.installed) {
        # /DIR is the verified registered location; Setup keeps the same AppId and uninstall log.
        $arguments = '/SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /DIR="' +
                     $config.target + '" /LOG="' + (Join-Path $job 'setup.log') + '"'
        $installer = Start-Process -FilePath $config.package -ArgumentList $arguments -PassThru -WindowStyle Hidden
        $installer.WaitForExit()
        if ($installer.ExitCode -ne 0) { throw "Setup exit code: $($installer.ExitCode)" }
        Assert-Target
    } else {
        Assert-Tree $config.stage
        if (!$config.stage.StartsWith($job + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid stage' }
        $files = Program-Files $config.stage $true
        foreach ($name in @('mayotter-installed.ini', 'unins000.exe', 'unins000.dat')) {
            if ($files.ContainsKey($name)) { throw 'Installer metadata in ZIP payload' }
        }
        $files['program-files.sha256'] = (Get-FileHash -LiteralPath (Join-Path $config.stage 'program-files.sha256')).Hash
        $backup = Join-Path $job 'backup'
        [IO.Directory]::CreateDirectory($backup) | Out-Null
        foreach ($relative in $files.Keys) {
            $destination = Program-Path $config.target $relative
            $source = Program-Path $config.stage $relative
            $saved = Program-Path $backup $relative
            if (Test-Path -LiteralPath $destination -PathType Leaf) {
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($saved)) | Out-Null
                [IO.File]::Copy($destination, $saved, $false)
            }
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
            $changed.Add($relative)
            [IO.File]::Copy($source, $destination, $true)
        }
    }
    $null = Program-Files $config.target $true
    $version = Get-Content -LiteralPath (Join-Path $config.target 'release-info.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($version.version -ne $config.version) { throw 'Installed version mismatch' }
    $success = $true
} catch {
    $failure = $_.Exception.Message
    if ($config -and !$config.installed -and $changed.Count) {
        try {
            Assert-Target
            for ($i = $changed.Count - 1; $i -ge 0; $i--) {
                $relative = $changed[$i]
                $destination = Program-Path $config.target $relative
                $saved = Program-Path (Join-Path $job 'backup') $relative
                if (Test-Path -LiteralPath $saved -PathType Leaf) { [IO.File]::Copy($saved, $destination, $true) }
                else { [IO.File]::Delete($destination) }
            }
        } catch {
            $failure += '; rollback failed: ' + $_.Exception.Message
            [IO.File]::WriteAllText((Join-Path $job 'needs-recovery'), $failure)
            $owned = $false
        }
    }
} finally {
    if ($owned) {
        try {
            Assert-NoLink $lock
            $active = Get-Content -LiteralPath $lock -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($active.token -ne $token) { throw 'Update lock changed' }
            @{ success = $success; version = $config.version; error = $failure; time = [DateTime]::UtcNow.ToString('o') } |
                ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'last-result.json') -Encoding UTF8
            # The job directory is this process's working directory and holds this running script, so
            # neither can be removed from here. Leave it first.
            Set-Location -LiteralPath $root
            Assert-Tree $job
            # Restart first: a cleanup problem must never prevent the updated application from starting.
            if ($success -and $config.restart) {
                Start-Process -FilePath (Join-Path $config.target 'Mayotter.exe') -WorkingDirectory $config.target
            }
            # Only the owner-verified job is removed; the shared update_tmp and the install directory are kept.
            # Remove everything except this running script now; a detached process removes the rest and the
            # lock after this process has exited.
            Get-ChildItem -LiteralPath $job -Force | Where-Object { $_.FullName -ne $PSCommandPath } |
                Remove-Item -Recurse -Force
            $quoted = @($job, $lock) | ForEach-Object { "'" + $_.Replace("'", "''") + "'" }
            $cleanup = "`$ErrorActionPreference = 'SilentlyContinue'; Wait-Process -Id $PID -Timeout 60; " +
                       "Remove-Item -LiteralPath $($quoted[0]) -Recurse -Force; Remove-Item -LiteralPath $($quoted[1]) -Force"
            $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cleanup))
            Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -WindowStyle Hidden `
                -ArgumentList @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded)
        } catch {
            # If cleanup is not possible, keep the job; it is reclaimed after an ownership check next time.
            Write-Error $_ -ErrorAction Continue
        }
    }
}
if (!$success) { exit 1 }
