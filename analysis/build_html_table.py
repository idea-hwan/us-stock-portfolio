import pandas as pd

df = pd.read_csv('../data/stock_universe.csv')

def ret_class(val):
    if not isinstance(val, str) or val == '':
        return ''
    v = float(val.replace('%','').replace('+',''))
    if v >= 20:  return 'ret-high-up'
    if v >= 5:   return 'ret-up'
    if v > 0:    return 'ret-low-up'
    if v >= -5:  return 'ret-low-dn'
    if v >= -20: return 'ret-dn'
    return 'ret-high-dn'

def pe_class(val):
    if val == '' or pd.isna(val): return ''
    try:
        v = float(val)
        if v < 0:   return 'pe-neg'
        if v < 15:  return 'pe-cheap'
        if v < 30:  return 'pe-mid'
        return 'pe-exp'
    except: return ''

rows_html = ''
for _, r in df.iterrows():
    ret20  = r['ret_20d']  if pd.notna(r['ret_20d'])  else ''
    ret60  = r['ret_60d']  if pd.notna(r['ret_60d'])  else ''
    ret180 = r['ret_180d'] if pd.notna(r['ret_180d']) else ''
    tpe    = str(r['trailing_pe']) if pd.notna(r['trailing_pe']) and r['trailing_pe'] != '' else ''
    fpe    = str(r['forward_pe'])  if pd.notna(r['forward_pe'])  and r['forward_pe']  != '' else ''
    biz    = str(r['biz_model'])[:120] + '…' if pd.notna(r['biz_model']) and len(str(r['biz_model'])) > 120 else (r['biz_model'] if pd.notna(r['biz_model']) else '')

    rows_html += f"""
    <tr>
      <td class="ticker">{r['ticker']}</td>
      <td>{r['company']}</td>
      <td><span class="badge sector-{r['sector'].replace(' ','_').replace('&','').lower()[:12]}">{r['sector']}</span></td>
      <td>{r['industry']}</td>
      <td>{r['country']}</td>
      <td class="num">{r['market_cap_str']}</td>
      <td class="num {ret_class(ret20)}">{ret20}</td>
      <td class="num {ret_class(ret60)}">{ret60}</td>
      <td class="num {ret_class(ret180)}">{ret180}</td>
      <td class="num {pe_class(tpe)}">{tpe}</td>
      <td class="num {pe_class(fpe)}">{fpe}</td>
      <td class="biz">{biz}</td>
    </tr>"""

