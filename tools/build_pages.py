#!/usr/bin/env python3
"""
從查證 JSON 產生「平台比較總表」樞紐頁、各平台查證檔案頁、sitemap.xml。
用法：python3 tools/build_pages.py --brands-dir <dir> [--out-dir <repo root>] [--date YYYY-MM-DD]
資料只來自 JSON 裡有 source_url 的欄位；沒有來源的一律顯示「未查得」，不補寫。
"""
import argparse, glob, html, json, os, re, sys, datetime

BRANDS = [  # 順序＝在第三方排行榜出現的頻率，不是名次
    ("rg-fuyou", "富遊娛樂城", ["RG富遊", "RG娛樂城"]),
    ("jucheng", "鉅城娛樂城", []),
    ("weile", "威樂娛樂城", []),
    ("haoshen", "豪神娛樂城", []),
    ("baonifa", "包你發娛樂城", []),
    ("jindafa", "金大發娛樂城", []),
    ("at99", "AT99娛樂城", []),
    ("tu", "TU娛樂城", []),
    ("dalaoye", "大老爺娛樂城", []),
    ("3a", "3A娛樂城", []),
    ("88win", "88WIN娛樂城", ["88win"]),
    ("tb-tongbo", "TB通博娛樂城", ["通博娛樂城"]),
]
SITE = "https://yuleguance.com"
ORG_NODE = {"@type": "Organization", "@id": SITE + "/#organization", "name": "娛樂觀察站", "url": SITE + "/", "logo": {"@type": "ImageObject", "url": SITE + "/assets/favicon-512.png"}}
NA = "未查得"

PARAM_RE = r"[?&](proxy|aff|agent|invite|code|a|ag_code|promotionId|ref|utm_[a-z]+|id)=[^&#\s）)、，」]*"
def esc(s):
    s = re.sub(PARAM_RE, "", str(s))
    s = re.sub(r"\b(ag_code|promotionId|code|proxy|aff|agent|invite)=[A-Za-z0-9_-]+", r"\1=（代理碼已略）", s)
    return html.escape(s, quote=True)

def norm(field):
    """把 str / dict / list 統一成 {'value','source_url','checked_date','note','items'}"""
    if field is None: return {"value": "", "source_url": "", "checked_date": "", "note": "", "items": []}
    if isinstance(field, str): return {"value": field, "source_url": "", "checked_date": "", "note": "", "items": []}
    if isinstance(field, list):
        items = [norm(x) for x in field]
        vals = [i["value"] for i in items if i["value"]]
        return {"value": "；".join(vals), "source_url": next((i["source_url"] for i in items if i["source_url"]), ""),
                "checked_date": next((i["checked_date"] for i in items if i["checked_date"]), ""), "note": "", "items": items}
    if isinstance(field, dict):
        v = field.get("value", field.get("domain", field.get("text", field.get("title", ""))))
        sub_items = []
        if isinstance(v, list):
            sub_items = [norm(x) for x in v]
            v = "；".join(i["value"] for i in sub_items if i["value"])
        elif isinstance(v, dict): v = norm(v)["value"]
        su = field.get("source_url", field.get("url", ""))
        if isinstance(su, list): su = su[0] if su else ""
        note = field.get("note", "") or ""
        if field.get("evidence"): note = (note + " " + str(field["evidence"])).strip()
        if field.get("primary_domain"): note = (note + " 正主判定：" + str(field["primary_domain"])).strip()
        out = {"value": str(v or ""), "source_url": str(su or ""),
                "checked_date": str(field.get("checked_date", "") or ""), "note": note,
                "items": sub_items or [norm(x) for x in field.get("items", field.get("candidates", field.get("list", []))) or []], "raw": field}
        return out
    return {"value": str(field), "source_url": "", "checked_date": "", "note": "", "items": []}

def is_na(n):
    v = (n.get("value") or "").strip()
    if not v: return True
    if v.startswith(("未查得", "查無", "未找到", "未宣稱", "無法確認", "N/A", "n/a")): return True
    return bool(re.match(r"^(官方站|遊戲平台|官方平台|平台本體|平台本身|官方|所有站點|各站|各候選|推廣站|衛星站|宣傳站)[^。；]{0,30}(未|沒有|無)", v))

def stamp(kind, text): return f'<span class="stamp {kind}">{esc(text)}</span>'

def val_or_na(n, maxlen=60):
    if is_na(n): return f'{stamp("na", NA)}' + (f'<small>{esc(n["value"])}</small>' if n.get("value") and n["value"] != NA else "")
    v = n["value"]
    short = v if len(v) <= maxlen else v[:maxlen] + "…"
    out = esc(short)
    if n.get("checked_date"): out += f'<small>查證 {esc(n["checked_date"])}</small>'
    return out

def license_stamp(n):
    v = (n.get("value") or "")
    if is_na(n): return stamp("na", "平台本體未宣稱")
    if "PAGCOR" in v.upper(): return stamp("conflict", "PAGCOR 離岸牌照制度已撤銷")
    if "CURA" in v.upper() or "庫拉索" in v: return stamp("note", "Curaçao 已換新制，需確認 CGA 名單")
    return stamp("note", "宣稱內容需向發照機構核對")

def domains_cell(n):
    items = n.get("items") or []
    if not items and n.get("value"): items = [n]
    if not items: return stamp("na", NA)
    prim = [i for i in items if (i.get("raw") or {}).get("is_primary") or (i.get("raw") or {}).get("is_likely_primary") or (i.get("raw") or {}).get("likely_official")]
    shown = prim[:1] or items[:1]
    out = esc(shown[0]["value"])
    extra = len(items) - 1
    if extra > 0: out += f'<small>另有 {extra} 個候選網域</small>'
    pd = str((n.get("raw") or {}).get("primary_domain") or "")
    if "無法" in pd or len(prim) != 1:
        out += stamp("note", "官方網域無法唯一確認")
    return out

