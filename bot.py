import json
from datetime import datetime, timezone
from pathlib import Path

import requests


# ============================================================
# Meme AI Trader v2
# PAPER TRADING ONLY
# ============================================================

STATE_FILE = Path("state.json")

STARTING_BALANCE = 10000.0

SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"

SEARCH_WORDS = [
    "meme",
    "pepe",
    "doge",
    "cat",
    "pump",
]

# ------------------------------------------------------------
# Market filters
# ------------------------------------------------------------

MIN_LIQUIDITY_USD = 100000
MIN_VOLUME_USD = 25000

# 24hでこれ以上上がっている銘柄は
# 急騰後の飛び乗りを避けるため除外
MAX_ENTRY_CHANGE_24H_PCT = 30.0

MAX_CANDIDATES = 10


# ------------------------------------------------------------
# Position / risk
# ------------------------------------------------------------

MAX_OPEN_POSITIONS = 2

RISK_PER_TRADE_PCT = 1.0

STOP_LOSS_PCT = 8.0
TAKE_PROFIT_PCT = 16.0

MAX_HOLD_TICKS = 20

# +5%到達後、建値までストップを引き上げる
BREAKEVEN_TRIGGER_PCT = 5.0

# +8%到達後、最高値から4%下にトレーリングストップ
TRAILING_TRIGGER_PCT = 8.0
TRAILING_STOP_PCT = 4.0

# 保有中のスコアがここまで落ちたら撤退
EXIT_SCORE_THRESHOLD = 45

# 新規エントリー最低スコア
ENTRY_SCORE_THRESHOLD = 70


# ============================================================
# Utility
# ============================================================

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

        "equity_history": [],

        "tick": 0,

        "risk": {
            "max_risk_per_trade_pct":
                RISK_PER_TRADE_PCT,

            "max_open_positions":
                MAX_OPEN_POSITIONS,

            "stop_loss_pct":
                STOP_LOSS_PCT,

            "take_profit_pct":
                TAKE_PROFIT_PCT,

            "max_hold_ticks":
                MAX_HOLD_TICKS,

            "breakeven_trigger_pct":
                BREAKEVEN_TRIGGER_PCT,

            "trailing_trigger_pct":
                TRAILING_TRIGGER_PCT,

            "trailing_stop_pct":
                TRAILING_STOP_PCT,

            "entry_score_threshold":
                ENTRY_SCORE_THRESHOLD,

            "exit_score_threshold":
                EXIT_SCORE_THRESHOLD,
        }
    }


def load_state():

    if not STATE_FILE.exists():
        return default_state()

    try:

        with open(
            STATE_FILE,
            encoding="utf-8"
        ) as f:

            state = json.load(f)

        base = default_state()

        for key, value in base.items():

            if key not in state:
                state[key] = value

        # v1からの移行
        if "equity_history" not in state:
            state["equity_history"] = []

        return state

    except Exception as e:

        print(
            f"State load error: {e}"
        )

        return default_state()


def save_state(state):

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# Market data
# ============================================================

def search_market(keyword):

    try:

        response = requests.get(
            SEARCH_URL,
            params={
                "q": keyword
            },
            timeout=15,
            headers={
                "User-Agent":
                    "meme-ai-trader-paper/2.0"
            }
        )

        response.raise_for_status()

        return response.json().get(
            "pairs",
            []
        )

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

        pairs = search_market(
            keyword
        )

        for pair in pairs:

            liquidity = (
                pair.get("liquidity")
                or {}
            )

            volume = (
                pair.get("volume")
                or {}
            )

            price_change = (
                pair.get("priceChange")
                or {}
            )

            base = (
                pair.get("baseToken")
                or {}
            )

            try:

                liquidity_usd = float(
                    liquidity.get("usd")
                    or 0
                )

                volume_24h = float(
                    volume.get("h24")
                    or 0
                )

                price_usd = float(
                    pair.get("priceUsd")
                    or 0
                )

                change_24h = float(
                    price_change.get("h24")
                    or 0
                )

            except (
                TypeError,
                ValueError
            ):

                continue

            # ------------------------------------------------
            # Basic filters
            # ------------------------------------------------

            if (
                liquidity_usd
                < MIN_LIQUIDITY_USD
            ):
                continue

            if (
                volume_24h
                < MIN_VOLUME_USD
            ):
                continue

            if price_usd <= 0:
                continue

            if (
                change_24h
                > MAX_ENTRY_CHANGE_24H_PCT
            ):
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

            token_address = base.get(
                "address"
            )

            if not token_address:
                continue

            # ------------------------------------------------
            # IMPORTANT:
            # tickerではなくtoken addressで識別
            # ------------------------------------------------

            token_key = (
                f"{chain}:"
                f"{token_address.lower()}"
            )

            candidate = {

                "chain":
                    chain,

                "dex":
                    pair.get("dexId"),

                "pair_address":
                    pair_address,

                "token_address":
                    token_address,

                "symbol":
                    symbol,

                "name":
                    base.get(
                        "name",
                        "UNKNOWN"
                    ),

                "price":
                    price_usd,

                "liquidity_usd":
                    liquidity_usd,

                "volume_24h_usd":
                    volume_24h,

                "price_change_24h_pct":
                    change_24h,

                "url":
                    pair.get("url"),
            }

            existing = unique.get(
                token_key
            )

            # 同じtokenなら
            # liquidityの高いpairを採用
            if (
                existing is None
                or
                candidate[
                    "liquidity_usd"
                ]
                >
                existing[
                    "liquidity_usd"
                ]
            ):

                unique[
                    token_key
                ] = candidate

    candidates = list(
        unique.values()
    )

    # volumeを中心に候補を並べる
    candidates.sort(
        key=lambda x: (
            x["volume_24h_usd"],
            x["liquidity_usd"]
        ),
        reverse=True
    )

    return candidates[
        :MAX_CANDIDATES
    ]


