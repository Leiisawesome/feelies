# CI-watch run-set extract (D-209, D-211). Reads completed pull_request runs of ci.yml created from CreatedFrom through CreatedTo (UTC dates, inclusive) and writes one CSV.
param(
    [string]$CreatedFrom = '2026-10-08',
    [string]$CreatedTo = '2026-10-20',
    [ValidateSet('latest', 'first', IgnoreCase = $false)][string]$Attempt = 'latest',
    [Parameter(Mandatory = $true)][string]$OutputPath
)
$exactDate = 'yyyy-MM-dd'
$dateCulture = [Globalization.CultureInfo]::InvariantCulture
$parsedFrom = [datetime]::MinValue
$parsedTo = [datetime]::MinValue
if (-not [datetime]::TryParseExact($CreatedFrom, $exactDate, $dateCulture, [Globalization.DateTimeStyles]::None, [ref]$parsedFrom)) {
    throw "CreatedFrom must be yyyy-MM-dd: $CreatedFrom"
}
if (-not [datetime]::TryParseExact($CreatedTo, $exactDate, $dateCulture, [Globalization.DateTimeStyles]::None, [ref]$parsedTo)) {
    throw "CreatedTo must be yyyy-MM-dd: $CreatedTo"
}
if ($parsedFrom -gt $parsedTo) {
    throw "CreatedFrom is after CreatedTo"
}
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$ErrorActionPreference = 'Continue'
$env:GH_PROMPT_DISABLED = '1'
$env:GH_NO_UPDATE_NOTIFIER = '1'

$CsvPath = $OutputPath
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $CsvPath) | Out-Null

$Repo = 'Leiisawesome/feelies'
$CheckJobName = 'check (ubuntu-latest)'
$TestsStepName = 'Tests'
$DetStepName = 'Determinism under an unpinned hash seed'
$SetupStepName = 'Set up job'
$Inv = [Globalization.CultureInfo]::InvariantCulture

function Assert-True {
    param([bool]$Condition, [string]$Label)
    if (-not $Condition) { throw "self-check failed: $Label" }
}

function ConvertTo-Dto {
    param([string]$Text)
    return [datetimeoffset]::Parse(
        $Text,
        $Inv,
        [Globalization.DateTimeStyles]::RoundtripKind)
}

function Get-LabelCount {
    param([string]$Text, [string]$Label)
    $re = [regex]('(?<![A-Za-z])(\d+)\s+' + [regex]::Escape($Label) + '\b')
    $found = $re.Match($Text)
    if (-not $found.Success) { return 0 }
    return [int]$found.Groups[1].Value
}

function Get-PytestSummary {
    param([string]$Message)
    $re = [regex]'^\s*(?<counts>.+?)\s+in\s+(?<secs>\d+(?:\.\d+)?)s(?:\s+\([^)]*\))?\s*$'
    $found = $re.Match($Message.Trim())
    if (-not $found.Success) { return $null }
    $counts = $found.Groups['counts'].Value
    $looksLike = $counts -cmatch '(?<![A-Za-z])(passed|failed|errors|error|skipped)\b'
    if (-not $looksLike) { return $null }
    $secs = [decimal]::Parse($found.Groups['secs'].Value, $Inv)
    return [pscustomobject]@{
        Passed     = (Get-LabelCount $counts 'passed')
        Skipped    = (Get-LabelCount $counts 'skipped')
        Deselected = (Get-LabelCount $counts 'deselected')
        XFailed    = (Get-LabelCount $counts 'xfailed')
        Failed     = (Get-LabelCount $counts 'failed')
        Seconds    = $secs
        Raw        = $Message.Trim()
    }
}

function Test-HasN4 {
    param([string]$Text)
    return [bool]($Text -cmatch '-n 4(?!\d)')
}

function Format-Fixed2 {
    param([decimal]$Value)
    return $Value.ToString('0.00', $Inv)
}

function Format-CsvField {
    param([string]$Value)
    if ($null -eq $Value) { $Value = '' }
    return '"' + ([string]$Value).Replace('"', '""') + '"'
}

function Remove-Ansi {
    param([string]$Text)
    $re = [regex]([char]27 + '\[[0-9;]*[A-Za-z]')
    return $re.Replace($Text, '')
}

