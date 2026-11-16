#Requires -Version 7
# 부동산 시장 Dashboard(서울·부산 아파트) 생성 스크립트.
#
# 하는 일: 한국부동산원 R-ONE(주간·월간 아파트 통계, 월세, 매입자 거주지·연령)과 한국은행 ECOS(금리·미분양·인허가·
# 주택가격전망·주택 수)를 받아 data-history.json 에 쌓는다. 구글 뉴스 RSS 는 주별 주제 수를 news-history.json 에 쌓는다.
# template.html 의 __DATA_JSON__ 자리에 자료를, __GEO_JSON__ 자리에 지도 경계(geo/maps.json)를 넣어 dashboard.html 을 만든다.
# 화면의 계산(변동률, 연속 주, 시장 온도, 지도 색, 월 상환액 등)은 template.html 의 스크립트가 한다.
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
# GitHub 러너에서 R-ONE 은 보통 0.5~0.8초에 답하지만, 10번에 1번꼴로 연결만 받고 답을 주지 않는다(2026-11-15 측정).
# 처음 만든 판은 30초 제한 시간을 다 기다리며 한 번에 하나씩 1,500번을 불러 40분이 넘게 걸렸다.
# 그래서 (1) 연결을 다시 쓰고 (2) 제한 시간을 8초로 줄이고 (3) 요청을 미리 기간 구간으로 나눠 12개씩 동시에 보내고
# (4) 실패한 요청만 모아 다시 보낸다.
$roneBase = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
$script:roneCalls = 0
$script:http = [System.Net.Http.HttpClient]::new()
$script:http.Timeout = [TimeSpan]::FromSeconds(8)
$script:http.DefaultRequestHeaders.UserAgent.ParseAdd($ua["User-Agent"])

function Get-RoneUri([System.Collections.IDictionary]$q) {
    $parts = @("Type=json", "pSize=5") + @($q.GetEnumerator() | ForEach-Object { "$($_.Key)=$([uri]::EscapeDataString([string]$_.Value))" })
    "${roneBase}?" + ($parts -join "&")
}
function ConvertFrom-RoneBody([string]$s) {
    $r = $s | ConvertFrom-Json
    if ($r.RESULT) {
        if ($r.RESULT.CODE -eq "INFO-200") { return , @() }   # 해당 기간 자료 없음
        throw "R-ONE $($r.RESULT.CODE) $($r.RESULT.MESSAGE)"
    }
    if (-not $r.SttsApiTblData) { throw "R-ONE 응답 형식이 예상과 다릅니다" }
    , @($r.SttsApiTblData[1].row)
}
# 한 번 부르기(최신 주 찾기 같은 몇 번 안 되는 호출). 답이 없으면 짧게 쉬고 다시.
function Invoke-Rone([System.Collections.IDictionary]$q) {
    $uri = Get-RoneUri $q
    for ($try = 1; $try -le 5; $try++) {
        try { $script:roneCalls++; return ConvertFrom-RoneBody ($script:http.GetStringAsync($uri).GetAwaiter().GetResult()) }
        catch { if ($try -eq 5) { throw }; Start-Sleep -Milliseconds (500 * $try) }
    }
}
# 여러 요청을 12개씩 동시에 보낸다. 실패한 것만 모아 다시 보낸다(최대 5바퀴). 각 요청에 rows 또는 err 가 채워진다.
function Invoke-RoneMany([object[]]$reqs, [int]$parallel = 12) {
    $pending = @($reqs)
    for ($round = 1; $round -le 5 -and $pending.Count; $round++) {
        $failed = [System.Collections.Generic.List[object]]::new()
        for ($i = 0; $i -lt $pending.Count; $i += $parallel) {
            $batch = @($pending[$i..([math]::Min($i + $parallel, $pending.Count) - 1)])
            $tasks = @(foreach ($r in $batch) { $script:roneCalls++; $script:http.GetStringAsync($r.uri) })
            for ($k = 0; $k -lt $batch.Count; $k++) {
                try { $batch[$k].rows = ConvertFrom-RoneBody ($tasks[$k].GetAwaiter().GetResult()); $batch[$k].err = $null }
                catch { $ex = $_.Exception; $batch[$k].err = if ($ex.InnerException) { $ex.InnerException.Message } else { $ex.Message }; $failed.Add($batch[$k]) }
            }
        }
        $pending = @($failed)
        if ($pending.Count) { Write-Host "    다시 보낼 요청 $($pending.Count)개($round 바퀴째)"; Start-Sleep -Milliseconds 800 }
    }
}

