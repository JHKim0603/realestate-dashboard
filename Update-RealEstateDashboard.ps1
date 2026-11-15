#Requires -Version 7
# 부동산 시장 Dashboard(서울·부산 아파트) 생성 스크립트.
#
# 하는 일: 한국부동산원 R-ONE(주간·월간 아파트 통계)과 한국은행 ECOS(금리·미분양·인허가·주택가격전망)를 받아
# data-history.json 에 쌓고, template.html 의 __DATA_JSON__ 자리에 넣어 dashboard.html 을 만든다.
# 화면의 계산(주간 변동률, 연속 상승·하락 주, 누적 변동, 구별 표)은 template.html 의 스크립트가 한다.
#
# 인증키가 필요 없다. R-ONE 은 키가 없으면 한 번에 5행만 주고 페이지(pIndex)도 무시하므로, 지역(CLS_ID)과
# 기간(START_WRTTIME~END_WRTTIME)을 좁혀 5행씩 이어 받는다. 그래서 처음 실행(3년치·1년치 채우기)은 1,500번쯤
# 부르고, 그 뒤에는 이미 받은 값을 두고 최근 몇 주·몇 달만 다시 받는다(150번쯤).
# ECOS 는 공개 sample 키가 한 번에 10행을 준다(work-dashboard 와 같은 방식).
#
# R-ONE 서버(www.reb.or.kr)는 중간 인증서를 보내지 않는다. 워크플로가 실행 전에 저장소의 certs/ 에 둔 중간 인증서
# (TuringSign RSA Secure CA 3, 발급처 공개 주소에서 받은 것)를 러너의 신뢰 목록에 더한다. 검증을 끄지 않는다.
param([string]$Out = "dashboard.html")

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$config = Get-Content -Raw -Encoding utf8 (Join-Path $root "config.json") | ConvertFrom-Json
$historyPath = Join-Path $root "data-history.json"

$tz = try { [TimeZoneInfo]::FindSystemTimeZoneById("Asia/Seoul") } catch { [TimeZoneInfo]::FindSystemTimeZoneById("Korea Standard Time") }
$nowKst = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $tz)
$ua = @{ "User-Agent" = "realestate-dashboard/1.0 (+https://github.com/JHKim0603/realestate-dashboard)" }

# ---- 쌓아 둔 값 -------------------------------------------------------------------------------
function Read-History {
    $h = if (Test-Path $historyPath) { Get-Content -Raw -Encoding utf8 $historyPath | ConvertFrom-Json -AsHashtable } else { @{} }
    foreach ($k in "weekly", "weekDates", "monthly", "ecos") { if (-not $h.ContainsKey($k) -or $null -eq $h[$k]) { $h[$k] = @{} } }
    $h
}
# 계열마다 한 줄로 쓴다. 날마다 바뀌는 건 몇 줄뿐이라 커밋 차이가 읽힌다.
function Write-History($h) {
    $sb = [System.Text.StringBuilder]::new()
    [void]$sb.Append("{`n")
    $sections = @("weekDates", "weekly", "monthly", "ecos")
    for ($i = 0; $i -lt $sections.Count; $i++) {
        $sec = $sections[$i]; $m = $h[$sec]
        [void]$sb.Append("  `"$sec`": {")
        $keys = @($m.Keys | Sort-Object)
        if ($sec -eq "weekDates") {
            $o = [ordered]@{}; foreach ($k in $keys) { $o[$k] = $m[$k] }
            [void]$sb.Append((ConvertTo-Json $o -Compress).TrimStart("{").TrimEnd("}"))
        } else {
            for ($j = 0; $j -lt $keys.Count; $j++) {
                $inner = $m[$keys[$j]]; $o = [ordered]@{}
                foreach ($p in @($inner.Keys | Sort-Object)) { $o[$p] = $inner[$p] }
                [void]$sb.Append("`n    " + (ConvertTo-Json $keys[$j]) + ": " + (ConvertTo-Json $o -Compress) + $(if ($j -lt $keys.Count - 1) { "," } else { "" }))
            }
            if ($keys.Count) { [void]$sb.Append("`n  ") }
        }
        [void]$sb.Append("}" + $(if ($i -lt $sections.Count - 1) { "," } else { "" }) + "`n")
    }
    [void]$sb.Append("}`n")
    [IO.File]::WriteAllText($historyPath, $sb.ToString(), [Text.UTF8Encoding]::new($false))
}

