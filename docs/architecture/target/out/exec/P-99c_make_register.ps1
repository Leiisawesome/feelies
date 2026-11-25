$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Repo = 'C:\Users\cheng.lei\OneDrive\Documents\GitHub\feelies'
$Ref = '140b2a3bbc20302897596dd4b07269ba632d5191'
$OutDir = Join-Path $env:USERPROFILE 'feelies-probes\P-99c'
if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir | Out-Null
}

$Utf8 = New-Object System.Text.UTF8Encoding $false
$IdRe = [regex]::new('\bF-[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)?\b')
$ClosedRe = [regex]::new('(?i)closed by|closed:|closed\.|is closed|fixed in|fixed by|resolved|superseded|accepted\b')
$LiveRe = [regex]::new('\blive\b')
$E14Re = [regex]::new('\b14E\b')
$UnscheduledRe = [regex]::new('\bunscheduled\b')
$ScheduledRe = [regex]::new('\bscheduled\b')
$DeferredRe = [regex]::new('\bdeferred\b')
$OpenWordRe = [regex]::new('(?i)\bopen\b|unscheduled|carried|not closed|backlog|operator decision|risk-policy')
$ClosedMultiRe = [regex]::new('(?i)not closed|\bopen\b|carried')
$HandoffIds = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
foreach ($hid in @(
    'F-T10-2', 'F-P52-4', 'F-P52-5', 'F-P52-1', 'F-P59-2',
    'F-T13-1', 'F-T15p-1', 'F-T15p-2', 'F-T15p-3', 'F-P95-1',
    'F-P95-2', 'F-P95-3', 'F-P95-4', 'F-P95-5', 'F-P95-6',
    'F-P95-7', 'F-P95-8', 'F-P95m-1', 'F-P96-1', 'F-P96-2',
    'F-P96-3', 'F-P99a-1', 'F-P99b-1', 'F-P99b-2', 'F-P99b-3',
    'F-P99b-4'
)) {
    [void]$HandoffIds.Add($hid)
}

