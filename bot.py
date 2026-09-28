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

# PAPER TRADING SETTINGS
MAX_OPEN_POSITIONS = 2
RISK_PER_TRADE_PCT = 1.0

STOP_LOSS_PCT = 8.0
TAKE_PROFIT_PCT = 16.0

# 1回のActions実行を1 tickとして扱う
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

        # 古いstate.jsonに新しい項目を追加
        base = default_state()
        for key, value in base.items():
            if key not in state:
                state[key] = value

        return state

    except Exception:
        return default_state()


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def search_market(keyword):
    try:
        response = requests.get(
            SEARCH_URL,
            params={"q": keyword},
            timeout=15,
            headers={"User-Agent": "meme-ai-trader-paper/1.0"}
        )

        response.raise_for_status()

        return response.json().get("pairs", [])

    except Exception as e:
        print(f"API error [{keyword}]: {e}")
        return []


def collect_candidates():
    unique = {}

    for keyword in SEARCH_WORDS:
        print(f"Searching: {keyword}")

        for pair in search_market(keyword):

            liquidity = pair.get("liquidity") or {}
            volume = pair.get("volume") or {}
            price_change = pair.get("priceChange") or {}
            base = pair.get("baseToken") or {}

            try:
                liquidity_usd = float(liquidity.get("usd") or 0)
                volume_24h = float(volume.get("h24") or 0)
                price_usd = float(pair.get("priceUsd") or 0)
                change_24h = float(price_change.get("h24") or 0)

            except (TypeError, ValueError):
                continue

            if liquidity_usd < MIN_LIQUIDITY_USD:
                continue

            if volume_24h < MIN_VOLUME_USD:
                continue

            if price_usd <= 0:
                continue

            pair_address = pair.get("pairAddress")

            if not pair_address:
                continue

            unique[pair_address] = {
                "chain": pair.get("chainId"),
                "dex": pair.get("dexId"),
                "pair_address": pair_address,

                "symbol": base.get("symbol", "UNKNOWN"),
                "name": base.get("name", "UNKNOWN"),

                "price": price_usd,
                "liquidity_usd": liquidity_usd,
                "volume_24h_usd": volume_24h,
                "price_change_24h_pct": change_24h,

                "url": pair.get("url")
            }

    candidates = list(unique.values())

    candidates.sort(
        key=lambda x: (
            x["volume_24h_usd"],
            x["liquidity_usd"]
        ),
        reverse=True
    )

    return candidates[:MAX_CANDIDATES]


def calculate_score(c):
    score = 0

    liquidity = c["liquidity_usd"]
    volume = c["volume_24h_usd"]
    change = c["price_change_24h_pct"]

    if liquidity >= 10000:
        score += 20

    if liquidity >= 50000:
        score += 10

    if volume >= 10000:
        score += 20

    if volume >= 50000:
        score += 10

    # 上昇しているが、極端な急騰は避ける
    if 0 < change <= 20:
        score += 20

    if change > 20:
        score += 5

    if change < -20:
        score -= 10

    return max(0, min(100, score))


def get_candidate_prices(candidates):
    return {
        c["pair_address"]: c["price"]
        for c in candidates
    }


def calculate_equity(state):
    equity = state["cash"]

    for position in state["open_positions"]:
        current_price = position.get("current_price", position["entry_price"])

        quantity = position["quantity"]

        equity += quantity * current_price

    return equity


def open_position(state, candidate):
    if len(state["open_positions"]) >= MAX_OPEN_POSITIONS:
        return False

    score = candidate["score"]

    # エントリー条件
    if score < 60:
        return False

    price = candidate["price"]

    if price <= 0:
        return False

    # 1回の取引で口座の1%をリスク
    risk_amount = state["equity"] * (RISK_PER_TRADE_PCT / 100)

    # SLまで8%下落すると仮定
    stop_distance = STOP_LOSS_PCT / 100

    position_value = risk_amount / stop_distance

    # 最大でも現金の25%
    position_value = min(
        position_value,
        state["cash"] * 0.25
    )

    if position_value <= 0:
        return False

    quantity = position_value / price

    position = {
        "pair_address": candidate["pair_address"],
        "symbol": candidate["symbol"],
        "name": candidate["name"],

        "entry_price": price,
        "current_price": price,

        "quantity": quantity,
        "position_value": position_value,

        "entry_tick": state["tick"],

        "score_at_entry": score,

        "stop_loss_price": price * (1 - STOP_LOSS_PCT / 100),
        "take_profit_price": price * (1 + TAKE_PROFIT_PCT / 100),

        "url": candidate.get("url")
    }

    state["cash"] -= position_value

    state["open_positions"].append(position)

    print(
        f"PAPER BUY {candidate['symbol']} "
        f"price={price} "
        f"value=${position_value:.2f} "
        f"score={score}"
    )

    return True