function Get-NextPeriod([string]$id, [string]$cycle) {
    $y = [int]$id.Substring(0, 4); $n = [int]$id.Substring(4)
    $max = if ($cycle -eq "WK") { 53 } else { 12 }
    if ($n -ge $max) { return ("{0}{1:D2}" -f ($y + 1), 1) }
    "{0}{1:D2}" -f $y, ($n + 1)
}

# 기간 범위를 5행씩 이어 받는다(최신 주 찾기와, 구간 요청이 5행으로 꽉 차 잘렸을 때 나머지를 받을 때만 쓴다).
function Get-RoneRange([string]$table, [string]$cycle, $cls, [string]$from, [string]$to, $itm = $null, $grp = $null) {
    $rows = [System.Collections.Generic.List[object]]::new()
    $start = $from
    for ($guard = 0; $guard -lt 300; $guard++) {
        $q = [ordered]@{ STATBL_ID = $table; DTACYCLE_CD = $cycle; CLS_ID = $cls; START_WRTTIME = $start; END_WRTTIME = $to }
        if ($itm) { $q.ITM_ID = $itm }
        if ($grp) { $q.GRP_ID = $grp }
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

# 기간 번호 목록을 구간으로 나눈다. 구간 끝은 다음 구간 시작 번호 바로 앞이라 사이에 빠지는 번호가 없다
# (연말 주 번호가 ISO 와 달라도 범위 비교라 어느 한 구간에는 들어간다). 한 구간은 많아야 5행이 되도록 크기를 잡는다.
function Split-Periods([string[]]$ids, [int]$size, [string]$last) {
    @(for ($i = 0; $i -lt $ids.Count; $i += $size) {
        $end = if ($i + $size -lt $ids.Count) { ([int64]$ids[$i + $size] - 1).ToString() } else { $last }
        , @($ids[$i], $end)
    })
}
# 구간 요청들을 만든다. key 는 data-history 의 계열 이름. grp 는 지역을 GRP_ID 로 고르는 표(매입자 표)에만 쓴다.
function New-RoneRequests([string]$key, [string]$table, [string]$cycle, $cls, $itm, [object[]]$windows, $grp = $null) {
    @(foreach ($w in $windows) {
        $q = [ordered]@{ STATBL_ID = $table; DTACYCLE_CD = $cycle; CLS_ID = $cls; START_WRTTIME = $w[0]; END_WRTTIME = $w[1] }
        if ($itm) { $q.ITM_ID = $itm }
        if ($grp) { $q.GRP_ID = $grp }
        [PSCustomObject]@{ key = $key; table = $table; cycle = $cycle; cls = $cls; itm = $itm; grp = $grp; end = $w[1]; uri = (Get-RoneUri $q); rows = $null; err = $null }
    })
}
# 구간 요청을 보내고, 5행으로 꽉 찬 구간은 마지막 행 다음부터 나머지를 받는다. 계열마다 행 목록과 실패 여부를 돌려준다.
function Get-RoneSeriesRows([object[]]$reqs) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    Invoke-RoneMany $reqs
    $out = @{}
    foreach ($r in $reqs) {
        if (-not $out.ContainsKey($r.key)) { $out[$r.key] = @{ rows = [System.Collections.Generic.List[object]]::new(); failed = 0 } }
        if ($r.err) { $out[$r.key].failed++; continue }
        foreach ($row in @($r.rows)) { $out[$r.key].rows.Add($row) }
        $rows = @($r.rows)
        if ($rows.Count -ge 5 -and [string]$rows[-1].WRTTIME_IDTFR_ID -lt $r.end) {
            try { foreach ($row in (Get-RoneRange $r.table $r.cycle $r.cls (Get-NextPeriod ([string]$rows[-1].WRTTIME_IDTFR_ID) $r.cycle) $r.end $r.itm $r.grp)) { $out[$r.key].rows.Add($row) } }
            catch { $out[$r.key].failed++ }
        }
    }
    Write-Host "  요청 $($reqs.Count)개, $([math]::Round($sw.Elapsed.TotalSeconds))초"
    $out
}

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
# 전국 지도용 시·도 매매(서울·부산처럼 위에서 이미 받는 지역은 건너뛴다)
$cityCls = @($config.regions | ForEach-Object { [int]$_.cls })
foreach ($p in $config.provinces) {
    if ($cityCls -contains [int]$p.cls) { continue }
    $weeklyJobs.Add(@{ t = "sale"; cls = [int]$p.cls; weeks = [int]$config.rone.weeksShort })
}

# 계열마다 받을 주를 정한다. 이미 받은 값이 필요한 처음 주까지 닿으면 마지막으로 받은 주의 한 주 전부터만(발표 뒤 고쳐지는 일에 대비).
$reqs = [System.Collections.Generic.List[object]]::new()
foreach ($j in $weeklyJobs) {
    $key = "$($j.t):$($j.cls)"
    if (-not $hist.weekly.ContainsKey($key)) { $hist.weekly[$key] = @{} }
    $wantFrom = $latestDate.AddDays(-7 * ($j.weeks - 1))
    $have = @($hist.weekly[$key].Keys | Sort-Object)
    $from = $wantFrom
    if ($have.Count -and $have[0] -le (Get-WeekId $wantFrom)) {
        $prev = $hist.weekDates[$have[[math]::Max(0, $have.Count - 2)]]
        $from = if ($prev) { [DateTime]::ParseExact($prev, "yyyy-MM-dd", $null) } else { $latestDate.AddDays(-14) }
    }
    $ids = @(for ($d = $from; $d -le $latestDate; $d = $d.AddDays(7)) { Get-WeekId $d })
    if (-not $ids.Count) { continue }
    foreach ($q in (New-RoneRequests $key $wk.($j.t).id "WK" $j.cls $null (Split-Periods $ids 4 $latestWeek))) { $reqs.Add($q) }
}
$got = Get-RoneSeriesRows $reqs.ToArray()
$weeklyFailed = @($got.Keys | Where-Object { $got[$_].failed })
foreach ($key in $got.Keys) {
    foreach ($row in $got[$key].rows) {
        $id = [string]$row.WRTTIME_IDTFR_ID
        $hist.weekly[$key][$id] = [math]::Round([double]$row.DTA_VAL, 4)
        if ($row.WRTTIME_DESC) { $hist.weekDates[$id] = [string]$row.WRTTIME_DESC }
    }
}
foreach ($k in $weeklyFailed) { Write-Warning "R-ONE 주간 $k 일부 구간을 받지 못했습니다(저장해 둔 값을 씁니다)" }
$status["rone.weekly"] = [ordered]@{ ok = ($weeklyFailed.Count -eq 0); note = if ($weeklyFailed.Count) { "$($weeklyFailed.Count)개 계열은 일부 주를 받지 못해 저장해 둔 값을 씁니다" } else { "" }; asOf = $latestDate.ToString("yyyy-MM-dd") }
Write-Host "  주간 계열 $($weeklyJobs.Count)개, R-ONE 호출 누적 $script:roneCalls 번, 일부 실패 $($weeklyFailed.Count)"

Write-Host "R-ONE 월간..."
$monthFrom = $nowKst.AddMonths(-[int]$config.rone.monthsBack).ToString("yyyyMM")
$monthTo = $nowKst.ToString("yyyyMM")
$reqs = [System.Collections.Generic.List[object]]::new()
foreach ($m in $config.rone.monthly) {
    # 6차 화면에 더한 표(월세·매입자)는 months 로 받을 기간을 짧게 둔다
    $mFrom = if ($m.months) { $nowKst.AddMonths(-[int]$m.months).ToString("yyyyMM") } else { $monthFrom }
    foreach ($p in $m.cls.PSObject.Properties) {
        $key = "$($m.key):$($p.Name)"
        $grp = if ($m.grp) { $m.grp.($p.Name) } else { $null }
        if (-not $hist.monthly.ContainsKey($key)) { $hist.monthly[$key] = @{} }
        $have = @($hist.monthly[$key].Keys | Sort-Object)
        $from = if ($have.Count -and ($have[0] -replace '-', '') -le $mFrom) { ($have[[math]::Max(0, $have.Count - 3)] -replace '-', '') } else { $mFrom }
        $ids = [System.Collections.Generic.List[string]]::new()
        for ($id = $from; $id -le $monthTo; $id = Get-NextPeriod $id "MM") { $ids.Add($id) }
        foreach ($q in (New-RoneRequests $key $m.id "MM" $p.Value $m.itm (Split-Periods $ids.ToArray() 5 $monthTo) $grp)) { $reqs.Add($q) }
    }
}
$got = Get-RoneSeriesRows $reqs.ToArray()
$monthlyFailed = @($got.Keys | Where-Object { $got[$_].failed })
foreach ($key in $got.Keys) {
    foreach ($row in $got[$key].rows) {
        $id = [string]$row.WRTTIME_IDTFR_ID
        $hist.monthly[$key]["$($id.Substring(0, 4))-$($id.Substring(4, 2))"] = [math]::Round([double]$row.DTA_VAL, 4)
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
    $annual = $e.cycle -eq "A"
    $range = if ($annual) { "A/$($nowKst.Year - 6)/$($nowKst.Year)" } else { "M/$eFrom/$eTo" }
    try {
        $got = 0
        for ($from = 1; $from -le 200; $from += 10) {
            $uri = "https://ecos.bok.or.kr/api/StatisticSearch/$([uri]::EscapeDataString($ecosKey))/json/kr/$from/$($from + 9)/$($e.code)/$range/$items"
            $resp = $null
            for ($try = 1; $try -le 2 -and -not $resp; $try++) {
                try { $resp = Invoke-RestMethod -Uri $uri -Headers $ua -TimeoutSec 30 } catch { if ($try -eq 2) { throw }; Start-Sleep -Seconds 3 }
            }
            if ($resp.RESULT) { if ($resp.RESULT.CODE -eq "INFO-200") { break }; throw "ECOS $($resp.RESULT.CODE) $($resp.RESULT.MESSAGE)" }
            $page = @($resp.StatisticSearch.row)
            foreach ($r in $page) {
                $t = [string]$r.TIME
                if ([string]$r.DATA_VALUE -notmatch '^-?[\d.]+$') { continue }
                if ($annual -and $t -match '^\d{4}$') { $store[$t] = [double]$r.DATA_VALUE; $got++ }
                elseif ($t -match '^\d{6}$') { $store["$($t.Substring(0, 4))-$($t.Substring(4, 2))"] = [double]$r.DATA_VALUE; $got++ }
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

# ---- 뉴스: 주별 이슈 흐름(구글 뉴스 RSS) ---------------------------------------------------------
# 묶음(서울·부산·전국·정책)마다 검색어 몇 개로 최근 7일 기사(when:7d)를 받아, 기사가 나온 주(월~일, KST)에 더한다.
# 같은 제목(앞 14글자)은 한 번만 센다(주마다 제목 지문을 이번 주·지난주만 남겨 둔다). 시장 낱말(keep)이 있는 제목만, 사건·사고(drop)는 뺀다.
# 제목의 주제 낱말로 주제별 기사 수를 세어 news-history.json 에 쌓는다(묶음별 기사 수·주제별 수·대표 기사 3개).
# 지난 주를 묻는 검색(after:/before:)은 GitHub 실행 환경에서 구글이 503 으로 막아(2026-11-16 확인), 처음 12주는 내 PC 에서
# tools/news-backfill.py 로 채웠다. 실행 중 구글이 막으면(503·429) 그 실행의 뉴스 검색은 멈추고 지난 값(기사 목록 포함)을 쓴다.
Write-Host "뉴스..."
$nc = $config.news
$newsPath = Join-Path $root "news-history.json"
$nh = if (Test-Path $newsPath) { Get-Content -Raw -Encoding utf8 $newsPath | ConvertFrom-Json -AsHashtable } else { @{} }
foreach ($k in "weeks", "items") { if (-not $nh.ContainsKey($k) -or $null -eq $nh[$k]) { $nh[$k] = @{} } }
$keep = [regex]::new($nc.keep); $drop = [regex]::new($nc.drop)
$topicRx = [ordered]@{}; foreach ($t in $nc.topics) { $topicRx[$t.key] = [regex]::new($t.kw) }
$issueKeys = @($nc.topics | Where-Object { -not $_.mood } | ForEach-Object { $_.key })
$groupNames = @($nc.groups.PSObject.Properties | ForEach-Object { $_.Name })
$sha = [System.Security.Cryptography.SHA1]::Create()
function Get-TitleId([string]$t) {
    $k = $t -replace '\W', ''; $k = $k.Substring(0, [math]::Min(14, $k.Length))
    -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($k))[0..3] | ForEach-Object { $_.ToString("x2") })
}
function Get-GNews([string]$q) {
    $u = "https://news.google.com/rss/search?q=$([uri]::EscapeDataString($q))&hl=ko&gl=KR&ceid=KR:ko"
    for ($try = 1; $try -le 2; $try++) {
        try { return @(Invoke-RestMethod -Uri $u -Headers $ua -TimeoutSec 20) }
        catch { if ($try -eq 2 -or $_.Exception.Message -match '503|429') { throw }; Start-Sleep -Seconds 2 }
    }
}
function ConvertTo-NewsItem($it) {
    $src = if ($it.source -is [string]) { $it.source } else { [string]$it.source.'#text' }
    $t = [string]$it.title
    # 언론사가 제목에 " - 언론사"를 이미 넣은 경우 구글이 한 번 더 붙이므로 끝에서 되풀이해 지운다
    while ($src -and $t.TrimEnd().EndsWith(" - $src")) { $t = $t.TrimEnd(); $t = $t.Substring(0, $t.Length - $src.Length - 3) }
    $t = $t.Trim()
    if (-not $t -or -not $keep.IsMatch($t) -or $drop.IsMatch($t)) { return }
    $when = try { [DateTimeOffset]::Parse([string]$it.pubDate, [Globalization.CultureInfo]::InvariantCulture) } catch { $null }
    if (-not $when) { return }
    [PSCustomObject]@{ t = $t; s = $src; when = [TimeZoneInfo]::ConvertTime($when, $tz); u = [string]$it.link; id = (Get-TitleId $t)
                       tp = @(foreach ($k in $topicRx.Keys) { if ($topicRx[$k].IsMatch($t)) { $k } }) }
}
$monday = $nowKst.Date.AddDays(-(([int]$nowKst.DayOfWeek + 6) % 7))
$curW = $monday.ToString("yyyy-MM-dd"); $prevW = $monday.AddDays(-7).ToString("yyyy-MM-dd")
$blocked = $false; $newsFailed = 0; $newsCalls = 0; $added = 0
foreach ($g in $groupNames) {
    $list = [System.Collections.Generic.List[object]]::new(); $seen = @{}
    foreach ($q in $nc.groups.$g.queries) {
        if ($blocked) { break }
        try { $raw = Get-GNews "$q when:7d"; $newsCalls++ }
        catch { $newsFailed++; if ($_.Exception.Message -match '503|429') { $blocked = $true }; Write-Warning "뉴스 $g '$q' 실패: $($_.Exception.Message)"; continue }
        foreach ($it in $raw) { $x = ConvertTo-NewsItem $it; if (-not $x -or $seen.ContainsKey($x.id)) { continue }; $seen[$x.id] = 1; $list.Add($x) }
        Start-Sleep -Milliseconds 300
    }
    # 주별 집계에 더하기(이번 주·지난주만)
    foreach ($x in $list) {
        $d = $x.when.DateTime.Date; $w = $d.AddDays(-(([int]$d.DayOfWeek + 6) % 7)).ToString("yyyy-MM-dd")
        if ($w -ne $curW -and $w -ne $prevW) { continue }
        if (-not $nh.weeks.ContainsKey($w)) { $nh.weeks[$w] = @{} }
        $r = $nh.weeks[$w][$g]
        if (-not $r) { $r = @{ n = 0; tp = @{}; top = @(); ids = @() }; $nh.weeks[$w][$g] = $r }
        if ($null -eq $r.ids) { $r.ids = @() }
        if ($null -eq $r.tp) { $r.tp = @{} }
        if (@($r.ids) -contains $x.id) { continue }
        $r.ids = @($r.ids) + $x.id; $r.n = [int]$r.n + 1; $added++
        foreach ($k in $x.tp) { $r.tp[$k] = [int]$r.tp[$k] + 1 }
        if (@($r.top).Count -lt 3 -and @($x.tp | Where-Object { $issueKeys -contains $_ }).Count) {
            $r.top = @($r.top) + [ordered]@{ t = $x.t; s = $x.s; u = $x.u; d = $x.when.ToString("M'/'d") }
        }
    }
    # 화면 목록(최근 7일). 이번 실행에서 못 받았으면 지난번 목록을 그대로 둔다.
    if ($list.Count) {
        $cut = $nowKst.AddDays(-7)
        $nh.items[$g] = @($list | Where-Object { $_.when -ge $cut } | Sort-Object when -Descending | Select-Object -First ([int]$nc.perGroup) |
            ForEach-Object { [ordered]@{ t = $_.t; s = $_.s; d = $_.when.ToString("M'/'d"); u = $_.u; tp = @($_.tp) } })
    }
}
# 쌓은 값: 주마다 한 줄(최근 26주만). 제목 지문(ids)은 이번 주·지난주만 남긴다. 묶음·주제 순서를 고정해 바뀐 줄만 차이로 보이게 한다.
$wkKeys = @($nh.weeks.Keys | Sort-Object -Descending | Select-Object -First 26 | Sort-Object)
$lines = foreach ($k in $wkKeys) {
    $o = [ordered]@{}
    foreach ($g in $groupNames) {
        $r = $nh.weeks[$k][$g]; if (-not $r) { continue }
        $tp = [ordered]@{}; foreach ($t in $topicRx.Keys) { $tp[$t] = if ($r.tp -and $null -ne $r.tp[$t]) { [int]$r.tp[$t] } else { 0 } }
        $o[$g] = [ordered]@{ n = [int]$r.n; tp = $tp; top = @($r.top | ForEach-Object { [ordered]@{ t = $_.t; s = $_.s; u = $_.u; d = $_.d } }) }
        if ($k -eq $curW -or $k -eq $prevW) { $o[$g].ids = @($r.ids) }
    }
    "    " + (ConvertTo-Json $k) + ": " + (ConvertTo-Json $o -Depth 6 -Compress)
}
$itemLines = foreach ($g in $groupNames) { "    " + (ConvertTo-Json $g) + ": " + (ConvertTo-Json @($nh.items[$g]) -Depth 6 -Compress) }
[IO.File]::WriteAllText($newsPath, "{`n  `"items`": {`n" + ($itemLines -join ",`n") + "`n  },`n  `"weeks`": {`n" + ($lines -join ",`n") + "`n  }`n}`n", [Text.UTF8Encoding]::new($false))
$weekOut = @(foreach ($k in ($wkKeys | Select-Object -Last ([int]$nc.weeks))) {
    $o = [ordered]@{}; foreach ($g in $groupNames) { $r = $nh.weeks[$k][$g]; if ($r) { $o[$g] = [ordered]@{ n = [int]$r.n; tp = $r.tp; top = @($r.top) } } }
    [ordered]@{ w = $k; g = $o }
})
$items = [ordered]@{}; foreach ($g in $groupNames) { $items[$g] = @($nh.items[$g]) }
$news = [ordered]@{
    topics = @($nc.topics | ForEach-Object { [ordered]@{ key = $_.key; name = $_.name; short = $(if ($_.short) { $_.short } else { $_.name }); mood = $(if ($_.mood) { [int]$_.mood } else { 0 }) } })
    groups = [ordered]@{}; weeks = $weekOut; items = $items
}
$news.queries = [ordered]@{}
foreach ($g in $groupNames) { $news.groups[$g] = $nc.groups.$g.name; $news.queries[$g] = @($nc.groups.$g.queries) }
Write-Host "  뉴스 검색 $newsCalls 번, 실패 $newsFailed, 새 기사 $added, 주 $($weekOut.Count)개$(if ($blocked) { ' (구글이 막아 멈춤)' })"
$status["news"] = [ordered]@{ ok = ($newsFailed -eq 0); note = if ($blocked) { "구글 뉴스가 응답을 막아(503) 지난 값을 씁니다" } elseif ($newsFailed) { "뉴스 검색 $newsFailed 번 실패" } else { "" } }

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
    news      = $news
    meta      = [ordered]@{ monthly = $config.rone.monthly; ecos = $config.ecos; regions = $config.regions; provinces = $config.provinces
                            population = $config.population; policies = $config.policies; events = $config.events }
    status    = $status
}
$json = ConvertTo-Json $data -Depth 12 -Compress
# 페이지 안 <script> 에 넣으므로 '</' 를 끊어 둔다.
$json = $json -replace '</', '<\/'
$template = Get-Content -Raw -Encoding utf8 (Join-Path $root "template.html")
if ($template -notmatch '__DATA_JSON__') { throw "template.html 에 __DATA_JSON__ 자리가 없습니다" }
# 지도 경계(통계청 2018 행정구역을 tools/build-geo.py 로 줄여 SVG 좌표로 바꾼 것)
$geo = (Get-Content -Raw -Encoding utf8 (Join-Path $root "geo/maps.json")).Trim()
if ($template -notmatch '__GEO_JSON__') { throw "template.html 에 __GEO_JSON__ 자리가 없습니다" }
$html = $template.Replace("__GEO_JSON__", $geo).Replace("__DATA_JSON__", $json)
[IO.File]::WriteAllText((Join-Path $root $Out), $html, [Text.UTF8Encoding]::new($false))
Write-Host "완료: $Out ($([math]::Round($html.Length / 1024))KB), 주 $($axisWeeks.Count)개, R-ONE 호출 $script:roneCalls 번"