function Split-LogLine {
    param([string]$Line)
    $clean = $Line.TrimStart([char]0xFEFF).TrimEnd("`r")
    if ($clean.Length -eq 0) { return $null }
    $parts = $clean.Split(@([char]9), 3)
    if ($parts.Count -lt 3) {
        return [pscustomobject]@{
            StepColumn = ''
            Time       = $null
            Message    = $clean
            Parsed     = $false
        }
    }
    $rest = $parts[2].TrimStart([char]0xFEFF)
    $re = [regex]'^(?<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s(?<msg>.*)$'
    $found = $re.Match($rest)
    if (-not $found.Success) {
        return [pscustomobject]@{
            StepColumn = $parts[1]
            Time       = $null
            Message    = (Remove-Ansi $rest)
            Parsed     = $false
        }
    }
    return [pscustomobject]@{
        StepColumn = $parts[1]
        Time       = (ConvertTo-Dto $found.Groups['ts'].Value)
        Message    = (Remove-Ansi $found.Groups['msg'].Value)
        Parsed     = $true
    }
}

function Resolve-AssignedStep {
    param($Parsed, $Steps)
    foreach ($step in $Steps) {
        if ($Parsed.StepColumn -ceq $step.Name) {
            return [pscustomobject]@{ Name = $step.Name; Method = 'column' }
        }
    }
    if (-not $Parsed.Parsed -or $null -eq $Parsed.Time) {
        return [pscustomobject]@{ Name = ''; Method = 'unparsed' }
    }
    $cands = @()
    foreach ($step in $Steps) {
        $windowEnd = $step.End.AddSeconds(1)
        if ($Parsed.Time -ge $step.Start -and $Parsed.Time -lt $windowEnd) {
            $cands += $step
        }
    }
    if ($cands.Count -eq 0) {
        return [pscustomobject]@{ Name = ''; Method = 'outside' }
    }
    if ($cands.Count -eq 1) {
        return [pscustomobject]@{ Name = $cands[0].Name; Method = 'timestamp-unique' }
    }
    $ordered = @($cands | Sort-Object Start, Index)
    $msg = $Parsed.Message.TrimStart()
    if ($msg.StartsWith('##[group]Run ')) {
        $pick = $ordered[$ordered.Count - 1]
        return [pscustomobject]@{ Name = $pick.Name; Method = 'timestamp-tie-later' }
    }
    $pick = $ordered[0]
    return [pscustomobject]@{ Name = $pick.Name; Method = 'timestamp-tie-earlier' }
}

function Get-CheckSeconds {
    param([datetimeoffset]$Start, [datetimeoffset]$End)
    return [decimal]($End.UtcTicks - $Start.UtcTicks) / [decimal]10000000
}

function ConvertTo-JoinedText {
    param($Raw)
    if ($null -eq $Raw) { return '' }
    return ((@($Raw) | ForEach-Object { [string]$_ }) -join "`n")
}

# Offline lock of the parser against the observed 39246191888 log shape.
$sampleSteps = @(
    [pscustomobject]@{ Name = 'Set up job'; Index = 0; Start = (ConvertTo-Dto '2026-10-19T11:39:20Z'); End = (ConvertTo-Dto '2026-10-19T11:39:21Z') }
    [pscustomobject]@{ Name = 'Run actions/checkout@v4'; Index = 1; Start = (ConvertTo-Dto '2026-10-19T11:39:21Z'); End = (ConvertTo-Dto '2026-10-19T11:39:23Z') }
    [pscustomobject]@{ Name = 'Generate the hot-path executed set'; Index = 2; Start = (ConvertTo-Dto '2026-10-19T11:39:39Z'); End = (ConvertTo-Dto '2026-10-19T11:40:23Z') }
    [pscustomobject]@{ Name = 'Tests'; Index = 3; Start = (ConvertTo-Dto '2026-10-19T11:40:23Z'); End = (ConvertTo-Dto '2026-10-19T11:48:19Z') }
    [pscustomobject]@{ Name = 'Determinism under an unpinned hash seed'; Index = 4; Start = (ConvertTo-Dto '2026-10-19T11:48:19Z'); End = (ConvertTo-Dto '2026-10-19T11:48:27Z') }
)
function Test-SampleAssign {
    param([string]$Stamp, [string]$Message, [string]$ExpectName, [string]$ExpectMethod)
    $line = "check (ubuntu-latest)`tUNKNOWN STEP`t$Stamp $Message"
    $parsed = Split-LogLine $line
    Assert-True ($parsed.Parsed) "parse $Stamp"
    $assigned = Resolve-AssignedStep $parsed $sampleSteps
    Assert-True ($assigned.Name -ceq $ExpectName) "step $Stamp got $($assigned.Name)"
    Assert-True ($assigned.Method -ceq $ExpectMethod) "method $Stamp got $($assigned.Method)"
}
Test-SampleAssign '2026-10-19T11:39:20.6208223Z' 'Image: ubuntu-24.04' 'Set up job' 'timestamp-unique'
Test-SampleAssign '2026-10-19T11:39:20.6208554Z' 'Version: 20261012.334.1' 'Set up job' 'timestamp-unique'
Test-SampleAssign '2026-10-19T11:40:23.6941445Z' '##[group]Run uv run pytest -m "$(cat scripts/ci_gate_expr.txt)" -q -n 4' 'Tests' 'timestamp-tie-later'
Test-SampleAssign '2026-10-19T11:48:19.1413425Z' '5371 passed, 5 skipped, 2 xfailed, 50 warnings in 474.32s (0:07:54)' 'Tests' 'timestamp-tie-earlier'
Test-SampleAssign '2026-10-19T11:48:19.5062994Z' '##[group]Run uv run pytest tests/determinism/ -q' 'Determinism under an unpinned hash seed' 'timestamp-tie-later'
Test-SampleAssign '2026-10-19T11:48:26.8277331Z' '148 passed, 1 warning in 6.73s' 'Determinism under an unpinned hash seed' 'timestamp-unique'
$bomLine = "check (ubuntu-latest)`tTests`t" + [char]0xFEFF + '2026-10-20T10:20:05.8486612Z ##[group]Run uv run pytest -q -n 4'
$bomParsed = Split-LogLine $bomLine
Assert-True ($bomParsed.Parsed) 'bom parsed'
Assert-True (Test-HasN4 $bomParsed.Message) 'bom n4'
$bomAssigned = Resolve-AssignedStep $bomParsed $sampleSteps
Assert-True ($bomAssigned.Name -ceq 'Tests') 'bom step'
Assert-True ($bomAssigned.Method -ceq 'column') 'bom method'

