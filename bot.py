import json
from datetime import datetime, timezone
from pathlib import Path
import requests

STATE_FILE = Path("state.json")

STARTING_BALANCE = 10000.0

SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"
SEARCH_WORDS = ["meme", "pepe", "doge", "cat", "pump"]

MIN_LIQUIDITY_USD = 10000
MIN_VOLUME_USD = 5000
MAX_CANDIDATES = 10

MAX_OPEN_POSITIONS = 2
RISK_PER_TRADE_PCT = 1.0

STOP_LOSS_PCT = 8.0
TAKE_PROFIT_PCT = 16.0

MAX_HOLD_TICKS = 20


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def default_state():
    return {
        "updated_at": "not_started",
        "mode": "PAPER",
        "starting_balance": STARTING_BALANCE,
        "cash": STARTING_BALANCE,
        "equity": STARTING_BALANCE,
        "pnl": 0,
        "pnl_pct": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0,
        "max_equity": STARTING_BALANCE,
        "max_drawdown_pct": 0,
        "consecutive_losses": 0,
        "cooldown": False,
        "open_positions": [],
        "candidates": [],
        "trades": [],
        "tick": 0,
        "risk": {
            "max_risk_per_trade_pct": RISK_PER_TRADE_PCT,
            "max_open_positions": MAX_OPEN_POSITIONS,
            "stop_loss_pct": STOP_LOSS_PCT,
            "take_profit_pct": TAKE_PROFIT_PCT,
            "max_hold_ticks": MAX_HOLD_TICKS
        }
    }


def load_state():
    if not STATE_FILE.exists():
        return default_state()

    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)

        base = default_state()

        for key, value in base.items():
            if key not in state:
                state[key] = value

        return state

    except Exception:
        return default_state()


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )


def search_market(keyword):
    try:
        response = requests.get(
            SEARCH_URL,
            params={"q": keyword},
            timeout=15,
            headers={
                "User-Agent": "meme-ai-trader-paper/1.0"
            }
        )

        response.raise_for_status()

        return response.json().get("pairs", [])

    except Exception as e:
        print(
            f"API error [{keyword}]: {e}"
        )
        return []


def collect_candidates():

    unique = {}

    for keyword in SEARCH_WORDS:

        print(
            f"Searching: {keyword}"
        )

        for pair in search_market(keyword):

            liquidity = pair.get(
                "liquidity"
            ) or {}

            volume = pair.get(
                "volume"
            ) or {}

            price_change = pair.get(
                "priceChange"
            ) or {}

            base = pair.get(
                "baseToken"
            ) or {}

            try:
                liquidity_usd = float(
                    liquidity.get("usd") or 0
                )

                volume_24h = float(
                    volume.get("h24") or 0
                )

                price_usd = float(
                    pair.get("priceUsd") or 0
                )

                change_24h = float(
                    price_change.get("h24") or 0
                )

            except (
                TypeError,
                ValueError
            ):
                continue

            if liquidity_usd < MIN_LIQUIDITY_USD:
                continue

            if volume_24h < MIN_VOLUME_USD:
                continue

            if price_usd <= 0:
                continue

            pair_address = pair.get(
                "pairAddress"
            )

            if not pair_address:
                continue

            chain = pair.get(
                "chainId"
            )

            symbol = base.get(
                "symbol",
                "UNKNOWN"
            )

            # 同じ銘柄を複数DEXから拾っても、
            # 銘柄単位で代表ペアを1つだけ残す
            token_key = (
                f"{chain}:"
                f"{symbol.upper()}"
            )

            candidate = {
                "chain": chain,
                "dex": pair.get("dexId"),
                "pair_address": pair_address,
                "symbol": symbol,
                "name": base.get(
                    "name",
                    "UNKNOWN"
                ),
                "price": price_usd,
                "liquidity_usd": liquidity_usd,
                "volume_24h_usd": volume_24h,
                "price_change_24h_pct": change_24h,
                "url": pair.get("url")
            }

            # より流動性が高いペアを代表として採用
            existing = unique.get(
                token_key
            )

            if (
                existing is None
                or candidate["liquidity_usd"]
                > existing["liquidity_usd"]
            ):
                unique[token_key] = candidate

    candidates = list(
        unique.values()
    )

    candidates.sort(
        key=lambda x: (
            x["volume_24h_usd"],
            x["liquidity_usd"]
        ),
        reverse=True
    )

    return candidates[:MAX_CANDIDATES]