$ClosedIds = @(
    'F-P23e-6', 'F-P23f-1', 'F-P23f-7', 'F-P23f-8', 'F-P29b-1', 'F-P29b-4',
    'F-P30-18', 'F-P30-19', 'F-P30-27', 'F-P49-2', 'F-P50-1', 'F-P50-3',
    'F-P52-3', 'F-P39-2', 'F-P50-2', 'F-P95-1', 'F-P95-2', 'F-P95-5',
    'F-P96-1', 'F-P96-2', 'F-R2', 'F-R3'
)
$CarriedPaperLiveIds = @(
    'F-P13b', 'F-P22a2h', 'F-P23a2-2', 'F-P23a2-9', 'F-P23b2-16', 'F-P23b2-17',
    'F-P23b3-2', 'F-P23c-c', 'F-P23c-i', 'F-P23e-7', 'F-P23f-2', 'F-P24-10',
    'F-P24-11', 'F-S1a', 'F-S1b', 'F-T14-1', 'F-T1a', 'F-T1c'
)
$Carried14EIds = @(
    'F-P13', 'F-P23c-f', 'F-P23c-g', 'F-P23c-l', 'F-P23c-m', 'F-P23e-8',
    'F-P23e-9', 'F-P23f-9', 'F-P99a-1', 'F-P99b-2'
)
$OperatorPolicyIds = @(
    'F-P23b2-18', 'F-P23g-13', 'F-P23g-2', 'F-P23g-9', 'F-T2-10', 'F-T2-7'
)
$BacklogIds = @(
    'F-D1-3', 'F-P22a2f', 'F-P23b-c', 'F-P23b3-4', 'F-P23d-f', 'F-P23d-g',
    'F-P23e-4', 'F-P23g-14', 'F-P23g2-12', 'F-P39-1', 'F-P51-1', 'F-P52-1',
    'F-P52-4', 'F-P52-5', 'F-P59-2', 'F-P95-3', 'F-P95m-1', 'F-P96-3',
    'F-P99b-1', 'F-P99b-4', 'F-T10-2', 'F-T13-1', 'F-T15p-1', 'F-T15p-2',
    'F-T15p-3', 'F-T6b-1'
)
$AcceptedIds = @(
    'F-D1-1', 'F-P13c', 'F-P23c-a', 'F-P23c-b', 'F-P23c-d', 'F-P23c-h',
    'F-P23c-j', 'F-P23e-2', 'F-P23e-5', 'F-P23f-3', 'F-P23f-4', 'F-P23f-5',
    'F-P23f-6', 'F-P23g-15', 'F-P23g-16', 'F-P23g-18', 'F-P23g-20', 'F-P23g-8',
    'F-P99b-3', 'F-T10-1'
)
$NoteById = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([StringComparer]::Ordinal)
$NoteById['F-P23b-c'] = 'check whether D-191 closed it.'
$NoteById['F-P96-3'] = 'close at P-99c2 after a repo check.'
$NoteById['F-P99b-4'] = 'close at P-99c2 after a repo check.'
$NoteById['F-T15p-1'] = 'campaign 14E setup checklist.'
$NoteById['F-T2-7'] = 'close when PR #249 merges to main.'
$NoteById['F-T2-10'] = 'close when PR #249 merges to main.'
$DispLists = New-Object 'System.Collections.Generic.Dictionary[string,string[]]' ([StringComparer]::Ordinal)
$DispLists['CLOSED'] = [string[]]$ClosedIds
$DispLists['CARRIED-PAPER-LIVE'] = [string[]]$CarriedPaperLiveIds
$DispLists['CARRIED-14E'] = [string[]]$Carried14EIds
$DispLists['OPERATOR-POLICY'] = [string[]]$OperatorPolicyIds
$DispLists['BACKLOG'] = [string[]]$BacklogIds
$DispLists['ACCEPTED'] = [string[]]$AcceptedIds
$DispOf = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([StringComparer]::Ordinal)
foreach ($dispName in @($DispLists.Keys)) {
    foreach ($dispId in $DispLists[$dispName]) {
        if ($DispOf.ContainsKey($dispId)) { throw "id in two lists: $dispId" }
        $DispOf[$dispId] = $dispName
    }
}
if ($ClosedIds.Count -ne 22) { throw "CLOSED list $($ClosedIds.Count)" }
if ($CarriedPaperLiveIds.Count -ne 18) { throw "CARRIED-PAPER-LIVE list $($CarriedPaperLiveIds.Count)" }
if ($Carried14EIds.Count -ne 10) { throw "CARRIED-14E list $($Carried14EIds.Count)" }
if ($OperatorPolicyIds.Count -ne 6) { throw "OPERATOR-POLICY list $($OperatorPolicyIds.Count)" }
if ($BacklogIds.Count -ne 26) { throw "BACKLOG list $($BacklogIds.Count)" }
if ($AcceptedIds.Count -ne 20) { throw "ACCEPTED list $($AcceptedIds.Count)" }
foreach ($noteId in $NoteById.Keys) {
    if (-not $DispOf.ContainsKey($noteId)) { throw "note id not in a disposition list: $noteId" }
}
$ClassOf = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([StringComparer]::Ordinal)
$DispositionOf = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([StringComparer]::Ordinal)
$DispCounts = New-Object 'System.Collections.Generic.Dictionary[string,int]' ([StringComparer]::Ordinal)
foreach ($dispName in @('CARRIED-14E', 'CARRIED-PAPER-LIVE', 'OPERATOR-POLICY', 'BACKLOG', 'ACCEPTED', 'CLOSED', 'RECORD')) {
    $DispCounts[$dispName] = 0
}

function Split-GitText([string]$text) {
    if ($text.Length -gt 0 -and [int]$text[0] -eq 0xFEFF) {
        $text = $text.Substring(1)
    }
    $parts = $text.Split([string[]]@("`n"), [System.StringSplitOptions]::None)
    $n = $parts.Length
    if ($n -gt 0 -and $parts[$n - 1].Length -eq 0) {
        $n = $n - 1
    }
    $lines = New-Object string[] $n
    for ($i = 0; $i -lt $n; $i++) {
        $lines[$i] = $parts[$i].TrimEnd([char]13)
    }
    return ,$lines
}

