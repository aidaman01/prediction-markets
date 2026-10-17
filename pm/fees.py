"""Official taker fee schedules. Decimal arithmetic so published examples are reproduced to the cent.

Kalshi: kalshi.com/fee-schedule and docs.kalshi.com/getting_started/fee_rounding.
  model fee = multiplier * C * P * (1 - P), multiplier 0.07 for most markets; trade fee is the model fee rounded
  up to $0.000001; a non-direct member's balance moves on a $0.01 grid, so total cash out is rounded up to the cent.
Polymarket: docs.polymarket.com/trading/fees.
  fee = C * rate * (P * (1 - P)) ** exponent, taker only, rounded to 5 decimals (anything below 0.00001 is zero).
"""
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal

D = Decimal
CENT, MICRO, PM_TICK = D("0.01"), D("0.000001"), D("0.00001")


def _d(x):
    return x if isinstance(x, Decimal) else D(str(x))


def kalshi_trade_fee(contracts, price, multiplier="0.07"):
    """Kalshi trade fee in dollars for one fill: model fee rounded up to $0.000001."""
    c, p = _d(contracts), _d(price)
    return (_d(multiplier) * c * p * (1 - p)).quantize(MICRO, rounding=ROUND_CEILING)


def kalshi_buy_cash(fills, multiplier="0.07", grid=CENT):
    """Total cash a non-direct member pays to buy along `fills` [(price, contracts), ...] as one order.

    The fee accumulator makes an order's total converge to a single equivalent fill: sum of trade fees plus
    notional, rounded up to the balance grid. Returns (cash_out, fee) with fee = cash_out - notional."""
    notional = sum(_d(p) * _d(c) for p, c in fills)
    fee = sum(kalshi_trade_fee(c, p, multiplier) for p, c in fills)
    cash = (notional + fee).quantize(_d(grid), rounding=ROUND_CEILING)
    return cash, cash - notional


def kalshi_fill_rounding(revenue, model_fee, grid=CENT):
    """The docs' per-fill mechanics: (trade_fee, aligned_change, rounding_fee). revenue is signed (buyer < 0)."""
    trade_fee = _d(model_fee).quantize(MICRO, rounding=ROUND_CEILING)
    raw = _d(revenue) - trade_fee
    aligned = (raw / _d(grid)).to_integral_value(rounding="ROUND_FLOOR") * _d(grid)
    return trade_fee, aligned, raw - aligned


def polymarket_fee(shares, price, rate, exponent=1):
    """Polymarket taker fee in USDC for one fill."""
    c, p, r = _d(shares), _d(price), _d(rate)
    if r == 0:
        return D(0)
    core = p * (1 - p)
    core = core if exponent == 1 else _d(float(core) ** float(exponent))
    return (c * r * core).quantize(PM_TICK, rounding=ROUND_DOWN)


def polymarket_buy_cash(fills, rate, exponent=1):
    """Total USDC paid to buy along `fills` [(price, shares), ...]; fee charged per fill."""
    notional = sum(_d(p) * _d(c) for p, c in fills)
    fee = sum(polymarket_fee(c, p, rate, exponent) for p, c in fills)
    return notional + fee, fee