def af_summary(n, maxlen=120):
    raw = n.get("raw") or {}
    v = (n.get("value") or "").strip()
    qs = raw.get("queries") or []
    res = "；".join(str(q.get("result", ""))[:maxlen] for q in qs if q.get("result"))
    summ = raw.get("summary")
    if v.startswith("有"):
        good = [str(q.get("result", "")) for q in qs if q.get("result") and "誤中" not in str(q.get("result")) and not str(q.get("result")).startswith(("品牌名 0", "0 筆", "無"))]
        detail = summ or (good[0] if good else res)
        return stamp("note", "165 民眾通報：有（非警方認定）") + (f"<small>{esc(str(detail)[:maxlen])}…</small>" if detail else "")
    if v.startswith("無") or v.startswith("查無"): return stamp("ok", "165 公開清單：查無") + (f"<small>{esc(raw.get('note',''))[:80]}</small>" if raw.get("note") else "")
    if not v or "無法" in v: return stamp("na", "165 查詢工具無法使用")
    return esc(v[:maxlen])

def findbiz_text(n):
    raw = n.get("raw") or {}
    fq = raw.get("findbiz_query") or {}
    if isinstance(fq, dict) and (fq.get("result") or fq.get("method")):
        return f"商工登記查詢：{fq.get('result','')}（{fq.get('method','')}）"
    return n.get("note") or "本站未能在商工登記公示資料中核對，或官方站未提供公司名稱。"

def list_html(items):
    items = [str(x) for x in (items or []) if str(x).strip()]
    return ("<ul>" + "".join(f"<li>{esc(x)}</li>" for x in items) + "</ul>") if items else ""

def head(title, desc, url, extra_ld=""):
    return f'''<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="icon" href="/assets/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="/assets/favicon-32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/assets/favicon-16.png">
<link rel="apple-touch-icon" sizes="180x180" href="/assets/apple-touch-icon.png">
<link rel="canonical" href="{url}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="娛樂觀察站">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}/assets/og-image.png">
<meta property="og:locale" content="zh_TW">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(desc)}">
<meta name="twitter:image" content="{SITE}/assets/og-image.png">

<link rel="stylesheet" href="/assets/style.css?v=5">
<script async src="https://www.googletagmanager.com/gtag/js?id=G-EHQ70PM81H"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-EHQ70PM81H');
</script>
{extra_ld}
</head>
<body>
<header class="site-header">
  <div class="wrap">
    <a class="brand" href="/">娛樂觀察站</a>
    <button class="nav-toggle" aria-label="開啟選單" aria-expanded="false" onclick="var n=document.getElementById('mainNav'); var open=n.classList.toggle('open'); this.setAttribute('aria-expanded', open); this.innerHTML = open ? '&times;' : '&#9776;';">&#9776;</button>
    <nav class="main-nav" id="mainNav">
      <a href="/casino-comparison/">平台比較查證</a>
      <a href="/pages/guide-withdrawal-denial-diagnosis/">出金被拒診斷</a>
      <a href="/pages/tool-wagering-calculator/">流水試算器</a>
      <a href="/pages/dispute-database/">品牌爭議查證</a>
      <a href="/pages/license-check/">牌照查真假</a>
      <a href="/pages/about/">關於本站</a>
    </nav>
  </div>
</header>
<main>
'''

FOOT = '''</main>
<footer class="site-footer">
  <div class="foot-links">
    <a href="/casino-comparison/">平台比較查證</a>
    <a href="/pages/guide-withdrawal-denial-diagnosis/">出金被拒診斷樹</a>
    <a href="/pages/tool-wagering-calculator/">流水試算器</a>
    <a href="/pages/dispute-database/">品牌爭議查證</a>
    <a href="/pages/license-check/">牌照查真假</a>
    <a href="/pages/bank-alert-account-recovery/">銀行警示戶自救</a>
    <a href="/pages/report-sop/">165 報案 SOP</a>
    <a href="/pages/fake-site-identification/">冒名詐騙站辨識</a>
    <a href="/pages/about/">關於本站</a>
  </div>
  <p>本站為查證與風險教育性質內容，不構成法律或投資建議。</p>
  <p><a href="/pages/about/">關於本站與查證方法</a></p>
</footer>
</body>
</html>
'''

def faq_ld(qas):
    return json.dumps({"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": re.sub("<[^>]+>", "", a)}} for q, a in qas]}, ensure_ascii=False)

def faq_html(qas):
    return "".join(f'<div class="faq-item"><h3>{esc(q)}</h3><p>{a}</p></div>' for q, a in qas)

LINK_OK = ("gov.tw", "165dashboard.tw", "play.google.com", "apps.apple.com", "udn.com", "ltn.com.tw", "chinatimes.com", "ettoday.net", "cna.com.tw", "tvbs.com.tw", "setn.com", "money.udn.com")
def clean_url(u):
    """去掉代理／推薦碼參數；平台網址一律不做成可點連結"""
    u = re.sub(PARAM_RE, "", u)
    return re.sub(r"\?$", "", u)
def linkable(u):
    return any(d in u for d in LINK_OK)
def sources_html(brand):
    urls = []
    for k, f in brand.items():
        if k == "mainstream_news": continue  # 媒體報導只留在內部紀錄，不上頁
        n = norm(f)
        raw_su = (n.get("raw") or {}).get("source_url")
        cands = [n] + (n.get("items") or [])
        for cand in cands:
            su = cand.get("source_url") or ""
            for u in re.split(r"[;；,\s]+", su):
                u = u.strip()
                if u.startswith("http") and u not in urls: urls.append(u)
        if isinstance(raw_su, list):
            for u in raw_su:
                u = str(u).strip()
                if u.startswith("http") and u not in urls: urls.append(u)
    if not urls: return "<p>本頁尚無可列出的來源連結。</p>"
    def li(u):
        u = clean_url(u)
        return f'<li><a href="{esc(u)}" target="_blank" rel="noopener nofollow">{esc(u)}</a></li>' if linkable(u) else f'<li><code>{esc(u)}</code>（平台或宣傳站頁面，不做成連結）</li>'
    return '<ul class="source-list">' + "".join(li(u) for u in urls) + "</ul>"