# ---- R-ONE -----------------------------------------------------------------------------------
$roneBase = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
$script:roneCalls = 0
function Invoke-Rone([System.Collections.IDictionary]$q) {
    $parts = @("Type=json", "pSize=5") + @($q.GetEnumerator() | ForEach-Object { "$($_.Key)=$([uri]::EscapeDataString([string]$_.Value))" })
    $uri = "${roneBase}?" + ($parts -join "&")
    for ($try = 1; $try -le 3; $try++) {
        try {
            $script:roneCalls++
            $r = Invoke-RestMethod -Uri $uri -Headers $ua -TimeoutSec 30
            if ($r.RESULT) {
                if ($r.RESULT.CODE -eq "INFO-200") { return @() }   # 해당 기간 자료 없음
                throw "R-ONE $($r.RESULT.CODE) $($r.RESULT.MESSAGE)"
            }
            if (-not $r.SttsApiTblData) { throw "R-ONE 응답 형식이 예상과 다릅니다" }
            return @($r.SttsApiTblData[1].row)
        } catch {
            if ($try -eq 3) { throw }
            Start-Sleep -Seconds (2 * $try)
        }
    }
}

function Get-NextPeriod([string]$id, [string]$cycle) {
    $y = [int]$id.Substring(0, 4); $n = [int]$id.Substring(4)
    $max = if ($cycle -eq "WK") { 53 } else { 12 }
    if ($n -ge $max) { return ("{0}{1:D2}" -f ($y + 1), 1) }
    "{0}{1:D2}" -f $y, ($n + 1)
}

# 기간 범위를 5행씩 이어 받는다. 행은 기간 순으로 온다. 없는 기간 번호(2025년 53주처럼)는 범위 비교라 상관없다.
function Get-RoneRange([string]$table, [string]$cycle, $cls, [string]$from, [string]$to, $itm = $null) {
    $rows = [System.Collections.Generic.List[object]]::new()
    $start = $from
    for ($guard = 0; $guard -lt 300; $guard++) {
        $q = [ordered]@{ STATBL_ID = $table; DTACYCLE_CD = $cycle; CLS_ID = $cls; START_WRTTIME = $start; END_WRTTIME = $to }
        if ($itm) { $q.ITM_ID = $itm }
        $page = @(Invoke-Rone $q)
        if ($page.Count -eq 0) { break }
        foreach ($p in $page) { $rows.Add($p) }
        $last = [string]$page[-1].WRTTIME_IDTFR_ID
        if ($page.Count -lt 5 -or $last -ge $to) { break }
        $start = Get-NextPeriod $last $cycle
    }
    $rows
}

# ISO 주(R-ONE 주간 통계의 기간 번호가 조사일 월요일의 ISO 연도·주차와 같다: 2026-11-09 → 202646).
function Get-WeekId([DateTime]$d) { "{0}{1:D2}" -f [System.Globalization.ISOWeek]::GetYear($d), [System.Globalization.ISOWeek]::GetWeekOfYear($d) }

$status = [ordered]@{}   # 자료별 상태(화면 아래 '자료 상태'에 보인다)
$hist = Read-History

Write-Host "R-ONE 주간: 최신 주 찾기..."
$wk = $config.rone.weekly
$probe = Get-RoneRange $wk.sale.id "WK" 50001 (Get-WeekId $nowKst.AddDays(-28)) (Get-WeekId $nowKst.AddDays(7))
if (-not $probe.Count) { throw "R-ONE 주간 매매가격지수(전국)를 받지 못했습니다" }
$latestWeek = [string]$probe[-1].WRTTIME_IDTFR_ID
$latestDate = [DateTime]::ParseExact([string]$probe[-1].WRTTIME_DESC, "yyyy-MM-dd", $null)
Write-Host "  최신 주 $latestWeek ($($latestDate.ToString('yyyy-MM-dd')) 기준)"

# 받을 주간 계열: (표, 지역 코드, 기간 길이)
$weeklyJobs = [System.Collections.Generic.List[object]]::new()
foreach ($r in $config.regions) {
    foreach ($t in "sale", "jeonse") { $weeklyJobs.Add(@{ t = $t; cls = [int]$r.cls; weeks = [int]$config.rone.weeksLong }) }
    if ($r.demand) { foreach ($t in "buy", "rent") { $weeklyJobs.Add(@{ t = $t; cls = [int]$r.cls; weeks = [int]$config.rone.weeksLong }) } }
    foreach ($g in @($r.groups)) {
        if (-not $g) { continue }
        foreach ($t in "sale", "jeonse") { $weeklyJobs.Add(@{ t = $t; cls = [int]$g.cls; weeks = [int]$config.rone.weeksShort }) }
        foreach ($d in @($g.districts)) {
            if (-not $d) { continue }
            foreach ($t in "sale", "jeonse") { $weeklyJobs.Add(@{ t = $t; cls = [int]$d[1]; weeks = [int]$config.rone.weeksShort }) }
        }
    }
}