$testsSample = Get-PytestSummary '5371 passed, 5 skipped, 2 xfailed, 50 warnings in 474.32s (0:07:54)'
Assert-True ($null -ne $testsSample) 'tests summary'
Assert-True ($testsSample.Passed -eq 5371) 'tests passed'
Assert-True ($testsSample.Skipped -eq 5) 'tests skipped'
Assert-True ($testsSample.Deselected -eq 0) 'tests deselected'
Assert-True ($testsSample.XFailed -eq 2) 'tests xfailed'
Assert-True ($testsSample.Failed -eq 0) 'tests failed'
Assert-True ($testsSample.Seconds -eq [decimal]'474.32') 'tests seconds'
$detSample = Get-PytestSummary '148 passed, 1 warning in 6.73s'
Assert-True ($null -ne $detSample) 'det summary'
Assert-True ($detSample.Passed -eq 148) 'det passed'
Assert-True ($detSample.Seconds -eq [decimal]'6.73') 'det seconds'
$ratioSample = [math]::Round($testsSample.Seconds / $detSample.Seconds, 2, [MidpointRounding]::AwayFromZero)
Assert-True ($ratioSample -eq [decimal]'70.48') 'ratio'
Assert-True ((Get-CheckSeconds (ConvertTo-Dto '2026-10-19T11:39:20Z') (ConvertTo-Dto '2026-10-19T11:48:29Z')) -eq 549) 'check_s'
Assert-True (Test-HasN4 '##[group]Run uv run pytest -m "$(cat scripts/ci_gate_expr.txt)" -q -n 4') 'n4 yes'
Assert-True (-not (Test-HasN4 '##[group]Run uv run pytest tests/determinism/ -q')) 'n4 no'
Assert-True (-not (Test-HasN4 'uv run pytest -n 40')) 'n4 forty'
Write-Output 'SELF_CHECK=PASS'

$worker = {
    param([string]$RunId, [string]$Attempt, [string]$Repo, [string]$CheckJobName)
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $OutputEncoding = [Console]::OutputEncoding
    $ErrorActionPreference = 'Continue'
    $result = [pscustomobject]@{
        RunId      = $RunId
        Error      = ''
        JobsText   = ''
        LogText    = ''
        LogFetched = $false
    }
    $jobsRaw = $null
    $jobsExit = 1
    foreach ($tryN in 1..3) {
        $jobsRaw = & gh run view $RunId --attempt $Attempt --repo $Repo --json jobs
        $jobsExit = $LASTEXITCODE
        if ($jobsExit -eq 0) { break }
        Start-Sleep -Seconds (5 * $tryN)
    }
    $jobsText = ''
    if ($null -ne $jobsRaw) {
        $jobsText = ((@($jobsRaw) | ForEach-Object { [string]$_ }) -join "`n")
    }
    $result.JobsText = $jobsText
    if ($jobsExit -ne 0) {
        $snip = $jobsText
        if ($snip.Length -gt 240) { $snip = $snip.Substring(0, 240) }
        $result.Error = "jobs_exit=$jobsExit $snip"
        $result
        return
    }
    try {
        $jobsObj = $jobsText | ConvertFrom-Json
    } catch {
        $result.Error = 'jobs_json_parse'
        $result
        return
    }
    $jobArr = @()
    if ($null -ne $jobsObj.jobs) { $jobArr = @($jobsObj.jobs) }
    $checkJobs = @()
    foreach ($job in $jobArr) {
        if ([string]$job.name -ceq $CheckJobName) { $checkJobs += $job }
    }
    if ($checkJobs.Count -ne 1 -or [string]$checkJobs[0].conclusion -cne 'success') {
        $result
        return
    }
    if ($null -eq $checkJobs[0].databaseId) {
        $result.Error = 'missing_job_id'
        $result
        return
    }
    $jobId = '{0:0}' -f $checkJobs[0].databaseId
    $logRaw = $null
    $logExit = 1
    foreach ($tryN in 1..3) {
        $logRaw = & gh run view $RunId --attempt $Attempt --repo $Repo --log --job $jobId
        $logExit = $LASTEXITCODE
        if ($logExit -eq 0) { break }
        Start-Sleep -Seconds (5 * $tryN)
    }
    $logText = ''
    if ($null -ne $logRaw) {
        $logText = ((@($logRaw) | ForEach-Object { [string]$_ }) -join "`n")
    }
    if ($logExit -ne 0) {
        $result.Error = "log_exit=$logExit"
        $result
        return
    }
    $result.LogText = $logText
    $result.LogFetched = $true
    $result
}