# ============================================================
# Scoring
# ============================================================

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

    # --------------------------------------------------------
    # Liquidity: 0〜25
    # --------------------------------------------------------

    if liquidity >= 100000:
        score += 10

    if liquidity >= 500000:
        score += 5

    if liquidity >= 1000000:
        score += 5

    if liquidity >= 5000000:
        score += 5

    # --------------------------------------------------------
    # Volume: 0〜25
    # --------------------------------------------------------

    if volume >= 25000:
        score += 10

    if volume >= 100000:
        score += 5

    if volume >= 500000:
        score += 5

    if volume >= 1000000:
        score += 5

    # --------------------------------------------------------
    # Volume / Liquidity
    #
    # 低すぎる = 活発ではない
    # 高すぎる = 異常な投機状態の可能性
    # --------------------------------------------------------

    if liquidity > 0:

        volume_liquidity_ratio = (
            volume / liquidity
        )

    else:

        volume_liquidity_ratio = 0

    if (
        0.05
        <= volume_liquidity_ratio
        <= 2.0
    ):

        score += 15

    elif (
        0.02
        <= volume_liquidity_ratio
        <= 4.0
    ):

        score += 8

    # --------------------------------------------------------
    # Momentum: 0〜20
    # --------------------------------------------------------

    if 1 <= change <= 5:

        score += 20

    elif 5 < change <= 10:

        score += 18

    elif 10 < change <= 15:

        score += 12

    elif 0 < change < 1:

        score += 8

    elif -3 <= change < 0:

        score += 4

    else:

        score += 0

    # --------------------------------------------------------
    # Extreme movement penalty
    # --------------------------------------------------------

    if change > 20:

        score -= 15

    if change < -10:

        score -= 10

    return max(
        0,
        min(100, score)
    )


# ============================================================
# Equity
# ============================================================

def calculate_equity(state):

    equity = state[
        "cash"
    ]

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


# ============================================================
# Position helpers
# ============================================================

def already_holding_token(
    state,
    candidate
):

    token_address = (
        candidate.get(
            "token_address"
        )
        or ""
    ).lower()

    chain = candidate.get(
        "chain"
    )

    for position in state[
        "open_positions"
    ]:

        if (
            position.get(
                "chain"
            )
            == chain
            and
            position.get(
                "token_address",
                ""
            ).lower()
            == token_address
        ):

            return True

    return False


def find_candidate_for_position(
    state,
    position
):

    pair_address = position.get(
        "pair_address"
    )

    token_address = (
        position.get(
            "token_address"
        )
        or ""
    ).lower()

    chain = position.get(
        "chain"
    )

    # まずpair完全一致
    for candidate in state[
        "candidates"
    ]:

        if (
            candidate[
                "pair_address"
            ]
            == pair_address
        ):

            return candidate

    # 次にtoken address + chain
    for candidate in state[
        "candidates"
    ]:

        if (
            candidate.get(
                "chain"
            )
            == chain
            and
            candidate.get(
                "token_address",
                ""
            ).lower()
            == token_address
        ):

            return candidate

    return None


# ============================================================
# Open position
# ============================================================