$weeklyFailed = 0
foreach ($j in $weeklyJobs) {
    $key = "$($j.t):$($j.cls)"
    if (-not $hist.weekly.ContainsKey($key)) { $hist.weekly[$key] = @{} }
    $store = $hist.weekly[$key]
    $want = Get-WeekId $latestDate.AddDays(-7 * ($j.weeks - 1))
    $have = @($store.Keys | Sort-Object)
    # 이미 받은 값이 필요한 처음 주까지 닿으면, 마지막으로 받은 주의 한 주 전부터만 다시 받는다(발표 뒤 고쳐지는 일에 대비).
    $from = if ($have.Count -and $have[0] -le $want) { $have[[math]::Max(0, $have.Count - 2)] } else { $want }
    try {
        foreach ($row in (Get-RoneRange $wk.($j.t).id "WK" $j.cls $from $latestWeek)) {
            $id = [string]$row.WRTTIME_IDTFR_ID
            $store[$id] = [math]::Round([double]$row.DTA_VAL, 4)
            if ($row.WRTTIME_DESC) { $hist.weekDates[$id] = [string]$row.WRTTIME_DESC }
        }
    } catch {
        $weeklyFailed++
        Write-Warning "R-ONE 주간 $key 실패: $($_.Exception.Message)"
    }
}
$status["rone.weekly"] = [ordered]@{ ok = ($weeklyFailed -eq 0); note = if ($weeklyFailed) { "$weeklyFailed 개 계열은 이번에 받지 못해 저장해 둔 값을 씁니다" } else { "" }; asOf = $latestDate.ToString("yyyy-MM-dd") }
Write-Host "  주간 계열 $($weeklyJobs.Count)개, R-ONE 호출 $script:roneCalls 번, 실패 $weeklyFailed"

Write-Host "R-ONE 월간..."
$monthFrom = $nowKst.AddMonths(-[int]$config.rone.monthsBack).ToString("yyyyMM")
$monthTo = $nowKst.ToString("yyyyMM")
$monthlyFailed = @()
foreach ($m in $config.rone.monthly) {
    foreach ($p in $m.cls.PSObject.Properties) {
        $key = "$($m.key):$($p.Name)"
        if (-not $hist.monthly.ContainsKey($key)) { $hist.monthly[$key] = @{} }
        $store = $hist.monthly[$key]
        $have = @($store.Keys | Sort-Object)
        $from = if ($have.Count -and ($have[0] -replace '-', '') -le $monthFrom) { ($have[[math]::Max(0, $have.Count - 3)] -replace '-', '') } else { $monthFrom }
        try {
            foreach ($row in (Get-RoneRange $m.id "MM" $p.Value $from $monthTo $m.itm)) {
                $id = [string]$row.WRTTIME_IDTFR_ID
                $store["$($id.Substring(0, 4))-$($id.Substring(4, 2))"] = [math]::Round([double]$row.DTA_VAL, 4)
            }
        } catch {
            $monthlyFailed += $key
            Write-Warning "R-ONE 월간 $key 실패: $($_.Exception.Message)"
        }
    }
}
$status["rone.monthly"] = [ordered]@{ ok = ($monthlyFailed.Count -eq 0); note = if ($monthlyFailed.Count) { "$($monthlyFailed -join ', ') 은 저장해 둔 값입니다" } else { "" } }
Write-Host "  R-ONE 누적 호출 $script:roneCalls 번"