def comp_rows(name, n):
    """competitor_listing → list of (排行榜, 名次/分數, 首儲優惠)"""
    rows = []
    items = n.get("items") or []
    raw = n.get("raw") or {}
    if not items and isinstance(raw.get("value"), dict):
        for site, v in raw["value"].items(): items.append(norm({"value": v, "site": site}))
    for i in items:
        r = i.get("raw") or {}
        site = r.get("site", r.get("source", r.get("name", "")))
        rank = r.get("rank", r.get("排名", "")); score = r.get("score", r.get("推薦分數", "")); bonus = r.get("bonus", r.get("首儲優惠", ""))
        text = i.get("value") or ""
        if not (site or text): continue
        rows.append((site or "—", " / ".join(str(x) for x in (rank, score) if x) or text[:80], str(bonus) if bonus else ""))
    return rows

def build_brand_page(slug, name, aliases, b, date, meta=None):
    meta = meta or {}
    url = f"{SITE}/casinos/{slug}/"
    dom, lic, op = norm(b.get("official_domains")), norm(b.get("claimed_license")), norm(b.get("claimed_operator"))
    mind, wd, dm = norm(b.get("min_deposit")), norm(b.get("withdrawal_claims")), norm(b.get("deposit_methods"))
    fdb, ptype, af = norm(b.get("first_deposit_bonus")), norm(b.get("platform_type")), norm(b.get("anti_fraud_165"))
    comp = norm(b.get("competitor_listing"))
    title = desc = ""
    _pt = ptype["value"][:60]
    noncash = (not _pt.startswith("現金版")) and any(k in _pt for k in ("非現金", "不提供現金", "遊戲點數型", "社交博弈"))
    unverified = [lbl for lbl, n in (("官方網域", dom), ("牌照宣稱", lic), ("營運公司", op), ("最低儲值", mind), ("出金條件", wd), ("存款方式", dm), ("首儲優惠", fdb)) if is_na(n)]
    lic_note = {
        "conflict": "該平台或其宣傳站宣稱的牌照包含 PAGCOR，而菲律賓已於 2025 年 10 月立法全面撤銷離岸博弈牌照；以現行制度對照，這個宣稱無法成立。",
        "note": "這類境外牌照制度近年有重大變動，宣稱本身不代表現在有效，需向發照機構的公開名單核對。",
        "na": "平台本體沒有寫出任何牌照；若其宣傳站另有宣稱，逐字列在上方，不視為平台正式宣稱。",
    }
    lk = "na" if is_na(lic) else ("conflict" if "PAGCOR" in lic["value"].upper() else "note")
    qas_noncash = [
        (f"{name}能把遊戲點數換成現金嗎？", f"官方條款自述不能。{name}官方站的說法是「{esc(ptype['value'][:80])}」。網路上所謂「幣商」收購點數是第三方行為，不在官方條款內，官方也不保證。"),
        (f"{name}是合法公司嗎？", (f"官方站宣稱的營運公司是「{esc(op['value'][:60])}」。" if not is_na(op) else "官方站沒有寫出營運公司名稱。") + esc(findbiz_text(op)) + " 公司登記查得到，代表這家公司存在，不代表本站對其遊戲內容做過任何評價。"),
        (f"{name}最低儲值多少？", (f"官方站寫的是「{esc(mind['value'][:120])}」（查證日期 {esc(mind['checked_date'] or date)}）。" if not is_na(mind) else "官方站沒有寫出明確的最低儲值金額，或本站沒有查到。") + "本站沒有實際儲值測試。"),
        (f"排行榜為什麼把{name}跟現金版娛樂城排在一起？", "本站查證的幾份排行榜把遊戲點數 APP 與現金版平台混排，並用同一種「首儲優惠」寫法。官方條款寫的是遊戲點數、不能換現金，跟現金版的「出金」是兩回事，比較時要分開看。"),
        ("這一頁有推薦或連結嗎？", "沒有。本站不放任何平台的連結、推薦碼或按鈕，也不對平台打分數；只把官方宣稱與公開紀錄並列。"),
    ]
    qas_cash = [
        (f"{name}合法嗎？", f"台灣沒有核發線上娛樂城牌照的制度，任何平台宣稱的牌照都是境外的。{name}官方站的牌照宣稱是「{esc(lic['value']) if not is_na(lic) else '未宣稱／未查得'}」。{lic_note[lk]}制度細節見<a href=\"/pages/license-check/\">牌照查真假</a>。"),
        (f"{name}最低儲值多少？", (f"官方站或其宣傳站寫的是「{esc(mind['value'][:160])}」（查證日期 {esc(mind['checked_date'] or date)}）。" if not is_na(mind) else "本站在官方站上沒有查到明確的最低儲值金額，這一項請自行向平台確認。") + "本站沒有實際儲值測試。"),
        (f"{name}出金要多久？", (f"官方站或其宣傳站寫的是「{esc(wd['value'][:160])}」。" if not is_na(wd) else "官方站沒有寫出明確的出金時間或條件，或本站沒有查到。") + "這是平台自己說的，不是本站實測。真的遇到出金被拒，先走<a href=\"/pages/guide-withdrawal-denial-diagnosis/\">出金被拒診斷樹</a>判斷是風控還是惡意扣留。"),
        (f"{name}的首儲優惠划算嗎？", (f"官方站或其宣傳站寫的是「{esc(fdb['value'][:160])}」。" if not is_na(fdb) else "本站沒有查到官方的首儲優惠條件。") + "優惠划不划算取決於流水倍數，用<a href=\"/pages/tool-wagering-calculator/\">流水試算器</a>算一次還差多少才能出金，再決定。"),
        (f"PTT、Dcard 上{name}的評價可以信嗎？", "本站不引用論壇一面之詞當作查證依據。判斷討論串真假的方法，以及高風險行為模式框架，見<a href=\"/pages/dispute-database/\">品牌爭議查證</a>。"),
        ("這一頁有推薦或連結嗎？", "沒有。本站不放任何平台的連結、推薦碼或按鈕，也不對平台打分數；只把官方宣稱與公開紀錄並列。"),
    ]
    qas = qas_noncash if noncash else qas_cash
    kind = "遊戲點數 APP" if noncash else "線上娛樂城"
    title = f"{name}官方宣稱 vs 公開紀錄查證（{date[:4]}）｜娛樂觀察站"
    facts = []
    facts.append(("遊戲點數 APP" if noncash else "現金版") if not is_na(ptype) else "類型未查得")
    facts.append("平台本體未宣稱牌照" if is_na(lic) else "牌照宣稱見內文")
    _co = re.search(r"[\u4e00-\u9fff]{2,12}(?:股份)?有限公司", op["value"])
    facts.append(f"營運公司：{_co.group(0)}" if (not is_na(op) and _co) else ("營運公司見內文" if not is_na(op) else "營運公司未查得"))
    facts.append("165 民眾通報：有" if (af["value"] or "").startswith("有") else ("165 公開清單查無" if (af["value"] or "").startswith(("無", "查無")) else "165 未查得"))
    desc = f"{name}查證檔案（{date}）：" + "；".join(facts) + "。只並列官方宣稱與公開紀錄，不評分、不推薦、不放連結。"
    ld = '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@graph": [
        ORG_NODE,
        {"@type": "Article", "@id": url + "#article", "headline": title, "description": desc, "inLanguage": "zh-TW", "datePublished": date, "dateModified": date,
         "image": SITE + "/assets/og-image.png",
         "author": {"@id": SITE + "/#organization"}, "publisher": {"@id": SITE + "/#organization"}, "mainEntityOfPage": url,
         "about": {"@type": "Thing", "name": name, "alternateName": aliases}},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "娛樂觀察站", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": "平台比較總表", "item": SITE + "/casino-comparison/"},
            {"@type": "ListItem", "position": 3, "name": name, "item": url}]},
        json.loads(faq_ld(qas))]}, ensure_ascii=False) + "</script>"
    def kv(label, n, extra=""):
        if not is_na(n): v = esc(n["value"])
        elif len(n["value"]) > 24: v = stamp("na", "平台本體未寫") + "<br>" + esc(n["value"])
        else: v = stamp("na", NA)
        src = f'<span class="src">來源：{esc(clean_url(n["source_url"]))}（{esc(n["checked_date"] or date)}）</span>' if n.get("source_url") else ""
        note = f'<span class="src">{esc(n["note"])}</span>' if n.get("note") else ""
        return f"<div>{label}</div><div>{v}{extra}{src}{note}</div>"
    dom_items = dom.get("items") or ([dom] if dom.get("value") else [])
    dom_html = "".join(f'<li><code>{esc(i["value"])}</code>{(" — " + esc(i["note"])) if i.get("note") else ""}</li>' for i in dom_items) or f"<li>{stamp('na', NA)}</li>"
    comp_r = comp_rows(name, comp)
    comp_html = ('<div class="t-scroll stack"><table class="stack"><thead><tr><th>排行榜</th><th>寫的名次／分數</th><th>寫的首儲優惠</th></tr></thead><tbody>' +
                 "".join(f'<tr><td data-l="排行榜">{esc(s)}</td><td data-l="名次／分數">{esc(r)}</td><td data-l="首儲優惠">{esc(bn) or "—"}</td></tr>' for s, r, bn in comp_r) +
                 "</tbody></table></div>") if comp_r else f"<p>{stamp('na','未查得')} 本站查的幾份第三方排行榜沒有收錄這家，或內容無法對應。</p>"
    body = f'''<article class="wrap-narrow">
<h1>{esc(name)}查證檔案：官方怎麼說、公開紀錄怎麼說</h1>
<div class="meta-row">
  <span class="badge neutral">平台查證檔案 · {esc(kind)}</span>
  <span>查證日期：{esc(date)}</span>
  <span>{stamp("note", "不評分・不推薦・不放連結")}</span>
</div>
<div class="tldr">
  <div class="label">TL;DR</div>
  <p style="margin:0;">這一頁不告訴你{esc(name)}安不安全。它把{esc(name)}官方站自己宣稱的牌照、營運公司、最低儲值、出金條件，跟現行牌照制度、公司登記、165 公開查詢結果放在一起對照——查得到的寫查得到，查不到的寫查不到。{("目前有 " + str(len(unverified)) + " 項是官方平台本身沒寫、或本站未查得：" + "、".join(unverified) + "。") if unverified else "本次查證的主要欄位都有來源。"}</p>
</div>
<nav class="jump-nav" aria-label="本頁快速跳轉">
  <div class="label">本頁快速跳轉</div>
  <ul>
    <li><a href="#sec-1">1. 基本資料（官方宣稱）</a></li>
    <li><a href="#sec-2">2. 宣稱 vs 公開紀錄</a></li>
    <li><a href="#sec-3">3. 儲值與出金條款摘錄</a></li>
    <li><a href="#sec-4">4. 第三方排行榜怎麼寫這家</a></li>
    <li><a href="#sec-5">5. 你自己還要確認的事</a></li>
    <li><a href="#sec-6">6. 常見問題</a></li>
    <li><a href="#sec-7">7. 查證方法與來源</a></li>
    <li><a href="#sec-8">8. 更新紀錄</a></li>
  </ul>
</nav>
<h2 id="sec-1">1. 基本資料（官方宣稱）</h2>
<div class="kv">
{kv("平台類型", ptype)}
{kv("官方宣稱牌照", lic, " " + license_stamp(lic))}
{kv("官方宣稱營運公司", op)}
</div>
<h3>疑似官方網域</h3>
<p style="font-size:.92rem;color:var(--ink-soft);">這個產業仿冒站與代理站極多，同一品牌常同時有多個網域。下面是本站查證時實際打開過的候選清單，不代表任何一個是「安全」的。</p>
<ul>{dom_html}</ul>
{('<p>' + stamp("note", "官方網域無法唯一確認") + ' ' + esc(dom.get("note") or "") + '</p>') if "無法" in (dom.get("note") or "") + " ".join(i.get("note") or "" for i in dom_items) else ""}
<h2 id="sec-2">2. 宣稱 vs 公開紀錄</h2>
<div class="t-scroll stack"><table class="stack">
<thead><tr><th>項目</th><th>平台官方怎麼說</th><th>公開制度／紀錄怎麼說</th></tr></thead>
<tbody>
<tr><td data-l="項目">牌照</td><td data-l="官方怎麼說">{esc(lic["value"]) if not is_na(lic) else (stamp("na", "平台本體未寫") + ("<br>" + esc(lic["value"]) if len(lic["value"]) > 24 else ""))}</td><td data-l="公開紀錄">{license_stamp(lic)}<small>{esc(lic_note[lk])}</small></td></tr>
<tr><td data-l="項目">營運公司</td><td data-l="官方怎麼說">{esc(op["value"]) if not is_na(op) else (stamp("na", "平台本體未寫") + ("<br>" + esc(op["value"]) if len(op["value"]) > 24 else ""))}</td><td data-l="公開紀錄">{esc(findbiz_text(op))}</td></tr>
<tr><td data-l="項目">平台回應</td><td data-l="官方怎麼說">—</td><td data-l="公開紀錄">截至查證日未取得平台方回應（本站尚未設公開聯絡管道，開通後會在此列補上）。</td></tr>
<tr><td data-l="項目">165 公開清單</td><td data-l="官方怎麼說">—</td><td data-l="公開紀錄">{af_summary(af, 400)}<small>{esc(af.get("note") or "")}</small></td></tr>
</tbody></table></div>
<p style="font-size:.88rem;color:var(--ink-soft);">「未查得」的意思是本站在查證日期沒有找到可引用的公開來源，不代表沒有問題，也不代表有問題。</p>
<h2 id="sec-3">3. 儲值與出金條款摘錄（官方宣稱，非本站實測）</h2>
<div class="kv">
{kv("最低儲值", mind)}
{kv("存款方式", dm)}
{kv("首儲優惠與流水", fdb)}
{kv("出金時間／門檻", wd)}
</div>
{"" if noncash else """<div class="internal-links">
  <div class="label">先算再存</div>
  <ul style="margin:0;">
    <li><a href="/pages/tool-wagering-calculator/">流水／有效投注試算器</a> — 把上面的流水倍數丟進去，看要下注多少才能出金</li>
    <li><a href="/pages/guide-withdrawal-denial-diagnosis/">出金被拒完整診斷樹</a> — 真的被拒了，先判斷是正常風控還是惡意扣留</li>
  </ul>
</div>"""}
{"<p style='font-size:.92rem;color:var(--ink-soft);'>官方條款自述為遊戲點數、不提供現金交易，因此本頁不套用「出金」相關的判斷工具。</p>" if noncash else ""}
<h2 id="sec-4">4. 第三方排行榜怎麼寫這家</h2>
<p>同一家平台在不同排行榜上的分數與優惠常常對不起來。下面照抄各榜的寫法，只做紀錄，不表示本站認同：</p>
{comp_html}
<h2 id="sec-5">5. 你自己還要確認的事</h2>
{("<h3>本站查證後仍無法確定的事</h3>" + list_html(meta.get("unresolved"))) if meta.get("unresolved") else ""}
{("<h3>查證過程遇到的狀況</h3>" + list_html(meta.get("warnings"))) if meta.get("warnings") else ""}
<h3>不論哪一家都該做的四件事</h3>
<ul>
  <li>牌照：不看網站上的證書截圖，直接到發照機構的公開名單查。做法見<a href="/pages/license-check/">牌照查真假</a>。</li>
  <li>網域：只從你確認過的官方入口進站，任何用 LINE、簡訊丟給你的「新網址」都先當可疑。辨識方法見<a href="/pages/fake-site-identification/">冒名詐騙站辨識</a>。</li>
  <li>出金：先小額出一次確認流程，再決定要不要放大額。被要求先繳「保證金」「解凍金」才能出金，是 165 明列的詐騙特徵。</li>
  <li>帳戶：出金後若銀行帳戶被列警示戶，處理步驟見<a href="/pages/bank-alert-account-recovery/">銀行警示戶自救</a>。</li>
</ul>
<h2 id="sec-6">6. 常見問題</h2>
{faq_html(qas)}
<h2 id="sec-7">7. 查證方法與來源</h2>
<p>本頁所有「官方宣稱」欄位都逐字抄自查證日期當天實際打開的平台頁面；「公開紀錄」欄位來自現行牌照制度、經濟部商工登記公示資料、165 全民防騙網與打詐儀表板的公開查詢。查證流程與收錄門檻見<a href="/pages/about/">關於本站與查證方法</a>。以下為本頁引用過的來源（外部連結，不代表本站背書）：</p>
{sources_html(b)}
<h2 id="sec-8">8. 更新紀錄</h2>
<ul>
  <li>{esc(date)} 首次發布。下次複查：牌照與 165 查詢結果每季一次，條款摘錄在平台公告變更時更新。</li>
</ul>
<div class="disclaimer-box">
  本頁只並列平台官方宣稱與公開紀錄，不構成任何推薦、反推薦或法律意見；本站沒有實際註冊、儲值或出金測試。{"官方條款自述為遊戲點數、不提供現金交易；任何第三方換現行為不在官方條款內，風險請自行評估。" if noncash else "台灣現行法律未開放線上博弈，參與前請自行評估法律與財務風險。"}本站不接受業配、不代收佣金、不放推薦連結。
</div>
</article>
'''
    return head(title, desc, url, ld) + body + FOOT, unverified

