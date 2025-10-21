#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Upbit DCA Bot — Buy-on-Price-Drop Strategy (BTC/ETH/XRP)
- Supports per-coin DROP_PCT via DROP_PCT_PER_COIN env var.
- Strategy: 분할매수(DCA) but trigger buys when price drops by DROP_PCT (per-coin) from the last buy price.
  * INITIAL_BUY: 시작 시 기본 1회분 매수 여부 (True/False)
  * After each buy, next_buy_price = last_buy_price * (1 - DROP_PCT/100)
  * Do this until INSTALLMENTS reached.
- ALLOCATIONS (percent or fractions), TARGET exit (percent/KRW), SELL_FRACTION, DRY_RUN supported.
- purchases.json stores progress and trigger prices so restarts continue correctly.
"""

import os
import time
import json
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import pyupbit
import traceback


def _parse_bool(value, default=False):
    return default if value is None else str(value).lower() in ("1", "true", "yes", "on")

load_dotenv()

# --- 설정 (환경변수로 오버라이드 가능) ---
COINS = ["KRW-BTC", "KRW-ETH", "KRW-XRP"]

# 분할매수 관련
INSTALLMENTS = int(os.getenv("INSTALLMENTS", "5"))           # 각 코인별 총 매수 횟수
MIN_KRW_ORDER = int(os.getenv("MIN_KRW_ORDER", "5000"))      # 업비트 최소 주문금액(원)

# 전역 가격 하락 트리거(퍼센트) - 기본값 (per-coin이 없을 때 사용)
DROP_PCT = float(os.getenv("DROP_PCT", "2.0"))               # % 단위: 2.0 -> 2% 떨어지면 매수

# 코인별 DROP_PCT 설정 (예: "KRW-BTC:2,KRW-ETH:3" 또는 "BTC:2,ETH:3")
DROP_PCT_PER_COIN = os.getenv("DROP_PCT_PER_COIN", "").strip()

# 초기 매수 여부: 시작 시 1회분을 바로 매수할지 (True/False)
INITIAL_BUY = _parse_bool(os.getenv("INITIAL_BUY", "true"), default=True)

# 자금 할당: 전체 KRW 잔고의 몇 %를 투입할지 또는 TOTAL_INVEST_KRW 사용
TOTAL_INVEST_FRACTION = float(os.getenv("TOTAL_INVEST_FRACTION", "0.5"))  # 기본 50% 사용
TOTAL_INVEST_KRW = os.getenv("TOTAL_INVEST_KRW", "")  # 절대 금액 지정 시 사용

# 코인별 비중(옵션). 예: "KRW-BTC:50,KRW-ETH:30,KRW-XRP:20" 또는 "BTC:0.5,ETH:0.3,XRP:0.2"
ALLOCATIONS_ENV = os.getenv("ALLOCATIONS", "")  # 빈 문자열이면 균등 분배

# Exit(청산) 관련 설정
TARGET_PROFIT_PCT = os.getenv("TARGET_PROFIT_PCT", "")  # 예: "10" -> 10% 이익 시 매도
TARGET_PROFIT_KRW = os.getenv("TARGET_PROFIT_KRW", "")  # 예: "5000" -> 순이익 5,000원 이상 시 매도
SELL_FRACTION = float(os.getenv("SELL_FRACTION", "1.0"))  # 매도 시 전량:1.0, 일부:0.5 등

# purchases 기록 파일
PURCHASES_DEFAULT = "purchases.json"
PURCHASES_ALLOWED_SUFFIXES = {".json"}
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PURCHASES_PATH = (BASE_DIR / PURCHASES_DEFAULT).resolve()
PURCHASES_FILE_ENV = os.getenv("PURCHASES_FILE", PURCHASES_DEFAULT)


def _resolve_purchases_path(env_value):
    candidate_value = (env_value or PURCHASES_DEFAULT).strip()
    if not candidate_value:
        candidate_value = PURCHASES_DEFAULT
    candidate = Path(candidate_value)
    if not candidate.is_absolute():
        candidate = (BASE_DIR / candidate).resolve()
    else:
        candidate = candidate.resolve()

    log = logging.getLogger("upbit-dca-drop-bot")
    try:
        candidate.relative_to(BASE_DIR)
    except ValueError:
        log.warning("Rejected PURCHASES_FILE outside project dir: %s", env_value)
        return DEFAULT_PURCHASES_PATH

    if candidate.suffix.lower() not in PURCHASES_ALLOWED_SUFFIXES:
        log.warning("Rejected PURCHASES_FILE with disallowed suffix: %s", candidate)
        return DEFAULT_PURCHASES_PATH

    if candidate.is_dir():
        log.warning("Rejected PURCHASES_FILE pointing to directory: %s", candidate)
        return DEFAULT_PURCHASES_PATH

    return candidate


PURCHASES_FILE = _resolve_purchases_path(PURCHASES_FILE_ENV)

# 모니터링 주기 (초)
MONITOR_INTERVAL_SEC = int(os.getenv("MONITOR_INTERVAL_SEC", str(60 * int(os.getenv("MONITOR_INTERVAL_MIN", "5")))))  # 기본 5분

# 실행 모드
DRY_RUN = _parse_bool(os.getenv("DRY_RUN", "true"), default=True)

# 업비트 API 키 (실거래 시 필요)
ACCESS = os.getenv("UPBIT_ACCESS_KEY", "")
SECRET = os.getenv("UPBIT_SECRET_KEY", "")

# Upbit 클라이언트 (실거래 모드에서만 초기화)
if ACCESS and SECRET and not DRY_RUN:
    upbit = pyupbit.Upbit(ACCESS, SECRET)
    client_mode = "LIVE"
else:
    upbit = None
    client_mode = "DRY_RUN"

SIM_STATE = None
if DRY_RUN or upbit is None:
    try:
        sim_krw = float(os.getenv("SIM_KRW_BALANCE", "100000"))
    except ValueError:
        sim_krw = 100000.0
    SIM_STATE = {
        "krw": max(0.0, sim_krw),
        "coins": {}
    }
    for ticker in COINS:
        currency = ticker.split("-")[1]
        try:
            initial_coin = float(os.getenv(f"SIM_BAL_{currency}", "0"))
        except ValueError:
            initial_coin = 0.0
        SIM_STATE["coins"][ticker] = max(0.0, initial_coin)

# 로깅
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("upbit-dca-drop-bot")

# --- 헬퍼 함수들 ---
def parse_allocations(env_str):
    if not env_str:
        return None
    try:
        parts = [p.strip() for p in env_str.split(",") if p.strip()]
        raw = {}
        for p in parts:
            if ":" not in p:
                continue
            k, v = p.split(":", 1)
            key = k.strip().upper()
            val = float(v.strip())
            matched = None
            for t in COINS:
                if key == t.upper() or key == t.split("-")[1].upper():
                    matched = t
                    break
            if matched:
                raw[matched] = val
            else:
                if key.startswith("KRW-"):
                    raw[key] = val
                else:
                    raw["KRW-" + key] = val
        if not raw:
            return None

        sum_vals = sum(raw.values())
        normalized = {}
        if sum_vals > 1.01:
            if sum_vals <= 100.0:
                for k, v in raw.items():
                    normalized[k] = v / 100.0
            else:
                for k, v in raw.items():
                    normalized[k] = v / sum_vals
        else:
            for k, v in raw.items():
                normalized[k] = v
            s = sum(normalized.values())
            if s > 0:
                for k in list(normalized.keys()):
                    normalized[k] = normalized[k] / s

        specified_sum = sum(normalized.get(t, 0.0) for t in COINS if t in normalized)
        unspecified = [t for t in COINS if t not in normalized]
        result = {}
        if unspecified:
            remaining = max(0.0, 1.0 - specified_sum)
            per_unspecified = remaining / len(unspecified) if len(unspecified) > 0 else 0.0
            for t in COINS:
                if t in normalized:
                    result[t] = normalized[t]
                else:
                    result[t] = per_unspecified
        else:
            total = sum(normalized.values())
            if total > 0:
                for t in COINS:
                    result[t] = normalized.get(t, 0.0) / total
            else:
                per = 1.0 / len(COINS) if COINS else 0.0
                for t in COINS:
                    result[t] = per
        s_final = sum(result.values())
        if s_final <= 0:
            per = 1.0 / len(COINS) if COINS else 0.0
            for t in COINS:
                result[t] = per
        else:
            for t in result:
                result[t] = result[t] / s_final
        return result
    except Exception:
        logger.exception("ALLOCATIONS 파싱 중 오류 발생")
        return None

def parse_drop_pcts(env_str):
    """
    Parse DROP_PCT_PER_COIN env var like "KRW-BTC:2,ETH:3,XRP:5" or "BTC:2,ETH:3".
    Returns dict mapping full ticker -> drop_pct (float).
    Keys not matching COINS are attempted with KRW- prefix.
    """
    if not env_str:
        return {}
    try:
        parts = [p.strip() for p in env_str.split(",") if p.strip()]
        result = {}
        for p in parts:
            if ":" not in p:
                continue
            k, v = p.split(":", 1)
            key = k.strip().upper()
            try:
                val = float(v.strip())
            except Exception:
                logger.warning(f"DROP_PCT_PER_COIN의 값 파싱 실패: {p}, 무시합니다.")
                continue
            matched = None
            for t in COINS:
                if key == t.upper() or key == t.split("-")[1].upper():
                    matched = t
                    break
            if matched:
                result[matched] = val
            else:
                if key.startswith("KRW-"):
                    result[key] = val
                else:
                    result["KRW-" + key] = val
        # Filter only known COINS (ignore unknown tickers)
        filtered = {t: result[t] for t in result if t in COINS}
        return filtered
    except Exception:
        logger.exception("DROP_PCT_PER_COIN 파싱 중 오류 발생")
        return {}

ALLOCATIONS = parse_allocations(ALLOCATIONS_ENV)
DROP_PCTS = parse_drop_pcts(DROP_PCT_PER_COIN)


def load_purchases():
    if PURCHASES_FILE.exists():
        try:
            with PURCHASES_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.warning("purchases.json 읽기 실패, 새로 생성합니다.")
    return {}


def save_purchases(data):
    try:
        PURCHASES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with PURCHASES_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"purchases.json 저장 실패: {e}")

def get_krw_balance():
    if DRY_RUN or upbit is None:
        if SIM_STATE is None:
            return 0.0
        return SIM_STATE.get("krw", 0.0)
    try:
        balances = upbit.get_balances()
        for b in balances:
            if b['currency'] == 'KRW':
                return float(b['balance'])
    except Exception as e:
        logger.error(f"KRW 잔고 조회 실패: {e}")
    return 0.0

def ticker_price(ticker):
    try:
        ob = pyupbit.get_orderbook(tickers=[ticker])
        if ob and len(ob) > 0:
            return float(ob[0]['orderbook_units'][0]['ask_price'])
    except Exception:
        pass
    try:
        df = pyupbit.get_ohlcv(ticker, count=1)
        if df is not None and not df.empty:
            return float(df['close'].iloc[-1])
    except Exception:
        pass
    return None

def place_market_buy(ticker, krw_amount):
    krw_amount = float(krw_amount)
    if krw_amount < MIN_KRW_ORDER:
        logger.info(f"[{ticker}] 매수 금액 {krw_amount:.0f}원 < 최소 {MIN_KRW_ORDER}원, 생략")
        return None
    if DRY_RUN or upbit is None:
        price = ticker_price(ticker) or 0
        if price <= 0:
            logger.warning(f"[{ticker}] 시뮬레이션 매수 가격 조회 실패, 주문 스킵")
            return None
        qty = krw_amount / price if price and price > 0 else 0
        resp = {
            "result": "dry_run_buy",
            "ticker": ticker,
            "krw": krw_amount,
            "price": price,
            "amount": qty,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        logger.info(f"[DRY_RUN] BUY {ticker} KRW {krw_amount:.0f} -> qty {qty:.8f} @ price {price}")
        if SIM_STATE is not None:
            SIM_STATE["krw"] = max(0.0, SIM_STATE.get("krw", 0.0) - krw_amount)
            SIM_STATE["coins"][ticker] = SIM_STATE["coins"].get(ticker, 0.0) + qty
        return resp
    try:
        resp = upbit.buy_market_order(ticker, krw_amount)
        logger.info(f"BUY 주문 전송: {resp}")
        return resp
    except Exception as e:
        logger.error(f"buy_market_order 실패: {e}")
        logger.debug(traceback.format_exc())
        return None

def place_market_sell(ticker, amount):
    amount = float(amount)
    market_price = ticker_price(ticker) or 0
    value_krw = amount * market_price
    if value_krw < MIN_KRW_ORDER:
        logger.info(f"[{ticker}] 매도 가치 {value_krw:.0f}원 < 최소 {MIN_KRW_ORDER}원, 매도 생략")
        return None
    if DRY_RUN or upbit is None:
        if market_price <= 0:
            logger.warning(f"[{ticker}] 시뮬레이션 매도 가격 조회 실패, 주문 스킵")
            return None
        actual_amount = amount
        if SIM_STATE is not None:
            held = SIM_STATE["coins"].get(ticker, 0.0)
            if held <= 0:
                logger.info(f"[{ticker}] 시뮬레이션 보유량이 없어 매도 생략")
                return None
            if held < amount:
                logger.warning(f"[{ticker}] 요청한 매도 수량 {amount:.8f} > 보유 {held:.8f}, 보유분만 매도")
                actual_amount = held
            SIM_STATE["coins"][ticker] = max(0.0, held - actual_amount)
            SIM_STATE["krw"] = SIM_STATE.get("krw", 0.0) + actual_amount * market_price
        value_krw = actual_amount * market_price
        resp = {
            "result": "dry_run_sell",
            "ticker": ticker,
            "amount": actual_amount,
            "price": market_price,
            "krw": value_krw,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        logger.info(f"[DRY_RUN] SELL {ticker} amt {actual_amount:.8f} @ price {market_price} -> KRW {value_krw:.0f}")
        return resp
    try:
        resp = upbit.sell_market_order(ticker, amount)
        logger.info(f"SELL 주문 전송: {resp}")
        return resp
    except Exception as e:
        logger.error(f"sell_market_order 실패: {e}")
        logger.debug(traceback.format_exc())
        return None

def record_purchase_entry(ticker, entry):
    purchases = load_purchases()
    if ticker not in purchases:
        purchases[ticker] = {
            "target_krw": 0.0,
            "installments": INSTALLMENTS,
            "purchased": [],
            "sold": [],
            "last_buy_price": None,
            "next_buy_price": None,
            "completed": False,
            "exited": False
        }
    purchases[ticker]["purchased"].append(entry)
    price = entry.get("price", None)
    # per-coin drop pct (fallback to global DROP_PCT)
    drop_pct = DROP_PCTS.get(ticker, DROP_PCT)
    if price:
        purchases[ticker]["last_buy_price"] = price
        purchases[ticker]["next_buy_price"] = round(price * (1.0 - drop_pct / 100.0), 8)
    if len(purchases[ticker]["purchased"]) >= purchases[ticker].get("installments", INSTALLMENTS):
        purchases[ticker]["completed"] = True
    save_purchases(purchases)

def record_sale_entry(ticker, entry):
    purchases = load_purchases()
    if ticker not in purchases:
        purchases[ticker] = {
            "target_krw": 0.0,
            "installments": INSTALLMENTS,
            "purchased": [],
            "sold": [],
            "last_buy_price": None,
            "next_buy_price": None,
            "completed": False,
            "exited": False
        }
    purchases[ticker].setdefault("sold", []).append(entry)
    purchases[ticker]["exited"] = True
    save_purchases(purchases)

def compute_allocations(total_krw):
    if ALLOCATIONS:
        allocs = {}
        for t in COINS:
            frac = ALLOCATIONS.get(t, 0.0)
            allocs[t] = total_krw * frac
        return allocs
    per = total_invest / len(COINS) if len(COINS) > 0 else 0
    return {t: per for t in COINS}

def analyze_unrealized(ticker):
    purchases = load_purchases().get(ticker, {})
    bought = purchases.get("purchased", [])
    total_amount = sum([it.get("amount", 0) for it in bought])
    total_spent = sum([it.get("krw", 0) for it in bought])
    sold = purchases.get("sold", [])
    total_sold_amount = sum([it.get("amount", 0) for it in sold])
    total_sold_krw = sum([it.get("krw", 0) for it in sold])
    held_amount = max(0.0, total_amount - total_sold_amount)
    current_price = ticker_price(ticker) or 0
    current_value = held_amount * current_price
    avg_buy_price = (total_spent / total_amount) if total_amount > 0 else 0
    invested_for_held = avg_buy_price * held_amount
    unrealized_krw = current_value - invested_for_held
    unrealized_pct = (unrealized_krw / invested_for_held * 100) if invested_for_held > 0 else 0
    return {
        "held_amount": held_amount,
        "avg_buy_price": avg_buy_price,
        "invested_for_held": invested_for_held,
        "current_price": current_price,
        "current_value": current_value,
        "unrealized_krw": unrealized_krw,
        "unrealized_pct": unrealized_pct
    }

def should_exit(ticker):
    pct_target = None
    krw_target = None
    try:
        if TARGET_PROFIT_PCT:
            pct_target = float(TARGET_PROFIT_PCT)
    except Exception:
        pct_target = None
    try:
        if TARGET_PROFIT_KRW:
            krw_target = float(TARGET_PROFIT_KRW)
    except Exception:
        krw_target = None

    stats = analyze_unrealized(ticker)
    if stats["held_amount"] <= 0 or stats["invested_for_held"] <= 0:
        return False, stats
    if pct_target is not None and stats["unrealized_pct"] >= pct_target:
        return True, stats
    if krw_target is not None and stats["unrealized_krw"] >= krw_target:
        return True, stats
    return False, stats

def prepare_targets(total_krw):
    purchases = load_purchases()
    for t in COINS:
        frac = ALLOCATIONS.get(t, 0.0) if ALLOCATIONS else (1.0 / len(COINS))
        target = total_krw * frac
        if t not in purchases:
            purchases[t] = {
                "target_krw": float(target),
                "installments": INSTALLMENTS,
                "purchased": [],
                "sold": [],
                "last_buy_price": None,
                "next_buy_price": None,
                "completed": False,
                "exited": False
            }
        else:
            if not purchases[t].get("completed", False) and not purchases[t].get("exited", False):
                purchases[t]["target_krw"] = float(target)
                purchases[t]["installments"] = INSTALLMENTS
    save_purchases(purchases)
    return purchases

# --- 메인 루프 ---
def main():
    global total_invest
    logger.info(f"Starting DCA Drop-Buy bot ({client_mode}). Coins: {COINS}")
    logger.info(f"Using purchases file: {PURCHASES_FILE}")
    if ALLOCATIONS:
        logger.info(f"사용자 지정 ALLOCATIONS (fractions): {ALLOCATIONS}")
    if DROP_PCTS:
        logger.info(f"사용자 지정 DROP_PCT_PER_COIN: {DROP_PCTS}")
    logger.info(f"GLOBAL DROP_PCT={DROP_PCT}% INITIAL_BUY={INITIAL_BUY} INSTALLMENTS={INSTALLMENTS}")
    try:
        krw_balance = get_krw_balance()
        logger.info(f"KRW Balance: {krw_balance:.0f} KRW")

        if TOTAL_INVEST_KRW:
            try:
                total_invest = float(TOTAL_INVEST_KRW)
            except Exception:
                total_invest = krw_balance * TOTAL_INVEST_FRACTION
        else:
            total_invest = krw_balance * TOTAL_INVEST_FRACTION

        if total_invest > krw_balance:
            logger.warning("총투자금(total_invest)이 KRW 잔고를 초과하여 잔고로 제한합니다.")
            total_invest = krw_balance

        logger.info(f"총투자금(분할 대상): {total_invest:.0f} KRW")
        if TARGET_PROFIT_PCT:
            logger.info(f"목표 수익률: {TARGET_PROFIT_PCT}% 이상이면 청산")
        if TARGET_PROFIT_KRW:
            logger.info(f"목표 이익(절대): {TARGET_PROFIT_KRW}원 이상이면 청산")

        purchases = prepare_targets(total_invest)
        allocs = {t: purchases[t]['target_krw'] for t in COINS}
        logger.info("각 코인별 목표(원) 및 1회분 금액:")
        for t in COINS:
            one_amount = purchases[t]['target_krw'] / purchases[t]['installments'] if purchases[t]['installments'] > 0 else 0
            use_drop = DROP_PCTS.get(t, DROP_PCT)
            logger.info(f" - {t}: target {purchases[t]['target_krw']:.0f} KRW, one_amount {one_amount:.0f} KRW, DROP_PCT {use_drop}%")

        # INITIAL_BUY: 기본 1회분 매수 (설정에 따라)
        if INITIAL_BUY:
            logger.info("INITIAL_BUY 활성화: 보유하지 않은 코인에 대해 1회분을 즉시 매수 시도합니다.")
            krw_balance = get_krw_balance()
            for t in COINS:
                try:
                    purchases = load_purchases()
                    entry = purchases.get(t, {})
                    done = len(entry.get("purchased", []))
                    if done >= entry.get("installments", INSTALLMENTS):
                        logger.info(f"[{t}] 이미 충분한 매수(완료) 상태, 초기 매수 스킵.")
                        continue
                    if entry.get("exited", False):
                        logger.info(f"[{t}] 이미 청산된 상태, 초기 매수 스킵.")
                        continue
                    one_amount = entry.get("target_krw", 0) / entry.get("installments", INSTALLMENTS) if entry.get("installments", INSTALLMENTS) > 0 else 0
                    if one_amount < MIN_KRW_ORDER:
                        logger.info(f"[{t}] 1회분 금액 {one_amount:.0f}원 < 최소 {MIN_KRW_ORDER}원, 초기 매수 스킵 및 완료 처리.")
                        purchases[t]["completed"] = True
                        save_purchases(purchases)
                        continue
                    if krw_balance < one_amount:
                        logger.warning(f"[{t}] 초기 매수 잔고 부족: 필요 {one_amount:.0f}원, 보유 {krw_balance:.0f}원. 스킵.")
                        continue
                    logger.info(f"[{t}] 초기 매수 시도 -> {one_amount:.0f} KRW")
                    resp = place_market_buy(t, one_amount)
                    if resp:
                        if isinstance(resp, dict):
                            record_purchase_entry(t, resp)
                        else:
                            record_purchase_entry(t, {"result": str(resp), "krw": one_amount, "price": None, "amount": None, "timestamp": datetime.utcnow().isoformat() + "Z"})
                        krw_balance -= one_amount
                    time.sleep(0.5)
                except Exception as e:
                    logger.error(f"[{t}] 초기 매수 중 예외: {e}")
                    logger.debug(traceback.format_exc())

        # 모니터링 루프: 가격이 next_buy_price 이하로 내려가면 매수 트리거
        logger.info("모니터링 루프 시작: 가격 하락 시 분할매수 트리거를 감시합니다.")
        while True:
            try:
                purchases = load_purchases()
                all_done = all((purchases.get(t, {}).get("completed", False) or purchases.get(t, {}).get("exited", False)) for t in COINS)
                if all_done:
                    logger.info("모든 코인의 분할매수가 완료되었거나 청산됨. 루프를 종료합니다.")
                    break
                krw_balance = get_krw_balance()
                for t in COINS:
                    try:
                        entry = purchases.get(t, {})
                        if not entry:
                            continue
                        if entry.get("exited", False) or entry.get("completed", False):
                            continue

                        installments = int(entry.get("installments", INSTALLMENTS))
                        done = len(entry.get("purchased", []))
                        remaining = installments - done
                        if remaining <= 0:
                            purchases[t]["completed"] = True
                            save_purchases(purchases)
                            logger.info(f"[{t}] 분할매수 완료로 표시.")
                            continue

                        one_amount = entry.get("target_krw", 0) / installments if installments > 0 else 0
                        if one_amount < MIN_KRW_ORDER:
                            logger.info(f"[{t}] 1회분 금액 {one_amount:.0f}원 < 최소 {MIN_KRW_ORDER}원, 자동 스킵 및 완료 처리.")
                            purchases[t]["completed"] = True
                            save_purchases(purchases)
                            continue

                        cur_price = ticker_price(t)
                        if cur_price is None:
                            logger.warning(f"[{t}] 현재가 조회 불가, 다음 코인으로 건너뜀.")
                            continue

                        # per-coin drop pct or global
                        drop_pct = DROP_PCTS.get(t, DROP_PCT)
                        next_price = entry.get("next_buy_price", None)
                        if next_price is None:
                            # If no previous buy, set next_price to current_price * (1 - drop_pct)
                            next_price = round(cur_price * (1.0 - drop_pct / 100.0), 8)
                            purchases[t]["next_buy_price"] = next_price
                            save_purchases(purchases)
                            logger.debug(f"[{t}] next_buy_price 초기화 -> {next_price} (DROP_PCT {drop_pct}%)")

                        logger.info(f"[{t}] 현재가 {cur_price:.0f}, next_buy_price {next_price}, 남은회차 {remaining}, DROP_PCT {drop_pct}%")
                        # Trigger if price <= next_buy_price
                        if cur_price <= float(next_price):
                            if krw_balance < one_amount:
                                logger.warning(f"[{t}] 매수 트리거 발생하지만 잔고 부족: 필요 {one_amount:.0f}원, 보유 {krw_balance:.0f}원. 대기.")
                                continue
                            logger.info(f"[{t}] 가격 하락 조건 충족 -> 분할매수 실행 ({done+1}/{installments}) {one_amount:.0f} KRW")
                            resp = place_market_buy(t, one_amount)
                            if resp:
                                if isinstance(resp, dict):
                                    record_purchase_entry(t, resp)
                                    used_price = resp.get("price", None)
                                    if used_price is None:
                                        # if price absent, use cur_price and update triggers
                                        purchases = load_purchases()
                                        purchases[t]["last_buy_price"] = cur_price
                                        purchases[t]["next_buy_price"] = round(cur_price * (1.0 - drop_pct / 100.0), 8)
                                        save_purchases(purchases)
                                else:
                                    record_purchase_entry(t, {"result": str(resp), "krw": one_amount, "price": cur_price, "amount": None, "timestamp": datetime.utcnow().isoformat() + "Z"})
                                krw_balance -= one_amount
                                # 매수 직후 목표수익 달성 여부 확인(즉시 엑시트)
                                exit_ok, stats = should_exit(t)
                                if exit_ok and stats["held_amount"] > 0:
                                    sell_amount = stats["held_amount"] * SELL_FRACTION
                                    logger.info(f"[{t}] 매수 직후 목표 수익 달성 감지 -> 매도 시도 amt {sell_amount:.8f}")
                                    sell_resp = place_market_sell(t, sell_amount)
                                    if sell_resp:
                                        if isinstance(sell_resp, dict):
                                            record_sale_entry(t, sell_resp)
                                        else:
                                            record_sale_entry(t, {"result": str(sell_resp), "amount": sell_amount, "krw": sell_amount * (stats["current_price"] or 0), "timestamp": datetime.utcnow().isoformat() + "Z"})
                            time.sleep(0.5)
                        else:
                            logger.debug(f"[{t}] 아직 트리거 미충족.")
                    except Exception as e:
                        logger.error(f"[{t}] 모니터링/매수 처리 중 예외: {e}")
                        logger.debug(traceback.format_exc())
                logger.info(f"{MONITOR_INTERVAL_SEC}초 대기 후 상태 재확인")
                time.sleep(MONITOR_INTERVAL_SEC)
            except KeyboardInterrupt:
                logger.info("사용자 중단 (KeyboardInterrupt). 종료합니다.")
                return
            except Exception as e:
                logger.error(f"모니터링 루프 예외: {e}")
                logger.debug(traceback.format_exc())
                time.sleep(10)
    except KeyboardInterrupt:
        logger.info("사용자 중단 (KeyboardInterrupt). 종료합니다.")
    except Exception as e:
        logger.error(f"메인 예외: {e}")
        logger.debug(traceback.format_exc())

if __name__ == "__main__":
    main()