def close_position(state, position, exit_price, reason):
    entry_price = position["entry_price"]
    quantity = position["quantity"]

    pnl = (exit_price - entry_price) * quantity

    exit_value = exit_price * quantity

    state["cash"] += exit_value

    trade = {
        "symbol": position["symbol"],
        "name": position["name"],

        "entry_price": entry_price,
        "exit_price": exit_price,

        "quantity": quantity,
        "position_value": position["position_value"],

        "pnl": pnl,

        "reason": reason,

        "entry_tick": position["entry_tick"],
        "exit_tick": state["tick"],

        "closed_at": now_iso(),

        "url": position.get("url")
    }

    state["trades"].append(trade)

    if len(state["trades"]) > 100:
        state["trades"] = state["trades"][-100:]

    if pnl > 0:
        state["wins"] += 1
        state["consecutive_losses"] = 0

    else:
        state["losses"] += 1
        state["consecutive_losses"] += 1

    total = state["wins"] + state["losses"]

    if total > 0:
        state["win_rate"] = (
            state["wins"] / total
        ) * 100

    print(
        f"PAPER SELL {position['symbol']} "
        f"price={exit_price} "
        f"PnL=${pnl:.2f} "
        f"reason={reason}"
    )


def update_positions(state, price_map):
    remaining = []

    for position in state["open_positions"]:

        pair_address = position["pair_address"]

        current_price = price_map.get(pair_address)

        if current_price is None:
            # 価格が取得できなければ今回は保有継続
            remaining.append(position)
            continue

        position["current_price"] = current_price

        entry_price = position["entry_price"]

        change_pct = (
            (current_price - entry_price)
            / entry_price
        ) * 100

        hold_ticks = (
            state["tick"] - position["entry_tick"]
        )

        if current_price <= position["stop_loss_price"]:

            close_position(
                state,
                position,
                current_price,
                "STOP_LOSS"
            )

        elif current_price >= position["take_profit_price"]:

            close_position(
                state,
                position,
                current_price,
                "TAKE_PROFIT"
            )

        elif hold_ticks >= MAX_HOLD_TICKS:

            close_position(
                state,
                position,
                current_price,
                "MAX_HOLD"

            )

        else:
            remaining.append(position)

    state["open_positions"] = remaining


def update_risk_metrics(state):
    equity = calculate_equity(state)

    state["equity"] = equity

    if equity > state["max_equity"]:
        state["max_equity"] = equity

    if state["max_equity"] > 0:

        drawdown = (
            (state["max_equity"] - equity)
            / state["max_equity"]
        ) * 100

        state["max_drawdown_pct"] = max(
            state["max_drawdown_pct"],
            drawdown
        )

    state["pnl"] = equity - STARTING_BALANCE

    state["pnl_pct"] = (
        state["pnl"] / STARTING_BALANCE
    ) * 100

    # 3連敗したら次回エントリーを停止
    state["cooldown"] = (
        state["consecutive_losses"] >= 3
    )


def main():

    print(
        "Meme AI Trader - "
        "PAPER MODE / REAL MARKET DATA / NO LIVE TRADING"
    )

    state = load_state()

    state["tick"] += 1
    state["updated_at"] = now_iso()
    state["mode"] = "PAPER"

    # 市場データ取得
    candidates = collect_candidates()

    for candidate in candidates:
        candidate["score"] = calculate_score(candidate)

    state["candidates"] = candidates

    price_map = get_candidate_prices(candidates)

    # 既存ポジションの更新
    update_positions(
        state,
        price_map
    )

    update_risk_metrics(state)

    # 新規エントリー
    if not state["cooldown"]:

        # スコア順
        sorted_candidates = sorted(
            candidates,
            key=lambda x: x["score"],
            reverse=True
        )

        for candidate in sorted_candidates:

            if len(state["open_positions"]) >= MAX_OPEN_POSITIONS:
                break

            # 同じ銘柄を二重購入しない
            already_open = any(
                p["pair_address"]
                == candidate["pair_address"]
                for p in state["open_positions"]
            )

            if already_open:
                continue

            open_position(
                state,
                candidate
            )

    update_risk_metrics(state)

    save_state(state)

    print(
        f"Candidates: {len(candidates)}"
    )

    print(
        f"Open positions: "
        f"{len(state['open_positions'])}"
    )

    print(
        f"Cash: ${state['cash']:.2f}"
    )

    print(
        f"Equity: ${state['equity']:.2f}"
    )

    print(
        f"P&L: ${state['pnl']:.2f} "
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

    print("state.json updated.")


if __name__ == "__main__":
    main()