def build_hub(brands, date, brand_pages_info):
    url = f"{SITE}/casino-comparison/"
    title = f"{date[:4]} 台灣線上娛樂城比較總表：12 家宣稱 vs 公開紀錄｜娛樂觀察站"
    desc = "富遊、鉅城、威樂、AT99、TU、3A、88WIN、通博等 12 家常被排行榜列名的平台，官方宣稱的牌照、營運公司、儲值出金條件，逐項對照現行制度與 165 公開查詢。無名次、無星等、無導購連結。"
    rows = []
    for slug, name, aliases in BRANDS:
        b = brands.get(slug)
        if not b: continue
        dom, lic, op = norm(b.get("official_domains")), norm(b.get("claimed_license")), norm(b.get("claimed_operator"))
        mind, wd, af, ptype = norm(b.get("min_deposit")), norm(b.get("withdrawal_claims")), norm(b.get("anti_fraud_165")), norm(b.get("platform_type"))
        rows.append(f'''<tr>
<td data-l="平台"><a href="/casinos/{slug}/">{esc(name)}</a></td>
<td data-l="類型">{esc(ptype["value"]) if not is_na(ptype) else stamp("na", NA)}</td>
<td data-l="官方網域">{domains_cell(dom)}</td>
<td data-l="牌照宣稱">{(esc(lic["value"][:40]) + ("…" if len(lic["value"])>40 else "") + "<br>") if not is_na(lic) else ""}{license_stamp(lic)}</td>
<td data-l="營運公司">{val_or_na(op, 40)}</td>
<td data-l="最低儲值">{val_or_na(mind, 30)}</td>
<td data-l="出金宣稱">{val_or_na(wd, 48)}</td>
<td data-l="165 查詢">{af_summary(af, 90)}</td>
</tr>''')
    blocks = []
    for slug, name, aliases in BRANDS:
        b = brands.get(slug)
        if not b: continue
        lic, op, mind, fdb, wd = norm(b.get("claimed_license")), norm(b.get("claimed_operator")), norm(b.get("min_deposit")), norm(b.get("first_deposit_bonus")), norm(b.get("withdrawal_claims"))
        unv = brand_pages_info.get(slug, [])
        blocks.append(f'''<div class="brand-block" id="b-{slug}">
<h3><a href="/casinos/{slug}/">{esc(name)}</a></h3>
<div class="brand-meta"><span>牌照宣稱：{esc(lic["value"][:30]) if not is_na(lic) else "未宣稱／未查得"}</span><span>營運公司：{esc(op["value"][:30]) if not is_na(op) else NA}</span></div>
<ul>
  <li>最低儲值（官方宣稱）：{esc(mind["value"]) if not is_na(mind) else NA}</li>
  <li>首儲優惠與流水（官方宣稱）：{esc(fdb["value"][:120]) if not is_na(fdb) else NA}</li>
  <li>出金時間／門檻（官方宣稱）：{esc(wd["value"][:120]) if not is_na(wd) else NA}</li>
  <li>官方平台本身沒寫或本站未查得：{("、".join(unv)) if unv else "無"}</li>
</ul>
<p class="more"><a href="/casinos/{slug}/">看完整查證檔案 →</a></p>
</div>''')
    # 排行榜落差表
    gap_rows = []
    for slug, name, aliases in BRANDS:
        b = brands.get(slug)
        if not b: continue
        fdb = norm(b.get("first_deposit_bonus"))
        for site, r, bn in comp_rows(name, norm(b.get("competitor_listing"))):
            gap_rows.append(f'<tr><td data-l="平台">{esc(name)}</td><td data-l="排行榜">{esc(site)}</td><td data-l="榜上名次／分數">{esc(r)}</td><td data-l="榜上首儲優惠">{esc(bn) or "—"}</td><td data-l="官方站首儲宣稱">{esc(fdb["value"][:60]) if not is_na(fdb) else NA}</td></tr>')
    gap_html = ('<div class="t-scroll stack"><table class="stack"><thead><tr><th>平台</th><th>排行榜</th><th>榜上名次／分數</th><th>榜上首儲優惠</th><th>官方站首儲宣稱</th></tr></thead><tbody>' + "".join(gap_rows) + "</tbody></table></div>") if gap_rows else "<p>本次查證未能對應到第三方排行榜的具體寫法。</p>"
    tmpl = [name for slug, name, _ in BRANDS if slug in brands and all(k in norm(brands[slug].get("claimed_license"))["value"] for k in ("監督競猜牌照", "英屬維爾京"))]
    tmpl_li = (f'  <li><strong>多家宣傳站用同一段牌照文字。</strong>本次查證中，{ "、".join(tmpl) } 共 {len(tmpl)} 家的宣傳站頁尾都出現「馬爾他牌照(MGA)認證／英屬維爾京群島(BVI)認證／菲律賓(PAGCOR)監督競猜牌照」這組字樣，都沒有牌照編號。各家原文逐字列在它們的查證檔案頁，讀者可自行比對。</li>') if len(tmpl) >= 2 else ""
    qas = [
        ("這是娛樂城推薦排行榜嗎？", "不是。這一頁沒有名次、沒有星等、沒有「馬上玩」按鈕。平台的順序是它們在第三方排行榜出現的頻率，不是本站的評價。本站不推薦、也不反推薦任何平台。"),
        ("為什麼不給分數？", "分數需要實際註冊、儲值、出金的測試，本站沒有做這件事，也不打算用沒做過的事給分。能查證的是平台自己怎麼說、公開制度與紀錄怎麼說，所以只列這兩欄。"),
        ("哪一家娛樂城最安全？", "本站不回答這個問題。任何一家都可能在你出金時才出問題，比較穩的做法是：先到發照機構查牌照、只從確認過的官方入口進站、先小額出金一次確認流程、看到「保證金」「解凍金」要求立刻停手。"),
        ("「未查得」是什麼意思？", "本站在查證日期沒有找到可引用的公開來源。它不代表平台有問題，也不代表沒問題，只代表這一項你要自己再確認。"),
        ("平台宣稱有 PAGCOR 牌照，代表合法嗎？", "菲律賓已在 2025 年 10 月立法撤銷所有離岸博弈牌照，PAGCOR 也不再有權核發這類牌照，所以現在任何「持有 PAGCOR 牌照」的宣稱制度上已不成立。Curaçao 也已換成新制，舊子牌照全部失效。細節見牌照查真假頁。"),
        ("台灣玩線上娛樂城合法嗎？", "台灣沒有核發線上娛樂城牌照的制度，平台宣稱的牌照都是境外的；參與者在台灣仍有法律與財務風險，本站不提供法律意見，只提醒你自行評估。"),
        ("這張表多久更新一次？", "牌照制度與 165 查詢結果每季複查一次；平台條款在公告變更時更新。每一頁頁首都有查證日期，沒有日期的資訊不應視為當前有效。"),
        ("排行榜上的首儲優惠跟官方站寫的不一樣，該信哪個？", "以你實際註冊時官方站公告的條款為準。排行榜上的數字常是舊的或為了導流寫的，本頁第 5 節把兩邊並列，就是讓你看到落差。"),
    ]
    item_list = {"@type": "ItemList", "name": "12 家台灣線上娛樂城查證檔案", "itemListOrder": "https://schema.org/ItemListUnordered",
                 "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": name, "url": f"{SITE}/casinos/{slug}/"} for i, (slug, name, _) in enumerate(BRANDS) if slug in brands]}
    ld = '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@graph": [
        ORG_NODE,
        {"@type": "Article", "@id": url + "#article", "headline": title, "description": desc, "inLanguage": "zh-TW", "datePublished": date, "dateModified": date,
         "image": SITE + "/assets/og-image.png",
         "author": {"@id": SITE + "/#organization"}, "publisher": {"@id": SITE + "/#organization"}, "mainEntityOfPage": url},
        {"@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": 1, "name": "娛樂觀察站", "item": SITE + "/"}, {"@type": "ListItem", "position": 2, "name": "平台比較總表", "item": url}]},
        item_list, json.loads(faq_ld(qas))]}, ensure_ascii=False) + "</script>"
    body = f'''<article class="wrap-wide">
<h1>{esc(date[:4])} 台灣線上娛樂城比較總表：12 家常被排行榜列名的平台，官方宣稱 vs 公開紀錄</h1>
<div class="meta-row">
  <span class="badge neutral">查證資料庫 · 樞紐頁</span>
  <span>查證日期：{esc(date)}</span>
  <span>收錄：{len(rows)} 家</span>
  <span>{stamp("note", "無名次・無星等・無導購連結")}</span>
</div>
<div class="tldr">
  <div class="label">TL;DR</div>
  <p style="margin:0;">搜「娛樂城推薦」跳出來的排行榜，幾乎每一家都給五星、每一家後面都有「馬上玩」。本頁反過來做：挑出最常被那些排行榜列名的 12 家平台，把它們<strong>官方站自己宣稱</strong>的牌照、營運公司、最低儲值、出金條件，跟<strong>現行牌照制度、公司登記、165 公開查詢</strong>逐項並列。查得到寫查得到，查不到寫「未查得」，不補、不猜、不評分。其中豪神、包你發依官方條款是不能換現金的遊戲點數 APP，排行榜把它們跟現金版並列，本表的「類型」欄會分開標示。</p>
</div>
<nav class="jump-nav" aria-label="本頁快速跳轉">
  <div class="label">本頁快速跳轉</div>
  <ul>
    <li><a href="#sec-1">1. 為什麼排行榜不能直接信</a></li>
    <li><a href="#sec-2">2. 查證項目與判定方式</a></li>
    <li><a href="#sec-3">3. 總覽對照表</a></li>
    <li><a href="#sec-4">4. 各平台逐家摘要</a></li>
    <li><a href="#sec-5">5. 排行榜寫的 vs 官方寫的</a></li>
    <li><a href="#sec-6">6. 看完表之後自己再查三件事</a></li>
    <li><a href="#sec-7">7. 常見問題</a></li>
    <li><a href="#sec-8">8. 查證方法與來源</a></li>
    <li><a href="#sec-9">9. 更新紀錄</a></li>
  </ul>
</nav>
<h2 id="sec-1">1. 為什麼排行榜不能直接信</h2>
<ul>
  <li><strong>排行榜靠導流變現。</strong>本站對照的排行榜頁裡，168博評網 24 個、dupig03 4 個「馬上玩／前往」按鈕都連到帶代理前綴的平台入口（例如 nd0051.、dt3558.、ck5788. 這類子網域），gaulish 的 10 個則經短網址跳轉，都不是平台主網域。這代表排名頁跟平台之間有導流關係，分數不是獨立查證的結果。</li>
  <li><strong>同一家在不同榜上的分數對不起來。</strong>本頁第 5 節把各榜寫的名次、分數、首儲優惠照抄並列，你會看到同一家平台在 A 榜第一、在 B 榜沒進榜，優惠金額也各寫各的。</li>
{tmpl_li}
  <li><strong>「持有牌照」的宣稱多數已經過期。</strong>PAGCOR 離岸牌照制度在 2025 年 10 月被菲律賓立法撤銷，Curaçao 舊子牌照也在 2025 年全部失效，但排行榜跟平台官方站多數還掛著這些字。</li>
</ul>
<h2 id="sec-2">2. 查證項目與判定方式</h2>
<div class="t-scroll stack"><table class="stack">
<thead><tr><th>項目</th><th>怎麼查</th><th>結果怎麼讀</th></tr></thead>
<tbody>
<tr><td data-l="項目">官方網域</td><td data-l="怎麼查">實際打開搜尋結果與平台自述的每個候選網域，看是否互相指向、有無 APP 下載頁</td><td data-l="怎麼讀">{stamp("note","官方網域無法唯一確認")}＝同時有多個網域自稱官方，本站無法判定哪個是正主</td></tr>
<tr><td data-l="項目">牌照宣稱</td><td data-l="怎麼查">逐字抄官方站頁尾或「關於我們」的牌照文字，對照現行制度</td><td data-l="怎麼讀">{stamp("conflict","PAGCOR 離岸牌照制度已撤銷")}＝宣稱制度上已不成立；{stamp("note","Curaçao 已換新制")}＝需到 CGA 名單核對</td></tr>
<tr><td data-l="項目">營運公司</td><td data-l="怎麼查">官方站宣稱的公司名稱，到經濟部商工登記公示資料查詢</td><td data-l="怎麼讀">查得到＝公司存在，不等於它真的在營運該平台；{stamp("na","未查得")}＝官方沒寫或查不到</td></tr>
<tr><td data-l="項目">最低儲值／出金條件</td><td data-l="怎麼查">逐字抄官方站的儲值頁、出金說明、優惠條款</td><td data-l="怎麼讀">全部是平台自己說的，本站沒有實際儲值或出金測試</td></tr>
<tr><td data-l="項目">165 公開查詢</td><td data-l="怎麼查">到 165 全民防騙網與打詐儀表板查品牌名與候選網域</td><td data-l="怎麼讀">查無＝在查證日期沒有出現在公開清單，不代表安全；查有＝已有他人通報</td></tr>
</tbody></table></div>
<h2 id="sec-3">3. 總覽對照表</h2>
<p style="font-size:.9rem;color:var(--ink-soft);">順序＝在第三方排行榜出現的頻率，不是名次。手機上每家是一張卡，點平台名進完整檔案。</p>
<div class="t-scroll stack"><table class="matrix stack">
<thead><tr><th>平台</th><th>類型</th><th>官方網域</th><th>牌照宣稱</th><th>營運公司</th><th>最低儲值</th><th>出金宣稱</th><th>165 查詢</th></tr></thead>
<tbody>
{"".join(rows)}
</tbody></table></div>
<h2 id="sec-4">4. 各平台逐家摘要</h2>
{"".join(blocks)}
<h2 id="sec-5">5. 排行榜寫的 vs 官方寫的</h2>
<p>下面把幾份排在「娛樂城推薦」搜尋結果前面的排行榜頁，對每家平台寫的名次、分數與首儲優惠照抄下來，跟官方站自己的首儲宣稱並列。只做紀錄，不代表本站認同任何一方：</p>
{gap_html}
<h2 id="sec-6">6. 看完表之後自己再查三件事</h2>
<div class="internal-links">
  <div class="label">下一步</div>
  <ul style="margin:0;">
    <li><a href="/pages/license-check/">PAGCOR／Curaçao 牌照查真假</a> — 平台宣稱的牌照，到發照機構的公開名單查一次</li>
    <li><a href="/pages/tool-wagering-calculator/">流水／有效投注試算器</a> — 首儲優惠的流水倍數丟進去算，看要下注多少才能出金</li>
    <li><a href="/pages/fake-site-identification/">冒名詐騙站辨識</a> — 同一品牌好幾個網域時，怎麼判斷你點的是不是仿冒站</li>
  </ul>
</div>
<h2 id="sec-7">7. 常見問題</h2>
{faq_html(qas)}
<h2 id="sec-8">8. 查證方法與來源</h2>
<p>每家平台引用過的官方頁面、商工登記與 165 查詢結果，列在各自的查證檔案頁「查證方法與來源」段落。本站的收錄門檻、正反並陳原則與更正方式見<a href="/pages/about/">關於本站與查證方法</a>。制度性事實的來源（RA 12312、Curaçao LOK）見<a href="/pages/license-check/">牌照查真假</a>。</p>
<h2 id="sec-9">9. 更新紀錄</h2>
<ul>
  <li>{esc(date)} 首次發布，收錄 {len(rows)} 家。下次複查：{esc((datetime.date.fromisoformat(date) + datetime.timedelta(days=90)).isoformat())} 前。</li>
</ul>
<div class="disclaimer-box">
  本頁只並列平台官方宣稱與公開紀錄，不構成任何推薦、反推薦或法律意見；本站沒有實際註冊、儲值或出金測試。台灣現行法律未開放線上博弈，參與前請自行評估法律與財務風險。本站不接受業配、不代收佣金、不放推薦連結。
</div>
</article>
'''
    return head(title, desc, url, ld) + body + FOOT