function Read-GitBlob([string]$rel) {
    $git = (Get-Command git -ErrorAction Stop).Source
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $git
    $psi.WorkingDirectory = $Repo
    $spec = '{0}:{1}' -f $Ref, $rel
    $psi.Arguments = "-C `"$Repo`" --no-pager show $spec"
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = $Utf8
    $psi.StandardErrorEncoding = $Utf8
    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    [void]$p.Start()
    $outTask = $p.StandardOutput.ReadToEndAsync()
    $errTask = $p.StandardError.ReadToEndAsync()
    [void]$p.WaitForExit()
    $stdout = $outTask.GetAwaiter().GetResult()
    $stderr = $errTask.GetAwaiter().GetResult()
    if ($p.ExitCode -ne 0) {
        throw "git show failed ($($p.ExitCode)) for ${spec}: $stderr"
    }
    return Split-GitText $stdout
}

function New-Rec {
    $obj = [pscustomobject]@{
        Mentions    = 0
        S1          = $false
        S2          = $false
        S3          = $false
        First       = ''
        Last        = ''
        LastText    = ''
        TableRows   = (New-Object 'System.Collections.Generic.List[string]')
        ClosedLine  = ''
        ClosedText  = ''
        High        = $false
        Paper       = $false
        Live        = $false
        E14         = $false
        Campaign15  = $false
        NextRung    = $false
        Unscheduled = $false
        Scheduled   = $false
        Deferred    = $false
        OpenWord    = $false
    }
    return ,$obj
}

function Get-Clip([string]$s) {
    if ($null -eq $s) { return '' }
    if ($s.Length -le 120) { return $s }
    return $s.Substring(0, 120)
}

function Get-Head([string]$s, [int]$n) {
    if ($null -eq $s) { return '' }
    if ($s.Length -le $n) { return $s }
    return $s.Substring(0, $n)
}

function Format-CsvField([string]$s) {
    if ($null -eq $s) { $s = '' }
    return '"' + $s.Replace('"', '""') + '"'
}

$s1 = Read-GitBlob 'docs/architecture/target/position_engine/decisions.md'
$s2 = Read-GitBlob 'docs/architecture/target/out/phase14_position_engine.md'
$s3 = Read-GitBlob 'docs/architecture/target/out/exec/LEDGER.md'

if ($s1.Length -lt 2083 -or -not $s1[2082].StartsWith('| F-P13 |')) {
    throw "S1 line 2083 did not start with '| F-P13 |'"
}
$s3Start = -1
for ($i = 0; $i -lt $s3.Length; $i++) {
    if ($s3[$i].StartsWith('## P-00 ')) {
        $s3Start = $i
        break
    }
}
if ($s3Start -lt 0) {
    throw 'S3 line starting with "## P-00 " was not found'
}

$recs = New-Object 'System.Collections.Generic.Dictionary[string,object]' ([StringComparer]::Ordinal)

function Add-Scan([string]$label, [string[]]$lines, [int]$startAt) {
    for ($i = $startAt; $i -lt $lines.Length; $i++) {
        $text = $lines[$i]
        if ($text.IndexOf('F-') -lt 0) { continue }
        $ms = $IdRe.Matches($text)
        if ($ms.Count -eq 0) { continue }
        $lineNo = $i + 1
        $loc = '{0}:{1}' -f $label, $lineNo
        $isClosed = $ClosedRe.IsMatch($text)
        $isHigh = $text.Contains('HIGH')
        $dPaper = $text.Contains('paper campaign')
        $dLive = $LiveRe.IsMatch($text)
        $d14 = $E14Re.IsMatch($text)
        $d15 = $text.Contains('campaign 15')
        $dNext = $text.Contains('next rung')
        $dUns = $UnscheduledRe.IsMatch($text)
        $dSch = $ScheduledRe.IsMatch($text)
        $dDef = $DeferredRe.IsMatch($text)
        foreach ($m in $ms) {
            $id = $m.Value
            if (-not $recs.ContainsKey($id)) {
                $recs[$id] = (New-Rec)
            }
            $r = $recs[$id]
            $r.Mentions = $r.Mentions + 1
            if ($label -eq 'S1') { $r.S1 = $true }
            elseif ($label -eq 'S2') { $r.S2 = $true }
            else { $r.S3 = $true }
            if (-not $r.First) { $r.First = $loc }
            $r.Last = $loc
            $r.LastText = $text
            if ($isClosed) {
                $r.ClosedLine = $loc
                $r.ClosedText = $text
            }
            if ($isHigh) { $r.High = $true }
            if ($dPaper) { $r.Paper = $true }
            if ($dLive) { $r.Live = $true }
            if ($d14) { $r.E14 = $true }
            if ($d15) { $r.Campaign15 = $true }
            if ($dNext) { $r.NextRung = $true }
            if ($dUns) { $r.Unscheduled = $true }
            if ($dSch) { $r.Scheduled = $true }
            if ($dDef) { $r.Deferred = $true }
            if ($OpenWordRe.IsMatch($text)) { $r.OpenWord = $true }
            if ($label -eq 'S1' -and $text.StartsWith("| $id |")) {
                $ln = [string]$lineNo
                if (-not $r.TableRows.Contains($ln)) {
                    [void]$r.TableRows.Add($ln)
                }
            }
        }
    }
}

Add-Scan 'S1' $s1 0
Add-Scan 'S2' $s2 0
Add-Scan 'S3' $s3 $s3Start

$ids = New-Object string[] $recs.Count
$recs.Keys.CopyTo($ids, 0)
[Array]::Sort($ids, [StringComparer]::Ordinal)

$csv = New-Object System.Text.StringBuilder
$closedN = 0
$openN = 0
$prefixCounts = New-Object 'System.Collections.Generic.Dictionary[string,int]' ([StringComparer]::Ordinal)
$csv2 = New-Object System.Text.StringBuilder
$csv3 = New-Object System.Text.StringBuilder
$classOrder = @('CHECK', 'CLOSED', 'EXCEPTION', 'RECORD')
$classCounts = New-Object 'System.Collections.Generic.Dictionary[string,int]' ([StringComparer]::Ordinal)
foreach ($cn in $classOrder) {
    $classCounts[$cn] = 0
}
$excLines = New-Object System.Text.StringBuilder
$chkLines = New-Object System.Text.StringBuilder
$recordIds = New-Object 'System.Collections.Generic.List[string]'

foreach ($id in $ids) {
    $r = $recs[$id]
    $fileParts = New-Object System.Collections.Generic.List[string]
    if ($r.S1) { [void]$fileParts.Add('S1') }
    if ($r.S2) { [void]$fileParts.Add('S2') }
    if ($r.S3) { [void]$fileParts.Add('S3') }
    $files = $fileParts -join '/'
    $destParts = New-Object System.Collections.Generic.List[string]
    if ($r.Paper) { [void]$destParts.Add('paper campaign') }
    if ($r.Live) { [void]$destParts.Add('live') }
    if ($r.E14) { [void]$destParts.Add('14E') }
    if ($r.Campaign15) { [void]$destParts.Add('campaign 15') }
    if ($r.NextRung) { [void]$destParts.Add('next rung') }
    if ($r.Unscheduled) { [void]$destParts.Add('unscheduled') }
    if ($r.Scheduled) { [void]$destParts.Add('scheduled') }
    if ($r.Deferred) { [void]$destParts.Add('deferred') }
    $dest = $destParts -join ','
    if ($r.ClosedLine) {
        $auto = 'CLOSED'
        $closedN = $closedN + 1
    } else {
        $auto = 'OPEN'
        $openN = $openN + 1
    }
    $high = 'no'
    if ($r.High) { $high = 'yes' }
    $table = $r.TableRows -join ';'
    $openWord = 'no'
    if ($r.OpenWord) { $openWord = 'yes' }
    $closedMulti = 'no'
    if ($r.ClosedLine.Length -gt 0) {
        $otherId = $false
        foreach ($cm in $IdRe.Matches($r.ClosedText)) {
            if (-not [string]::Equals($cm.Value, $id, [StringComparison]::Ordinal)) {
                $otherId = $true
                break
            }
        }
        if ($otherId -or $ClosedMultiRe.IsMatch($r.ClosedText)) {
            $closedMulti = 'yes'
        }
    }
    $handoff = 'no'
    if ($HandoffIds.Contains($id)) { $handoff = 'yes' }
    if ($auto -eq 'CLOSED' -and $closedMulti -eq 'yes') {
        $class = 'CHECK'
    } elseif ($auto -eq 'CLOSED' -and $closedMulti -eq 'no') {
        $class = 'CLOSED'
    } elseif ($auto -eq 'OPEN' -and ($high -eq 'yes' -or $table.Length -gt 0 -or $dest.Length -gt 0 -or $openWord -eq 'yes' -or $handoff -eq 'yes')) {
        $class = 'EXCEPTION'
    } else {
        $class = 'RECORD'
    }
    $classCounts[$class] = [int]$classCounts[$class] + 1
    $ClassOf[$id] = $class
    if ($class -eq 'CLOSED' -or $class -eq 'RECORD') {
        $disposition = $class
    } elseif ($class -eq 'CHECK' -or $class -eq 'EXCEPTION') {
        if (-not $DispOf.ContainsKey($id)) {
            throw "CHECK or EXCEPTION id in no list: $id"
        }
        $disposition = $DispOf[$id]
    } else {
        throw "unknown class for ${id}: $class"
    }
    $DispositionOf[$id] = $disposition
    $DispCounts[$disposition] = [int]$DispCounts[$disposition] + 1
    $note = ''
    if ($NoteById.ContainsKey($id)) {
        $note = [string]$NoteById[$id]
    }
    $fields = @(
        (Format-CsvField $id),
        (Format-CsvField ([string]$r.Mentions)),
        (Format-CsvField $files),
        (Format-CsvField $r.First),
        (Format-CsvField $r.Last),
        (Format-CsvField $table),
        (Format-CsvField $r.ClosedLine),
        (Format-CsvField (Get-Clip $r.ClosedText)),
        (Format-CsvField $high),
        (Format-CsvField $dest),
        (Format-CsvField $auto),
        (Format-CsvField (Get-Clip $r.LastText))
    )
    [void]$csv.Append(($fields -join ','))
    [void]$csv.Append("`n")
    $fields2 = New-Object 'System.Collections.Generic.List[string]'
    foreach ($f in $fields) { [void]$fields2.Add($f) }
    [void]$fields2.Add((Format-CsvField $openWord))
    [void]$fields2.Add((Format-CsvField $closedMulti))
    [void]$fields2.Add((Format-CsvField $handoff))
    [void]$fields2.Add((Format-CsvField $class))
    [void]$csv2.Append(($fields2 -join ','))
    [void]$csv2.Append("`n")
    $fields3 = New-Object 'System.Collections.Generic.List[string]'
    foreach ($f in $fields2) { [void]$fields3.Add($f) }
    [void]$fields3.Add((Format-CsvField $disposition))
    [void]$fields3.Add((Format-CsvField $note))
    [void]$csv3.Append(($fields3 -join ','))
    [void]$csv3.Append("`n")
    if ($class -eq 'EXCEPTION') {
        [void]$excLines.Append($id)
        [void]$excLines.Append(' | ')
        [void]$excLines.Append($high)
        [void]$excLines.Append(' | ')
        [void]$excLines.Append($table)
        [void]$excLines.Append(' | ')
        [void]$excLines.Append($dest)
        [void]$excLines.Append(' | ')
        [void]$excLines.Append($openWord)
        [void]$excLines.Append(' | ')
        [void]$excLines.Append($handoff)
        [void]$excLines.Append(' | ')
        [void]$excLines.Append($r.First)
        [void]$excLines.Append(' | ')
        [void]$excLines.Append($r.Last)
        [void]$excLines.Append(' | ')
        [void]$excLines.Append((Get-Head $r.LastText 140))
        [void]$excLines.Append("`n")
    } elseif ($class -eq 'CHECK') {
        [void]$chkLines.Append($id)
        [void]$chkLines.Append(' | ')
        [void]$chkLines.Append($r.ClosedLine)
        [void]$chkLines.Append(' | ')
        [void]$chkLines.Append((Get-Head $r.ClosedText 140))
        [void]$chkLines.Append("`n")
    } elseif ($class -eq 'RECORD') {
        [void]$recordIds.Add($id)
    }

    $rest = $id.Substring(2)
    $cut = $rest.Length
    for ($k = 0; $k -lt $rest.Length; $k++) {
        $ch = $rest[$k]
        if ($ch -eq '-' -or ($ch -ge '0' -and $ch -le '9')) {
            $cut = $k
            break
        }
    }
    $pref = $rest.Substring(0, $cut)
    if (-not $prefixCounts.ContainsKey($pref)) {
        $prefixCounts[$pref] = 0
    }
    $prefixCounts[$pref] = $prefixCounts[$pref] + 1
}

