import sqlite3
import sys

THRESH = 0.30

def get_prices(ticker):
    con = sqlite3.connect('data/prices.db')
    rows = con.execute(
        "select date, adj_close from daily_prices where ticker=? order by date", (ticker,)
    ).fetchall()
    con.close()
    return rows

def zigzag(rows, thresh=THRESH):
    """Return list of (date, price, 'H' or 'L') turning points using % retracement zigzag."""
    if not rows:
        return []
    pivots = []
    # initial state
    last_pivot_date, last_pivot_price = rows[0]
    direction = None  # 'up' or 'down' since last pivot
    extreme_date, extreme_price = last_pivot_date, last_pivot_price

    for date, price in rows[1:]:
        if direction is None:
            if price >= last_pivot_price * (1 + thresh):
                direction = 'up'
                extreme_date, extreme_price = date, price
            elif price <= last_pivot_price * (1 - thresh):
                direction = 'down'
                extreme_date, extreme_price = date, price
            else:
                if price > extreme_price:
                    extreme_date, extreme_price = date, price
                elif price < extreme_price:
                    extreme_date, extreme_price = date, price
            continue

        if direction == 'up':
            if price > extreme_price:
                extreme_date, extreme_price = date, price
            elif price <= extreme_price * (1 - thresh):
                pivots.append((extreme_date, extreme_price, 'H'))
                direction = 'down'
                last_pivot_date, last_pivot_price = extreme_date, extreme_price
                extreme_date, extreme_price = date, price
        else:  # direction == 'down'
            if price < extreme_price:
                extreme_date, extreme_price = date, price
            elif price >= extreme_price * (1 + thresh):
                pivots.append((extreme_date, extreme_price, 'L'))
                direction = 'up'
                last_pivot_date, last_pivot_price = extreme_date, extreme_price
                extreme_date, extreme_price = date, price

    # append final extreme as a pivot too
    pivots.append((extreme_date, extreme_price, 'H' if direction == 'up' else 'L'))
    return pivots

if __name__ == '__main__':
    ticker = sys.argv[1]
    rows = get_prices(ticker)
    print(f"{ticker}: {len(rows)} price rows, {rows[0][0]} ~ {rows[-1][0]}")
    pivots = zigzag(rows)
    print(f"{len(pivots)} turning points (thresh={THRESH})")
    for d, p, k in pivots:
        print(f"  {d}  {k}  {p:.2f}")
