import sqlite3
import sys

def get_financials(ticker):
    con = sqlite3.connect('data/stocks.db')
    rows = con.execute(
        "select term, revenue, operating_income, capex from quarterly_financials "
        "where ticker=? order by term", (ticker,)
    ).fetchall()
    con.close()
    return rows

if __name__ == '__main__':
    ticker = sys.argv[1]
    rows = get_financials(ticker)
    prev_rev = None
    print(f"{'term':8} {'revenue':>12} {'rev_qoq':>8} {'op_margin':>10} {'capex':>10} {'capex/rev':>10}")
    for term, rev, opinc, capex in rows:
        rev_qoq = f"{(rev/prev_rev-1)*100:+.1f}%" if prev_rev and rev is not None else ""
        opm = f"{(opinc/rev*100):.1f}%" if rev and opinc is not None else ""
        cap_ratio = f"{(-capex/rev*100):.1f}%" if rev and capex is not None else ""
        rev_disp = f"{rev/1e6:,.0f}" if rev is not None else ""
        capex_disp = f"{-capex/1e6:,.0f}" if capex is not None else ""
        print(f"{term:8} {rev_disp:>12} {rev_qoq:>8} {opm:>10} {capex_disp:>10} {cap_ratio:>10}")
        if rev is not None:
            prev_rev = rev