$sum = New-Object System.Text.StringBuilder
[void]$sum.Append('total_ids=')
[void]$sum.Append($ids.Length)
[void]$sum.Append("`n")
[void]$sum.Append('auto.CLOSED=')
[void]$sum.Append($closedN)
[void]$sum.Append("`n")
[void]$sum.Append('auto.OPEN=')
[void]$sum.Append($openN)
[void]$sum.Append("`n")
$pkeys = New-Object string[] $prefixCounts.Count
$prefixCounts.Keys.CopyTo($pkeys, 0)
[Array]::Sort($pkeys, [StringComparer]::Ordinal)
foreach ($pk in $pkeys) {
    [void]$sum.Append('prefix.')
    [void]$sum.Append($pk)
    [void]$sum.Append('=')
    [void]$sum.Append($prefixCounts[$pk])
    [void]$sum.Append("`n")
}

function Escape-Pipe([string]$s) {
    if ($null -eq $s) { return '' }
    return $s.Replace('|', '\|')
}
foreach ($dispId in $DispOf.Keys) {
    if (-not $ClassOf.ContainsKey($dispId)) {
        throw "listed id is not in the register: $dispId"
    }
    $listedClass = $ClassOf[$dispId]
    if ($listedClass -ne 'CHECK' -and $listedClass -ne 'EXCEPTION') {
        throw "listed id is not CHECK or EXCEPTION: $dispId ($listedClass)"
    }
}
$expectedN = New-Object 'System.Collections.Generic.Dictionary[string,int]' ([StringComparer]::Ordinal)
$expectedN['CLOSED'] = 56
$expectedN['CARRIED-14E'] = 10
$expectedN['CARRIED-PAPER-LIVE'] = 18
$expectedN['OPERATOR-POLICY'] = 6
$expectedN['BACKLOG'] = 26
$expectedN['ACCEPTED'] = 20
$expectedN['RECORD'] = 161
$sectionOrder = @('CARRIED-14E', 'CARRIED-PAPER-LIVE', 'OPERATOR-POLICY', 'BACKLOG', 'ACCEPTED', 'CLOSED', 'RECORD')
$sumDisp = 0
foreach ($dispName in $sectionOrder) {
    $got = [int]$DispCounts[$dispName]
    $want = [int]$expectedN[$dispName]
    if ($got -ne $want) {
        throw "count $dispName is $got, expected $want"
    }
    $sumDisp = $sumDisp + $got
}
if ($sumDisp -ne 297 -or $ids.Length -ne 297 -or $DispositionOf.Count -ne 297) {
    throw "total ids=$($ids.Length) dispositions=$($DispositionOf.Count) sum=$sumDisp expected 297"
}
$byDisp = New-Object 'System.Collections.Generic.Dictionary[string,object]' ([StringComparer]::Ordinal)
foreach ($dispName in $sectionOrder) {
    $byDisp[$dispName] = New-Object 'System.Collections.Generic.List[string]'
}
foreach ($id in $ids) {
    [void]$byDisp[$DispositionOf[$id]].Add($id)
}
$md = New-Object System.Text.StringBuilder
[void]$md.Append("# P-99c findings register (phase 14)`n`n")
[void]$md.Append("Generated by P-99c_make_register.ps1 at 140b2a3b (D-255). Sources: decisions.md, the plan, LEDGER.md from '## P-00'. Not hand-edited.`n`n")
[void]$md.Append("| disposition | n |`n")
[void]$md.Append("|---|---|`n")
foreach ($dispName in $sectionOrder) {
    [void]$md.Append("| $dispName | $($DispCounts[$dispName]) |`n")
}
[void]$md.Append("`n")
foreach ($dispName in $sectionOrder) {
    [void]$md.Append("## $dispName`n`n")
    if ($dispName -eq 'RECORD') {
        $recSep = ''
        foreach ($rid in $byDisp[$dispName]) {
            [void]$md.Append($recSep)
            [void]$md.Append($rid)
            $recSep = ','
        }
        [void]$md.Append("`n")
    } elseif ($dispName -eq 'CLOSED') {
        [void]$md.Append("| id | closed_line |`n")
        [void]$md.Append("|---|---|`n")
        foreach ($rid in $byDisp[$dispName]) {
            $cl = [string]$recs[$rid].ClosedLine
            [void]$md.Append("| $rid | $cl |`n")
        }
    } else {
        [void]$md.Append("| id | note | first | last | last_text |`n")
        [void]$md.Append("|---|---|---|---|---|`n")
        foreach ($rid in $byDisp[$dispName]) {
            $rr = $recs[$rid]
            $rn = ''
            if ($NoteById.ContainsKey($rid)) { $rn = [string]$NoteById[$rid] }
            $lt = Escape-Pipe (Get-Head $rr.LastText 140)
            [void]$md.Append("| $rid | $rn | $($rr.First) | $($rr.Last) | $lt |`n")
        }
    }
    [void]$md.Append("`n")
}
foreach ($dispName in $sectionOrder) {
    Write-Output ("{0}={1}" -f $dispName, [int]$DispCounts[$dispName])
}
[System.IO.File]::WriteAllText((Join-Path $OutDir 'register.csv'), $csv.ToString(), $Utf8)
[System.IO.File]::WriteAllText((Join-Path $OutDir 'summary.txt'), $sum.ToString(), $Utf8)
$sum2 = New-Object System.Text.StringBuilder
[void]$sum2.Append('total_ids=')
[void]$sum2.Append($ids.Length)
[void]$sum2.Append("`n")
foreach ($cn in $classOrder) {
    [void]$sum2.Append('class.')
    [void]$sum2.Append($cn)
    [void]$sum2.Append('=')
    [void]$sum2.Append($classCounts[$cn])
    [void]$sum2.Append("`n")
}
$recordText = ($recordIds -join ',') + "`n"
[System.IO.File]::WriteAllText((Join-Path $OutDir 'register2.csv'), $csv2.ToString(), $Utf8)
[System.IO.File]::WriteAllText((Join-Path $OutDir 'summary2.txt'), $sum2.ToString(), $Utf8)
[System.IO.File]::WriteAllText((Join-Path $OutDir 'exceptions.txt'), $excLines.ToString(), $Utf8)
[System.IO.File]::WriteAllText((Join-Path $OutDir 'check.txt'), $chkLines.ToString(), $Utf8)
[System.IO.File]::WriteAllText((Join-Path $OutDir 'record.txt'), $recordText, $Utf8)
[System.IO.File]::WriteAllText((Join-Path $OutDir 'P-99c_findings_register.csv'), $csv3.ToString(), $Utf8)
[System.IO.File]::WriteAllText((Join-Path $OutDir 'P-99c_findings_register.md'), $md.ToString(), $Utf8)