def calculate_score(candidate):

    score = 0

    liquidity = candidate[
        "liquidity_usd"
    ]

    volume = candidate[
        "volume_24h_usd"
    ]

    change = candidate[
        "price_change_24h_pct"
    ]

    if liquidity >= 10000:
        score += 20

    if liquidity >= 50000:
        score += 10

    if volume >= 10000:
        score += 20

    if volume >= 50000:
        score += 10

    if 0 < change <= 20:
        score += 20

    elif change > 20:
        score += 5

    if change < -20:
        score -= 10

    return max(
        0,
        min(100, score)
    )


def calculate_equity(state):

    equity = state["cash"]

    for position in state[
        "open_positions"
    ]:

        current_price = position.get(
            "current_price",
            position["entry_price"]
        )

        equity += (
            position["quantity"]
            * current_price
        )

    return equity


def already_holding_symbol(
    state,
    symbol
):

    symbol = symbol.upper()

    for position in state[
        "open_positions"
    ]:

        if (
            position["symbol"]
            .upper()
            == symbol
        ):
            return True

    return False


def open_position(
    state,
    candidate
):

    if len(
        state["open_positions"]
    ) >= MAX_OPEN_POSITIONS:
        return False

    if candidate["score"] < 60:
        return False

    symbol = candidate[
        "symbol"
    ]

    # 同一銘柄は1ポジションだけ
    if already_holding_symbol(
        state,
        symbol
    ):
        print(
            f"SKIP {symbol}: "
            "already holding"
        )

        return False

    price = candidate["price"]

    if price <= 0:
        return False

    equity = calculate_equity(
        state
    )

    risk_amount = (
        equity
        * RISK_PER_TRADE_PCT
        / 100
    )

    stop_distance = (
        STOP_LOSS_PCT / 100
    )

    position_value = (
        risk_amount
        / stop_distance
    )

    # 1ポジション最大25%
    position_value = min(
        position_value,
        state["cash"] * 0.25
    )

    if position_value <= 0:
        return False

    quantity = (
        position_value / price
    )

    position = {
        "pair_address":
            candidate[
                "pair_address"
            ],

        "symbol":
            candidate[
                "symbol"
            ],

        "name":
            candidate[
                "name"
            ],

        "entry_price":
            price,

        "current_price":
            price,

        "quantity":
            quantity,

        "position_value":
            position_value,

        "entry_tick":
            state["tick"],

        "score_at_entry":
            candidate["score"],

        "stop_loss_price":
            price
            * (
                1
                - STOP_LOSS_PCT / 100
            ),

        "take_profit_price":
            price
            * (
                1
                + TAKE_PROFIT_PCT / 100
            ),

        "url":
            candidate.get("url")
    }

    state["cash"] -= (
        position_value
    )

    state[
        "open_positions"
    ].append(position)

    print(
        f"PAPER BUY "
        f"{symbol} "
        f"${price} "
        f"value="
        f"${position_value:.2f} "
        f"score="
        f"{candidate['score']}"
    )

    return True


def close_position(
    state,
    position,
    exit_price,
    reason
):

    entry_price = position[
        "entry_price"
    ]

    quantity = position[
        "quantity"
    ]

    pnl = (
        exit_price
        - entry_price
    ) * quantity

    exit_value = (
        exit_price
        * quantity
    )

    state["cash"] += (
        exit_value
    )

    trade = {
        "symbol":
            position["symbol"],

        "name":
            position["name"],

        "entry_price":
            entry_price,

        "exit_price":
            exit_price,

        "quantity":
            quantity,

        "position_value":
            position[
                "position_value"
            ],

        "pnl":
            pnl,

        "reason":
            reason,

        "entry_tick":
            position[
                "entry_tick"
            ],

        "exit_tick":
            state["tick"],

        "closed_at":
            now_iso(),

        "url":
            position.get("url")
    }

    state[
        "trades"
    ].append(trade)

    # 最大100件
    state["trades"] = (
        state["trades"][-100:]
    )

    if pnl > 0:

        state["wins"] += 1

        state[
            "consecutive_losses"
        ] = 0

    else:

        state["losses"] += 1

        state[
            "consecutive_losses"
        ] += 1

    total = (
        state["wins"]
        + state["losses"]
    )

    if total > 0:

        state["win_rate"] = (
            state["wins"]
            / total
        ) * 100

    print(
        f"PAPER SELL "
        f"{position['symbol']} "
        f"${exit_price} "
        f"PnL="
        f"${pnl:.2f} "
        f"reason="
        f"{reason}"
    )