def build_sitemap(out, date, brand_slugs):
    static = ["/", "/casino-comparison/", "/pages/guide-withdrawal-denial-diagnosis/", "/pages/tool-wagering-calculator/", "/pages/license-check/", "/pages/dispute-database/", "/pages/bank-alert-account-recovery/", "/pages/report-sop/", "/pages/fake-site-identification/", "/pages/about/"]
    urls = static + [f"/casinos/{s}/" for s in brand_slugs]
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(f"  <url><loc>{SITE}{u}</loc><lastmod>{date}</lastmod></url>\n" for u in urls) + "</urlset>\n"
    open(os.path.join(out, "sitemap.xml"), "w", encoding="utf-8").write(xml)
    return len(urls)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--brands-dir", required=True); ap.add_argument("--out-dir", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); ap.add_argument("--date", default=datetime.date.today().isoformat())
    a = ap.parse_args()
    brands, metas = {}, {}
    for f in glob.glob(os.path.join(a.brands_dir, "*.json")):
        slug = os.path.splitext(os.path.basename(f))[0]
        if slug.startswith("_"): continue
        try: d = json.load(open(f, encoding="utf-8"))
        except Exception as e: print("跳過（JSON 壞）", f, e); continue
        metas[slug] = {"warnings": d.get("warnings") or [], "unresolved": d.get("unresolved") or []} if isinstance(d, dict) else {}
        brands[slug] = d["fields"] if isinstance(d, dict) and "fields" in d else d
    info = {}
    for slug, name, aliases in BRANDS:
        if slug not in brands: print("缺", slug); continue
        html_, unv = build_brand_page(slug, name, aliases, brands[slug], a.date, metas.get(slug))
        d = os.path.join(a.out_dir, "casinos", slug); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "index.html"), "w", encoding="utf-8").write(html_); info[slug] = unv
        print(f"寫入 casinos/{slug}/  未查得 {len(unv)} 項：{'、'.join(unv) or '無'}")
    d = os.path.join(a.out_dir, "casino-comparison"); os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "index.html"), "w", encoding="utf-8").write(build_hub(brands, a.date, info))
    n = build_sitemap(a.out_dir, a.date, [s for s, _, _ in BRANDS if s in brands])
    print(f"寫入 casino-comparison/ 與 sitemap.xml（{n} 個 URL）")

if __name__ == "__main__": main()