html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>S&amp;P 500 Stock Universe</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/tablesort/5.3.0/tablesort.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/tablesort/5.3.0/sorts/tablesort.number.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #0f1117; color: #e0e0e0; padding: 24px; font-size: 13px; }}
  h1 {{ font-size: 20px; font-weight: 600; margin-bottom: 6px; color: #fff; }}
  .subtitle {{ color: #888; margin-bottom: 20px; font-size: 12px; }}

  /* 필터 바 */
  .filter-bar {{ display: flex; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; align-items: center; }}
  .filter-bar input, .filter-bar select {{
    background: #1e2130; border: 1px solid #333; color: #ddd;
    padding: 6px 10px; border-radius: 6px; font-size: 12px; outline: none; }}
  .filter-bar input {{ width: 200px; }}
  .filter-bar label {{ color: #888; font-size: 12px; }}
  .count {{ color: #888; font-size: 12px; margin-left: auto; }}

  /* 테이블 */
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{
    background: #1a1d2e; color: #aaa; font-weight: 500;
    padding: 8px 10px; text-align: left; white-space: nowrap;
    border-bottom: 1px solid #2a2d3e; cursor: pointer; user-select: none;
    position: sticky; top: 0; z-index: 10; font-size: 11px; }}
  thead th:hover {{ color: #fff; background: #22263a; }}
  thead th[aria-sort="ascending"]::after  {{ content: " ▲"; color: #7c8cf8; }}
  thead th[aria-sort="descending"]::after {{ content: " ▼"; color: #7c8cf8; }}

  tbody tr {{ border-bottom: 1px solid #1a1d2e; transition: background .1s; }}
  tbody tr:hover {{ background: #1a1d2e; }}
  td {{ padding: 7px 10px; vertical-align: middle; }}

  .ticker {{ font-weight: 700; color: #7c8cf8; font-family: monospace; font-size: 13px; }}
  .num {{ text-align: right; font-family: monospace; white-space: nowrap; }}
  .biz {{ color: #888; font-size: 11px; max-width: 260px; line-height: 1.4; }}

  /* 수익률 색상 */
  .ret-high-up {{ color: #00e676; font-weight: 700; }}
  .ret-up      {{ color: #69f0ae; }}
  .ret-low-up  {{ color: #b9f6ca; }}
  .ret-low-dn  {{ color: #ffcdd2; }}
  .ret-dn      {{ color: #ef9a9a; }}
  .ret-high-dn {{ color: #f44336; font-weight: 700; }}

  /* PER 색상 */
  .pe-cheap {{ color: #69f0ae; }}
  .pe-mid   {{ color: #fff9c4; }}
  .pe-exp   {{ color: #ffcc80; }}
  .pe-neg   {{ color: #78909c; }}

  /* 섹터 배지 */
  .badge {{ padding: 2px 7px; border-radius: 10px; font-size: 10px; font-weight: 500; white-space: nowrap; }}
  .sector-technology      {{ background:#1a237e; color:#82b1ff; }}
  .sector-financial       {{ background:#1b5e20; color:#b9f6ca; }}
  .sector-consumer_cy     {{ background:#4a148c; color:#ea80fc; }}
  .sector-industrials     {{ background:#e65100; color:#ffe0b2; }}
  .sector-communication   {{ background:#006064; color:#84ffff; }}
  .sector-healthcare      {{ background:#880e4f; color:#ff80ab; }}
  .sector-energy          {{ background:#3e2723; color:#ffccbc; }}
  .sector-basic_materials {{ background:#37474f; color:#cfd8dc; }}
  .sector-utilities       {{ background:#1a237e; color:#c5cae9; }}
  .sector-consumer_de     {{ background:#1b5e20; color:#ccff90; }}
  .sector-real_estate     {{ background:#4e342e; color:#d7ccc8; }}

  /* 스크롤 래퍼 */
  .table-wrap {{ overflow-x: auto; border-radius: 8px; border: 1px solid #2a2d3e; }}
</style>
</head>
<body>
<h1>S&amp;P 500 Stock Universe</h1>
<p class="subtitle">총 {len(df)}개 개별 주식 · 시가총액 순 · 기준일 2026-05-27</p>

<div class="filter-bar">
  <input type="text" id="searchInput" placeholder="🔍  티커 / 회사명 / 섹터 검색…" oninput="filterTable()">
  <label>섹터</label>
  <select id="sectorFilter" onchange="filterTable()">
    <option value="">전체</option>
    {''.join(f'<option>{s}</option>' for s in sorted(df['sector'].dropna().unique()))}
  </select>
  <label>국가</label>
  <select id="countryFilter" onchange="filterTable()">
    <option value="">전체</option>
    {''.join(f'<option>{c}</option>' for c in sorted(df['country'].dropna().unique()))}
  </select>
  <span class="count" id="rowCount">{len(df)}개 종목</span>
</div>

<div class="table-wrap">
<table id="mainTable">
<thead>
  <tr>
    <th>티커</th>
    <th>회사명</th>
    <th>섹터</th>
    <th>산업</th>
    <th>국가</th>
    <th data-sort-method="number">시총</th>
    <th data-sort-method="number">20일</th>
    <th data-sort-method="number">60일</th>
    <th data-sort-method="number">180일</th>
    <th data-sort-method="number">PER(T)</th>
    <th data-sort-method="number">PER(F)</th>
    <th>비즈니스</th>
  </tr>
</thead>
<tbody id="tableBody">
{rows_html}
</tbody>
</table>
</div>

<script>
new Tablesort(document.getElementById('mainTable'));

function filterTable() {{
  const q       = document.getElementById('searchInput').value.toLowerCase();
  const sector  = document.getElementById('sectorFilter').value.toLowerCase();
  const country = document.getElementById('countryFilter').value.toLowerCase();
  const rows    = document.querySelectorAll('#tableBody tr');
  let count = 0;
  rows.forEach(row => {{
    const text    = row.textContent.toLowerCase();
    const secCell = row.cells[2].textContent.toLowerCase();
    const cntCell = row.cells[4].textContent.toLowerCase();
    const show = (!q || text.includes(q)) &&
                 (!sector  || secCell.includes(sector)) &&
                 (!country || cntCell.includes(country));
    row.style.display = show ? '' : 'none';
    if (show) count++;
  }});
  document.getElementById('rowCount').textContent = count + '개 종목';
}}
</script>
</body>
</html>"""

with open('stock_universe.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("✅ stock_universe.html 저장 완료")