# ---- ECOS ------------------------------------------------------------------------------------
Write-Host "ECOS..."
$ecosKey = if ($env:ECOS_API_KEY) { $env:ECOS_API_KEY } else { "sample" }
$ecosFailed = @()
$eFrom = $nowKst.AddMonths(-[int]$config.ecosMonths).ToString("yyyyMM")
$eTo = $nowKst.ToString("yyyyMM")
foreach ($e in $config.ecos) {
    if (-not $hist.ecos.ContainsKey($e.key)) { $hist.ecos[$e.key] = @{} }
    $store = $hist.ecos[$e.key]
    $items = (@($e.item1, $e.item2) | Where-Object { $_ }) -join "/"
    try {
        $got = 0
        for ($from = 1; $from -le 200; $from += 10) {
            $uri = "https://ecos.bok.or.kr/api/StatisticSearch/$([uri]::EscapeDataString($ecosKey))/json/kr/$from/$($from + 9)/$($e.code)/M/$eFrom/$eTo/$items"
            $resp = $null
            for ($try = 1; $try -le 2 -and -not $resp; $try++) {
                try { $resp = Invoke-RestMethod -Uri $uri -Headers $ua -TimeoutSec 30 } catch { if ($try -eq 2) { throw }; Start-Sleep -Seconds 3 }
            }
            if ($resp.RESULT) { if ($resp.RESULT.CODE -eq "INFO-200") { break }; throw "ECOS $($resp.RESULT.CODE) $($resp.RESULT.MESSAGE)" }
            $page = @($resp.StatisticSearch.row)
            foreach ($r in $page) {
                $t = [string]$r.TIME
                if ($t -match '^\d{6}$' -and [string]$r.DATA_VALUE -match '^-?[\d.]+$') { $store["$($t.Substring(0, 4))-$($t.Substring(4, 2))"] = [double]$r.DATA_VALUE; $got++ }
            }
            if ($page.Count -lt 10) { break }
            Start-Sleep -Milliseconds 200
        }
        if (-not $got) { throw "자료 없음" }
    } catch {
        $ecosFailed += $e.key
        Write-Warning "ECOS $($e.key) 실패: $($_.Exception.Message)"
    }
}
$status["ecos"] = [ordered]@{ ok = ($ecosFailed.Count -eq 0); note = if ($ecosFailed.Count) { "$($ecosFailed -join ', ') 은 저장해 둔 값입니다" } else { "" } }

Write-History $hist

# ---- 화면에 넣을 자료 ------------------------------------------------------------------------
# 주간: 도시 계열이 가진 주들을 한 줄 축으로 삼고, 모든 계열을 그 축에 맞춰 값 배열로 둔다(없으면 null).
$axisWeeks = @($hist.weekly["sale:50001"].Keys | Where-Object { $_ -le $latestWeek } | Sort-Object | Select-Object -Last ([int]$config.rone.weeksLong))
$series = [ordered]@{}
foreach ($key in ($hist.weekly.Keys | Sort-Object)) {
    $m = $hist.weekly[$key]
    $series[$key] = @($axisWeeks | ForEach-Object { if ($m.ContainsKey($_)) { $m[$_] } else { $null } })
}
$toPairs = { param($m) @($m.Keys | Sort-Object | ForEach-Object { , @($_, $m[$_]) }) }
$monthly = [ordered]@{}; foreach ($k in ($hist.monthly.Keys | Sort-Object)) { $monthly[$k] = & $toPairs $hist.monthly[$k] }
$ecos = [ordered]@{}; foreach ($k in ($hist.ecos.Keys | Sort-Object)) { $ecos[$k] = & $toPairs $hist.ecos[$k] }

$data = [ordered]@{
    generated = $nowKst.ToString("yyyy-MM-dd HH:mm")
    title     = $config.title
    subtitle  = $config.subtitle
    weekly    = [ordered]@{
        latest = $latestWeek; latestDate = $latestDate.ToString("yyyy-MM-dd")
        weeks  = $axisWeeks
        dates  = @($axisWeeks | ForEach-Object { $hist.weekDates[$_] })
        series = $series
    }
    monthly   = $monthly
    ecos      = $ecos
    meta      = [ordered]@{ monthly = $config.rone.monthly; ecos = $config.ecos; regions = $config.regions }
    status    = $status
}
$json = ConvertTo-Json $data -Depth 12 -Compress
# 페이지 안 <script> 에 넣으므로 '</' 를 끊어 둔다.
$json = $json -replace '</', '<\/'
$template = Get-Content -Raw -Encoding utf8 (Join-Path $root "template.html")
if ($template -notmatch '__DATA_JSON__') { throw "template.html 에 __DATA_JSON__ 자리가 없습니다" }
$html = $template.Replace("__DATA_JSON__", $json)
[IO.File]::WriteAllText((Join-Path $root $Out), $html, [Text.UTF8Encoding]::new($false))
Write-Host "완료: $Out ($([math]::Round($html.Length / 1024))KB), 주 $($axisWeeks.Count)개, R-ONE 호출 $script:roneCalls 번"
