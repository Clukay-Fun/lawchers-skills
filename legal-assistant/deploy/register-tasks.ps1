# legal-assistant Windows 任务计划程序注册脚本
# 用法：powershell -ExecutionPolicy Bypass -File deploy\register-tasks.ps1
#      [-ConfigPath D:\legal-assistant\config.yaml] [-PollMinutes 10]
#      [-WeeklyDay Friday] [-WeeklyTime 16:00]     # 汇总推送的星期与时间，自行调整
# 注销：powershell -File deploy\register-tasks.ps1 -Unregister

param(
    [string]$ConfigPath = "D:\legal-assistant\config.yaml",
    [int]$PollMinutes = 10,
    [ValidateSet("Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday")]
    [string]$WeeklyDay = "Friday",
    [string]$WeeklyTime = "16:00",
    [switch]$Unregister
)

$TaskNames = @(
    "legal-assistant-invoice",
    "legal-assistant-scan",
    "legal-assistant-output-invoice",
    "legal-assistant-weekly"
)

if ($Unregister) {
    foreach ($name in $TaskNames) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "已注销 $name"
    }
    exit 0
}

# 定位 legal-assistant 可执行文件（pip 安装的入口脚本）
$exe = (Get-Command legal-assistant -ErrorAction SilentlyContinue).Source
if (-not $exe) {
    Write-Error "找不到 legal-assistant，请先 pip install -e `".[pdf]`" 并确认 Scripts 目录在 PATH"
    exit 1
}
if (-not (Test-Path $ConfigPath)) {
    Write-Error "找不到配置 $ConfigPath（用 -ConfigPath 指定）"
    exit 1
}

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -MultipleInstances IgnoreNew

function Register-Poll($name, $subcommand) {
    $action = New-ScheduledTaskAction -Execute $exe -Argument "$subcommand --config `"$ConfigPath`""
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
        -RepetitionInterval (New-TimeSpan -Minutes $PollMinutes)
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
        -Settings $settings -Force | Out-Null
    Write-Host "已注册 $name（每 $PollMinutes 分钟：legal-assistant $subcommand）"
}

# 三个轮询任务
Register-Poll "legal-assistant-invoice" "invoice-once"
Register-Poll "legal-assistant-scan" "scan-once"
Register-Poll "legal-assistant-output-invoice" "output-invoice-once"

# 定时汇总（星期与时间由 -WeeklyDay / -WeeklyTime 自定义）
$action = New-ScheduledTaskAction -Execute $exe -Argument "weekly-summary --config `"$ConfigPath`""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $WeeklyDay -At $WeeklyTime
Register-ScheduledTask -TaskName "legal-assistant-weekly" -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null
Write-Host "已注册 legal-assistant-weekly（每 $WeeklyDay $WeeklyTime）"

Write-Host "`n全部注册完成。验证：Get-ScheduledTask -TaskName 'legal-assistant-*'"