$pool = $null
$live = New-Object System.Collections.Generic.List[object]
try {
    $allRuns = @()
    $totalCount = $null
    $page = 1
    do {
        $endpoint = "repos/Leiisawesome/feelies/actions/workflows/ci.yml/runs?event=pull_request&status=completed&created=$CreatedFrom..$CreatedTo&per_page=100&page=$page"
        $apiRaw = $null
        $apiExit = 1
        foreach ($tryN in 1..3) {
            $apiRaw = & gh api $endpoint
            $apiExit = $LASTEXITCODE
            if ($apiExit -eq 0) { break }
            Start-Sleep -Seconds (5 * $tryN)
        }
        if ($apiExit -ne 0) { throw "api list exit $apiExit page $page" }
        $apiText = ConvertTo-JoinedText $apiRaw
        $apiObj = $apiText | ConvertFrom-Json
        if ($null -eq $totalCount) { $totalCount = [int]$apiObj.total_count }
        $batch = @()
        if ($null -ne $apiObj.workflow_runs) { $batch = @($apiObj.workflow_runs) }
        $allRuns += $batch
        $page++
    } while ($batch.Count -eq 100)

    if ($allRuns.Count -ne $totalCount) {
        throw "api count mismatch collected=$($allRuns.Count) total=$totalCount"
    }

    $cutFrom = ConvertTo-Dto ($parsedFrom.ToString($exactDate, $dateCulture) + 'T00:00:00Z')
    $cutTo = ConvertTo-Dto ($parsedTo.AddDays(1).ToString($exactDate, $dateCulture) + 'T00:00:00Z')
    $meta = New-Object 'System.Collections.Generic.Dictionary[string,object]' ([StringComparer]::Ordinal)
    $dropped = New-Object System.Collections.Generic.List[string]
    foreach ($run in $allRuns) {
        $id = '{0:0}' -f $run.id
        $eventName = [string]$run.event
        $statusName = [string]$run.status
        $created = [string]$run.created_at
        $createdAt = ConvertTo-Dto $created
        if ($eventName -cne 'pull_request' -or $statusName -cne 'completed' -or $createdAt -lt $cutFrom -or $createdAt -ge $cutTo) {
            $dropped.Add($id)
            continue
        }
        $meta[$id] = [pscustomobject]@{
            Id         = $id
            Attempt    = $(if ($Attempt -ceq 'first') { '1' } else { '{0:0}' -f $run.run_attempt })
            Created    = $created
            Branch     = [string]$run.head_branch
            Sha        = [string]$run.head_sha
            Conclusion = [string]$run.conclusion
            Status     = $statusName
            Event      = $eventName
        }
    }

    $listRaw = $null
    $listExit = 1
    foreach ($tryN in 1..3) {
        $listRaw = & gh run list --repo Leiisawesome/feelies --workflow ci.yml --event pull_request --status completed --created "$CreatedFrom..$CreatedTo" --limit 200 --json databaseId
        $listExit = $LASTEXITCODE
        if ($listExit -eq 0) { break }
        Start-Sleep -Seconds (5 * $tryN)
    }
    if ($listExit -ne 0) { throw "run list exit $listExit" }
    $listText = ConvertTo-JoinedText $listRaw
    $listItems = $listText | ConvertFrom-Json
    if ($listItems -isnot [System.Array]) { throw 'run list JSON was not an array' }
    if ($listItems.Count -ge 200) { throw 'run list hit limit 200' }
    if ($listItems.Count -eq 0) { throw 'run list JSON was empty' }
    $listIds = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    foreach ($row in $listItems) { [void]$listIds.Add(('{0:0}' -f $row.databaseId)) }
    $onlyApi = @()
    foreach ($id in $meta.Keys) {
        if (-not $listIds.Contains($id)) { $onlyApi += $id }
    }
    $onlyList = @()
    foreach ($id in $listIds) {
        if (-not $meta.ContainsKey($id)) { $onlyList += $id }
    }
    if ($onlyApi.Count -gt 0 -or $onlyList.Count -gt 0) {
        throw ("cross-check mismatch api_only=$($onlyApi -join ',') list_only=$($onlyList -join ',')")
    }
    Write-Output ("CROSS_CHECK=PASS api={0} run_list={1} dropped={2} total_count={3}" -f $meta.Count, $listIds.Count, $dropped.Count, $totalCount)

    $pool = [runspacefactory]::CreateRunspacePool(1, 4)
    $pool.Open()
    foreach ($item in $meta.Values) {
        $ps = [powershell]::Create()
        $ps.RunspacePool = $pool
        [void]$ps.AddScript($worker)
        [void]$ps.AddArgument($item.Id)
        [void]$ps.AddArgument($item.Attempt)
        [void]$ps.AddArgument($Repo)
        [void]$ps.AddArgument($CheckJobName)
        $handle = $ps.BeginInvoke()
        $live.Add([pscustomobject]@{
                PS       = $ps
                Handle   = $handle
                RunId    = $item.Id
                Disposed = $false
            })
    }

    $fetched = New-Object 'System.Collections.Generic.Dictionary[string,object]' ([StringComparer]::Ordinal)
    $pending = New-Object System.Collections.Generic.List[object]
    for ($liveIndex = 0; $liveIndex -lt $live.Count; $liveIndex++) { $pending.Add($live[$liveIndex]) }
    while ($pending.Count -gt 0) {
        Start-Sleep -Milliseconds 800
        for ($i = $pending.Count - 1; $i -ge 0; $i--) {
            $item = $pending[$i]
            if (-not $item.Handle.IsCompleted) { continue }
            $pending.RemoveAt($i)
            try {
                $outs = @($item.PS.EndInvoke($item.Handle))
                $hit = $null
                foreach ($out in $outs) {
                    if ($out -is [pscustomobject] -and $out.PSObject.Properties.Name -contains 'RunId') {
                        $hit = $out
                        break
                    }
                }
                if ($null -eq $hit) {
                    $errText = ''
                    foreach ($err in @($item.PS.Streams.Error)) { $errText += [string]$err }
                    if ($errText.Length -gt 240) { $errText = $errText.Substring(0, 240) }
                    $hit = [pscustomobject]@{
                        RunId      = $item.RunId
                        Error      = "empty_worker $errText"
                        JobsText   = ''
                        LogText    = ''
                        LogFetched = $false
                    }
                }
                $fetched[$item.RunId] = $hit
            } catch {
                $fetched[$item.RunId] = [pscustomobject]@{
                    RunId      = $item.RunId
                    Error      = [string]$_.Exception.Message
                    JobsText   = ''
                    LogText    = ''
                    LogFetched = $false
                }
            }
            $item.PS.Dispose()
            $item.Disposed = $true
            Write-Host ("fetched {0} remaining {1}" -f $fetched.Count, $pending.Count)
        }
    }

    $fatals = New-Object System.Collections.Generic.List[string]
    foreach ($id in $meta.Keys) {
        if (-not $fetched.ContainsKey($id)) { $fatals.Add("missing_worker $id") }
        elseif ($fetched[$id].Error) { $fatals.Add("$id $($fetched[$id].Error)") }
    }
    if ($fatals.Count -gt 0) {
        foreach ($fatal in $fatals) { Write-Output "FATAL $fatal" }
        throw "fetch failures=$($fatals.Count)"
    }

    $ordered = @($meta.Values | Sort-Object @{ Expression = { ConvertTo-Dto $_.Created } }, @{ Expression = { $_.Id } })
    $rows = New-Object System.Collections.Generic.List[object]
    $classLines = New-Object System.Collections.Generic.List[string]
    $excludedJob = 0
    $excludedN4 = 0
    $excludedSummary = 0
    $jobConclusionHist = New-Object 'System.Collections.Generic.Dictionary[string,int]' ([StringComparer]::Ordinal)
    $workflowHist = New-Object 'System.Collections.Generic.Dictionary[string,int]' ([StringComparer]::Ordinal)
    $stepHist = New-Object 'System.Collections.Generic.Dictionary[string,int]' ([StringComparer]::Ordinal)
    $artifactMethods = New-Object 'System.Collections.Generic.Dictionary[string,int]' ([StringComparer]::Ordinal)
    $parsedLines = 0
    $unparsedLines = 0
    $fetchedLogs = 0

    function Add-Count {
        param($Dict, [string]$Key)
        if (-not $Dict.ContainsKey($Key)) { $Dict[$Key] = 0 }
        $Dict[$Key] = $Dict[$Key] + 1
    }

    foreach ($item in $ordered) {
        Add-Count $workflowHist $item.Conclusion
        $payload = $fetched[$item.Id]
        $jobsObj = $payload.JobsText | ConvertFrom-Json
        $jobArr = @()
        if ($null -ne $jobsObj.jobs) { $jobArr = @($jobsObj.jobs) }
        $checkJobs = @()
        foreach ($job in $jobArr) {
            if ([string]$job.name -ceq $CheckJobName) { $checkJobs += $job }
        }
        $sha8 = ''
        if ($item.Sha.Length -ge 8) { $sha8 = $item.Sha.Substring(0, 8) }
        $prefix = "id=$($item.Id) attempt=$($item.Attempt) created=$($item.Created) branch=$($item.Branch) sha8=$sha8 workflow=$($item.Conclusion)"

        if ($checkJobs.Count -ne 1) {
            $excludedJob++
            $detail = "check_job_count=$($checkJobs.Count)"
            Add-Count $jobConclusionHist $detail
            $classLines.Add("CLASS EXCLUDED reason=job_conclusion detail=$detail $prefix")
            continue
        }
        $check = $checkJobs[0]
        $checkConclusion = [string]$check.conclusion
        if ($checkConclusion -cne 'success') {
            $excludedJob++
            Add-Count $jobConclusionHist $checkConclusion
            $classLines.Add("CLASS EXCLUDED reason=job_conclusion detail=$checkConclusion $prefix")
            continue
        }
        if (-not $payload.LogFetched) { throw "success without log $($item.Id)" }
        $fetchedLogs++
        $logLines = @([regex]::Split($payload.LogText, "`r?`n"))
        if ($logLines.Count -lt 20) { throw "short log $($item.Id) lines=$($logLines.Count)" }

        $steps = @()
        $stepIndex = 0
        $rawStepArr = @()
        if ($null -ne $check.steps) { $rawStepArr = @($check.steps) }
        foreach ($step in $rawStepArr) {
            $started = [string]$step.startedAt
            $completed = [string]$step.completedAt
            if ($started -and $completed) {
                $steps += [pscustomobject]@{
                    Name  = [string]$step.name
                    Index = $stepIndex
                    Start = (ConvertTo-Dto $started)
                    End   = (ConvertTo-Dto $completed)
                }
            }
            $stepIndex++
        }

        $jobStart = ConvertTo-Dto ([string]$check.startedAt)
        $jobEnd = ConvertTo-Dto ([string]$check.completedAt)
        $checkRaw = Get-CheckSeconds $jobStart $jobEnd
        $checkWhole = [int][math]::Round($checkRaw, 0, [MidpointRounding]::AwayFromZero)

        $enriched = New-Object System.Collections.Generic.List[object]
        foreach ($logLine in $logLines) {
            $parsed = Split-LogLine $logLine
            if ($null -eq $parsed) { continue }
            $colKey = $parsed.StepColumn
            if ($colKey.Length -eq 0) { $colKey = '(empty)' }
            Add-Count $stepHist $colKey
            if ($parsed.Parsed) { $parsedLines++ } else { $unparsedLines++ }
            $assigned = Resolve-AssignedStep $parsed $steps
            if ($assigned.Name.Length -eq 0) { continue }
            $enriched.Add([pscustomobject]@{
                    Step    = $assigned.Name
                    Method  = $assigned.Method
                    Message = $parsed.Message
                })
        }

        $runLine = ''
        $runMethod = ''
        $testsSummary = $null
        $testsMethod = ''
        $detSummary = $null
        $detMethod = ''
        $image = ''
        $imageMethod = ''
        $version = ''
        $versionMethod = ''
        $awaitVersion = $false
        foreach ($entry in $enriched) {
            if ($runLine.Length -eq 0 -and $entry.Step -ceq $TestsStepName) {
                if ($entry.Message.TrimStart().StartsWith('##[group]Run ')) {
                    $runLine = $entry.Message.Trim()
                    $runMethod = $entry.Method
                }
            }
            if ($entry.Step -ceq $TestsStepName) {
                $summary = Get-PytestSummary $entry.Message
                if ($null -ne $summary) {
                    $testsSummary = $summary
                    $testsMethod = $entry.Method
                }
            }
            if ($entry.Step -ceq $DetStepName) {
                $summary = Get-PytestSummary $entry.Message
                if ($null -ne $summary) {
                    $detSummary = $summary
                    $detMethod = $entry.Method
                }
            }
            if ($entry.Step -ceq $SetupStepName) {
                $trimmed = $entry.Message.Trim()
                if (-not $awaitVersion -and $trimmed.StartsWith('Image:')) {
                    $image = $trimmed.Substring(6).Trim()
                    $imageMethod = $entry.Method
                    $awaitVersion = $true
                } elseif ($awaitVersion -and $trimmed.StartsWith('Version:')) {
                    $version = $trimmed.Substring(8).Trim()
                    $versionMethod = $entry.Method
                    $awaitVersion = $false
                }
            }
        }

        $hasN4 = $false
        if ($runLine.Length -gt 0) { $hasN4 = Test-HasN4 $runLine }
        if (-not $hasN4) {
            $excludedN4++
            $shown = $runLine
            if ($shown.Length -gt 220) { $shown = $shown.Substring(0, 220) }
            $classLines.Add("CLASS EXCLUDED reason=no_-n_4 run_line=$shown $prefix")
            continue
        }
        if ($null -eq $testsSummary -or $null -eq $detSummary) {
            $excludedSummary++
            $which = @()
            if ($null -eq $testsSummary) { $which += 'tests' }
            if ($null -eq $detSummary) { $which += 'determinism' }
            $classLines.Add("CLASS EXCLUDED reason=summary_line_missing missing=$($which -join '+') $prefix")
            foreach ($entry in $enriched) {
                $summary = Get-PytestSummary $entry.Message
                if ($null -ne $summary) {
                    $classLines.Add("SUMMARY_CANDIDATE id=$($item.Id) step=$($entry.Step) method=$($entry.Method) raw=$($summary.Raw)")
                }
            }
            continue
        }

        foreach ($methodName in @($runMethod, $testsMethod, $detMethod, $imageMethod, $versionMethod)) {
            if ($methodName.Length -gt 0) { Add-Count $artifactMethods $methodName }
        }
        $ratio = [math]::Round($testsSummary.Seconds / $detSummary.Seconds, 2, [MidpointRounding]::AwayFromZero)
        $row = [pscustomobject]@{
            run_id              = $item.Id
            attempt             = $item.Attempt
            created_utc         = $item.Created
            head_branch         = $item.Branch
            head_sha8           = $sha8
            check_s             = $checkWhole
            tests_passed        = $testsSummary.Passed
            tests_skipped       = $testsSummary.Skipped
            tests_deselected    = $testsSummary.Deselected
            tests_xfailed       = $testsSummary.XFailed
            tests_failed        = $testsSummary.Failed
            tests_s             = (Format-Fixed2 $testsSummary.Seconds)
            determinism_passed  = $detSummary.Passed
            determinism_s       = (Format-Fixed2 $detSummary.Seconds)
            ratio               = (Format-Fixed2 $ratio)
            runner_image        = $image
            runner_version      = $version
            check_raw           = (Format-Fixed2 $checkRaw)
            job_started         = [string]$check.startedAt
            job_completed       = [string]$check.completedAt
            tests_raw           = $testsSummary.Raw
            det_raw             = $detSummary.Raw
            run_line            = $runLine
            assign_run          = $runMethod
            assign_tests        = $testsMethod
            assign_det          = $detMethod
            assign_image        = $imageMethod
            assign_version      = $versionMethod
        }
        $rows.Add($row)
        $classLines.Add(("CLASS ELIGIBLE {0} check_s={1} check_raw={2} job_started={3} job_completed={4} tests_s={5} det_s={6} ratio={7} tests_passed={8} tests_skipped={9} tests_deselected={10} tests_xfailed={11} tests_failed={12} det_passed={13} image={14} version={15} assign_run={16} assign_tests={17} assign_det={18} assign_image={19} assign_version={20}" -f `
                    $prefix, $row.check_s, $row.check_raw, $row.job_started, $row.job_completed, $row.tests_s, $row.determinism_s, $row.ratio, `
                    $row.tests_passed, $row.tests_skipped, $row.tests_deselected, $row.tests_xfailed, $row.tests_failed, $row.determinism_passed, `
                    $row.runner_image, $row.runner_version, $row.assign_run, $row.assign_tests, $row.assign_det, $row.assign_image, $row.assign_version))
        $classLines.Add("RAW_TESTS id=$($item.Id) $($row.tests_raw)")
        $classLines.Add("RAW_DET id=$($item.Id) $($row.det_raw)")
        $classLines.Add("RAW_RUN id=$($item.Id) $($row.run_line)")
    }

    $header = @(
        'run_id', 'attempt', 'created_utc', 'head_branch', 'head_sha8', 'check_s',
        'tests_passed', 'tests_skipped', 'tests_deselected', 'tests_xfailed', 'tests_failed',
        'tests_s', 'determinism_passed', 'determinism_s', 'ratio', 'runner_image', 'runner_version'
    )
    $csvLines = New-Object System.Collections.Generic.List[string]
    $csvLines.Add((($header | ForEach-Object { Format-CsvField $_ }) -join ','))
    foreach ($row in $rows) {
        $fields = @(
            $row.run_id, $row.attempt, $row.created_utc, $row.head_branch, $row.head_sha8, $row.check_s,
            $row.tests_passed, $row.tests_skipped, $row.tests_deselected, $row.tests_xfailed, $row.tests_failed,
            $row.tests_s, $row.determinism_passed, $row.determinism_s, $row.ratio, $row.runner_image, $row.runner_version
        )
        $csvLines.Add((($fields | ForEach-Object { Format-CsvField ([string]$_) }) -join ','))
    }
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($CsvPath, (($csvLines -join "`r`n") + "`r`n"), $utf8)

    Write-Output ("RUNS_LISTED={0}" -f $ordered.Count)
    Write-Output ("RUNS_ELIGIBLE={0}" -f $rows.Count)
    Write-Output ("EXCLUDED job_conclusion={0}" -f $excludedJob)
    Write-Output ("EXCLUDED no_-n_4={0}" -f $excludedN4)
    Write-Output ("EXCLUDED summary_line_missing={0}" -f $excludedSummary)
    Write-Output ("FETCHED_LOGS={0}" -f $fetchedLogs)
    Write-Output ("LOG_LINES_PARSED={0}" -f $parsedLines)
    Write-Output ("LOG_LINES_UNPARSED={0}" -f $unparsedLines)
    $histBits = @()
    foreach ($key in $stepHist.Keys) { $histBits += "$key=$($stepHist[$key])" }
    Write-Output ("STEP_COLUMNS {0}" -f ($histBits -join ' '))
    $methodBits = @()
    foreach ($key in $artifactMethods.Keys) { $methodBits += "$key=$($artifactMethods[$key])" }
    Write-Output ("ARTIFACT_METHODS {0}" -f ($methodBits -join ' '))
    $wfBits = @()
    foreach ($key in $workflowHist.Keys) { $wfBits += "$key=$($workflowHist[$key])" }
    Write-Output ("WORKFLOW_CONCLUSIONS {0}" -f ($wfBits -join ' '))
    $jcBits = @()
    foreach ($key in $jobConclusionHist.Keys) { $jcBits += "$key=$($jobConclusionHist[$key])" }
    Write-Output ("JOB_CONCLUSION_DETAILS {0}" -f ($jcBits -join ' '))
    $columnArtifacts = 0
    if ($artifactMethods.ContainsKey('column')) { $columnArtifacts = $artifactMethods['column'] }
    $unknownOnly = $true
    foreach ($key in $stepHist.Keys) {
        if ($key -cne 'UNKNOWN STEP') { $unknownOnly = $false }
    }
    Write-Output 'STEP_ASSIGNMENT: if the log step-name column equals a step name from the jobs JSON, that column assigns the line. If the column does not name a step, the line is assigned by timestamp: it is inside a step when its timestamp is >= startedAt and < completedAt plus one second. When that window hits two steps, a line that begins with ##[group]Run is assigned to the later-started step and any other line to the earlier-started step.'
    foreach ($line in $classLines) { Write-Output $line }
    Write-Output 'EXCLUSION_INDEX_BEGIN'
    foreach ($line in $classLines) {
        if ($line.StartsWith('CLASS EXCLUDED')) { Write-Output $line }
    }
    Write-Output 'EXCLUSION_INDEX_END'
    Write-Output ("DATA_ROWS={0}" -f $rows.Count)
    Write-Output 'CENSUS_DONE'
} catch {
    Write-Output ("INNER_ERROR line=" + $_.InvocationInfo.ScriptLineNumber + " " + $_.Exception.Message)
    Write-Output $_.ScriptStackTrace
    throw
} finally {
    for ($liveIndex = 0; $liveIndex -lt $live.Count; $liveIndex++) {
        $liveItem = $live[$liveIndex]
        if (-not $liveItem.Disposed) {
            try { [void]$liveItem.PS.Stop() } catch { }
            try { $liveItem.PS.Dispose() } catch { }
            $liveItem.Disposed = $true
        }
    }
    if ($null -ne $pool) {
        try { $pool.Close() } catch { }
        try { $pool.Dispose() } catch { }
    }
}