def update_positions(
    state,
    price_map
):

    remaining = []

    for position in state[
        "open_positions"
    ]:

        pair_address = position[
            "pair_address"
        ]

        current_price = price_map.get(
            pair_address
        )

        # 新しい代表ペアに変わった場合、
        # 同一symbolの価格も探す
        if current_price is None:

            for candidate in (
                state["candidates"]
            ):

                if (
                    candidate["symbol"]
                    .upper()
                    ==
                    position[
                        "symbol"
                    ].upper()
                ):

                    current_price = (
                        candidate[
                            "price"
                        ]
                    )

                    break

        if current_price is None:

            remaining.append(
                position
            )

            continue

        position[
            "current_price"
        ] = current_price

        hold_ticks = (
            state["tick"]
            - position[
                "entry_tick"
            ]
        )

        if (
            current_price
            <= position[
                "stop_loss_price"
            ]
        ):

            close_position(
                state,
                position,
                current_price,
                "STOP_LOSS"
            )

        elif (
            current_price
            >= position[
                "take_profit_price"
            ]
        ):

            close_position(
                state,
                position,
                current_price,
                "TAKE_PROFIT"
            )

        elif (
            hold_ticks
            >= MAX_HOLD_TICKS
        ):

            close_position(
                state,
                position,
                current_price,
                "MAX_HOLD"
            )

        else:

            remaining.append(
                position
            )

    state[
        "open_positions"
    ] = remaining


def update_risk_metrics(state):

    equity = calculate_equity(
        state
    )

    state["equity"] = equity

    if equity > state[
        "max_equity"
    ]:

        state[
            "max_equity"
        ] = equity

    if state[
        "max_equity"
    ] > 0:

        drawdown = (
            (
                state[
                    "max_equity"
                ]
                - equity
            )
            / state[
                "max_equity"
            ]
        ) * 100

        state[
            "max_drawdown_pct"
        ] = max(
            state[
                "max_drawdown_pct"
            ],
            drawdown
        )

    state["pnl"] = (
        equity
        - STARTING_BALANCE
    )

    state["pnl_pct"] = (
        state["pnl"]
        / STARTING_BALANCE
    ) * 100

    state[
        "cooldown"
    ] = (
        state[
            "consecutive_losses"
        ] >= 3
    )


def main():

    print(
        "Meme AI Trader"
        " - PAPER MODE"
        " - REAL MARKET DATA"
        " - NO LIVE TRADING"
    )

    state = load_state()

    state["tick"] += 1

    state[
        "updated_at"
    ] = now_iso()

    state["mode"] = "PAPER"

    candidates = (
        collect_candidates()
    )

    for candidate in candidates:

        candidate[
            "score"
        ] = calculate_score(
            candidate
        )

    state[
        "candidates"
    ] = candidates

    price_map = {
        candidate[
            "pair_address"
        ]: candidate[
            "price"
        ]
        for candidate
        in candidates
    }

    # 既存ポジション更新
    update_positions(
        state,
        price_map
    )

    update_risk_metrics(
        state
    )

    # 新規エントリー
    if not state[
        "cooldown"
    ]:

        sorted_candidates = sorted(
            candidates,
            key=lambda x:
                x["score"],
            reverse=True
        )

        for candidate in (
            sorted_candidates
        ):

            if len(
                state[
                    "open_positions"
                ]
            ) >= MAX_OPEN_POSITIONS:

                break

            open_position(
                state,
                candidate
            )

    update_risk_metrics(
        state
    )

    save_state(
        state
    )

    print(
        f"Tick: "
        f"{state['tick']}"
    )

    print(
        f"Candidates: "
        f"{len(candidates)}"
    )

    print(
        f"Open positions: "
        f"{len(state['open_positions'])}"
    )

    print(
        f"Trades: "
        f"{len(state['trades'])}"
    )

    print(
        f"Cash: "
        f"${state['cash']:.2f}"
    )

    print(
        f"Equity: "
        f"${state['equity']:.2f}"
    )

    print(
        f"P&L: "
        f"${state['pnl']:.2f} "
        f"({state['pnl_pct']:.2f}%)"
    )

    print(
        f"Win rate: "
        f"{state['win_rate']:.2f}%"
    )

    print(
        f"Max drawdown: "
        f"{state['max_drawdown_pct']:.2f}%"
    )

    print(
        "state.json updated."
    )


if __name__ == "__main__":
    main()