def open_position(
    state,
    candidate
):

    if len(
        state[
            "open_positions"
        ]
    ) >= MAX_OPEN_POSITIONS:

        return False

    if (
        candidate["score"]
        < ENTRY_SCORE_THRESHOLD
    ):

        return False

    if already_holding_token(
        state,
        candidate
    ):

        print(
            f"SKIP "
            f"{candidate['symbol']}: "
            "already holding token"
        )

        return False

    price = candidate[
        "price"
    ]

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
        STOP_LOSS_PCT
        / 100
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
        position_value
        / price
    )

    position = {

        "pair_address":
            candidate[
                "pair_address"
            ],

        "token_address":
            candidate[
                "token_address"
            ],

        "chain":
            candidate[
                "chain"
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

        "highest_price":
            price,

        "quantity":
            quantity,

        "position_value":
            position_value,

        "entry_tick":
            state["tick"],

        "score_at_entry":
            candidate[
                "score"
            ],

        "current_score":
            candidate[
                "score"
            ],

        "stop_loss_price":
            price
            * (
                1
                - STOP_LOSS_PCT
                / 100
            ),

        "original_stop_loss_price":
            price
            * (
                1
                - STOP_LOSS_PCT
                / 100
            ),

        "take_profit_price":
            price
            * (
                1
                + TAKE_PROFIT_PCT
                / 100
            ),

        "stop_mode":
            "INITIAL",

        "url":
            candidate.get(
                "url"
            ),
    }

    state[
        "cash"
    ] -= position_value

    state[
        "open_positions"
    ].append(
        position
    )

    print(
        f"PAPER BUY "
        f"{candidate['symbol']} "
        f"${price} "
        f"value="
        f"${position_value:.2f} "
        f"score="
        f"{candidate['score']}"
    )

    return True


# ============================================================
# Close position
# ============================================================

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

    state[
        "cash"
    ] += exit_value

    trade = {

        "symbol":
            position[
                "symbol"
            ],

        "name":
            position[
                "name"
            ],

        "token_address":
            position.get(
                "token_address"
            ),

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

        "return_pct":
            (
                (
                    exit_price
                    / entry_price
                )
                - 1
            )
            * 100,

        "reason":
            reason,

        "entry_tick":
            position[
                "entry_tick"
            ],

        "exit_tick":
            state[
                "tick"
            ],

        "closed_at":
            now_iso(),

        "score_at_entry":
            position.get(
                "score_at_entry"
            ),

        "last_score":
            position.get(
                "current_score"
            ),

        "stop_mode":
            position.get(
                "stop_mode"
            ),

        "url":
            position.get(
                "url"
            ),
    }

    state[
        "trades"
    ].append(
        trade
    )

    # 最大100件
    state[
        "trades"
    ] = state[
        "trades"
    ][-100:]

    if pnl > 0:

        state[
            "wins"
        ] += 1

        state[
            "consecutive_losses"
        ] = 0

    else:

        state[
            "losses"
        ] += 1

        state[
            "consecutive_losses"
        ] += 1

    total = (
        state["wins"]
        + state["losses"]
    )

    if total > 0:

        state[
            "win_rate"
        ] = (
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


# ============================================================
# Update positions
# ============================================================

def update_positions(
    state
):

    remaining = []

    for position in state[
        "open_positions"
    ]:

        candidate = (
            find_candidate_for_position(
                state,
                position
            )
        )

        if candidate is None:

            print(
                f"NO PRICE "
                f"{position['symbol']}"
            )

            remaining.append(
                position
            )

            continue

        current_price = candidate[
            "price"
        ]

        current_score = candidate[
            "score"
        ]

        position[
            "current_price"
        ] = current_price

        position[
            "current_score"
        ] = current_score

        # 最高値更新
        if current_price > position[
            "highest_price"
        ]:

            position[
                "highest_price"
            ] = current_price

        entry_price = position[
            "entry_price"
        ]

        price_change_pct = (
            (
                current_price
                / entry_price
            )
            - 1
        ) * 100

        # ----------------------------------------------------
        # Breakeven
        # ----------------------------------------------------

        if (
            price_change_pct
            >= BREAKEVEN_TRIGGER_PCT
            and
            position[
                "stop_mode"
            ]
            == "INITIAL"
        ):

            position[
                "stop_loss_price"
            ] = entry_price

            position[
                "stop_mode"
            ] = "BREAKEVEN"

            print(
                f"BREAKEVEN "
                f"{position['symbol']}"
            )

        # ----------------------------------------------------
        # Trailing stop
        # ----------------------------------------------------

        if (
            price_change_pct
            >= TRAILING_TRIGGER_PCT
        ):

            trailing_stop = (
                position[
                    "highest_price"
                ]
                * (
                    1
                    - TRAILING_STOP_PCT
                    / 100
                )
            )

            if (
                trailing_stop
                >
                position[
                    "stop_loss_price"
                ]
            ):

                position[
                    "stop_loss_price"
                ] = trailing_stop

                position[
                    "stop_mode"
                ] = "TRAILING"

        hold_ticks = (
            state["tick"]
            - position[
                "entry_tick"
            ]
        )

        # ----------------------------------------------------
        # Exit checks
        # ----------------------------------------------------

        reason = None

        if (
            current_price
            <= position[
                "stop_loss_price"
            ]
        ):

            reason = (
                "TRAILING_STOP"
                if position[
                    "stop_mode"
                ] == "TRAILING"
                else
                "BREAKEVEN_STOP"
                if position[
                    "stop_mode"
                ] == "BREAKEVEN"
                else
                "STOP_LOSS"
            )

        elif (
            current_price
            >= position[
                "take_profit_price"
            ]
        ):

            reason = "TAKE_PROFIT"

        elif (
            current_score
            < EXIT_SCORE_THRESHOLD
            and
            hold_ticks >= 2
        ):

            reason = "SCORE_EXIT"

        elif (
            hold_ticks
            >= MAX_HOLD_TICKS
        ):

            reason = "MAX_HOLD"

        if reason:

            close_position(
                state,
                position,
                current_price,
                reason
            )

        else:

            remaining.append(
                position
            )

    state[
        "open_positions"
    ] = remaining


# ============================================================
# Risk metrics
# ============================================================

def update_risk_metrics(
    state
):

    equity = calculate_equity(
        state
    )

    state[
        "equity"
    ] = equity

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
            /
            state[
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

    state[
        "pnl"
    ] = (
        equity
        - STARTING_BALANCE
    )

    state[
        "pnl_pct"
    ] = (
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

    # --------------------------------------------------------
    # Equity history
    # --------------------------------------------------------

    history = state.get(
        "equity_history",
        []
    )

    history.append({

        "tick":
            state["tick"],

        "timestamp":
            state["updated_at"],

        "equity":
            equity,

        "cash":
            state["cash"],

        "pnl":
            state["pnl"],

        "pnl_pct":
            state["pnl_pct"],

    })

    # 最大200件
    state[
        "equity_history"
    ] = history[-200:]


# ============================================================
# Main
# ============================================================

def main():

    print(
        "================================"
    )

    print(
        "Meme AI Trader v2"
    )

    print(
        "PAPER MODE"
    )

    print(
        "REAL MARKET DATA"
    )

    print(
        "NO LIVE TRADING"
    )

    print(
        "================================"
    )

    state = load_state()

    state[
        "tick"
    ] += 1

    state[
        "updated_at"
    ] = now_iso()

    state[
        "mode"
    ] = "PAPER"

    # --------------------------------------------------------
    # Collect market
    # --------------------------------------------------------

    candidates = (
        collect_candidates()
    )

    # --------------------------------------------------------
    # Score
    # --------------------------------------------------------

    for candidate in candidates:

        candidate[
            "score"
        ] = calculate_score(
            candidate
        )

    state[
        "candidates"
    ] = candidates

    # --------------------------------------------------------
    # Existing positions
    # --------------------------------------------------------

    update_positions(
        state
    )


    # --------------------------------------------------------
    # New entries
    # --------------------------------------------------------

    if not state[
        "cooldown"
    ]:

        sorted_candidates = sorted(
            candidates,
            key=lambda x: (
                x["score"],
                x["volume_24h_usd"],
                x["liquidity_usd"],
            ),
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

            opened = open_position(
                state,
                candidate
            )

            if opened:

                print(
                    f"ENTRY "
                    f"{candidate['symbol']} "
                    f"score="
                    f"{candidate['score']}"
                )

    # --------------------------------------------------------
    # Final metrics
    # --------------------------------------------------------

    update_risk_metrics(
        state
    )

    save_state(
        state
    )

    # --------------------------------------------------------
    # Console
    # --------------------------------------------------------

    print(
        "--------------------------------"
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
        f"Consecutive losses: "
        f"{state['consecutive_losses']}"
    )

    print(
        f"Cooldown: "
        f"{state['cooldown']}"
    )

    print(
        "state.json updated."
    )

    print(
        "--------------------------------"
    )


if __name__ == "__main__":
    main()
