#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Upbit DCA (분할매수) Bot with Exit Target (BTC/ETH/XRP)
- Strategy: 분할매수 (DCA) + 목표 수익 달성 시 자동 청산(Exit)
- Target can be set as percent (TARGET_PROFIT_PCT) or absolute KRW (TARGET_PROFIT_KRW).
- SELL_FRACTION: 청산 시 매도할 비율 (기본 1.0 = 전량)
- DRY_RUN=True: 모의 모드 (기본)
- purchases.json에 진행상황 및 매수/매도 기록을 저장 (재시작 시 이어서 동작)
"""

import os
import time
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
import pyupbit
import traceback

load_dotenv()

# --- 설정 (환경변수로 오버라이드 가능) ---
COINS = ["KRW-BTC", "KRW-ETH", "KRW-XRP"]

# 분할매수 관련
INSTALLMENTS = int(os.getenv("INSTALLMENTS", "5"))           # 분할 수 (예: 5회)
INTERVAL_MIN = int(os.getenv("INTERVAL_MIN", "60"))          # 라운드 간격(분)
MIN_KRW_ORDER = int(os.getenv("MIN_KRW_ORDER", "5000"))      # 업비트 최소 주문금액(원)

# 자금 할당: 전체 KRW 잔고의 몇 %를 투입할지 (0.0 ~ 1.0) 또는 TOTAL_INVEST_KRW 사용
TOTAL_INVEST_FRACTION = float(os.getenv("TOTAL_INVEST_FRACTION", "0.5"))  # 기본 50% 사용
TOTAL_INVEST_KRW = os.getenv("TOTAL_INVEST_KRW", "")  # 지정하면 절대 KRW 값 사용 (문자열로 비워두면 무시)

# 코인별 비중(옵션). 예: "KRW-BTC:0.5,KRW-ETH:0.3,KRW-XRP:0.2"
ALLOCATIONS_ENV = os.getenv("ALLOCATIONS", "")  # 빈 문자열이면 균등 분배

# Exit(청산) 관련 설정
TARGET_PROFIT_PCT = os.getenv("TARGET_PROFIT_PCT", "")  # 예: "10" -> 10% 이익 시 매도
TARGET_PROFIT_KRW = os.getenv("TARGET_PROFIT_KRW", "")  # 예: "5000" -> 순이익 5,000원 이상 시 매도
SELL_FRACTION = float(os.getenv("SELL_FRACTION", "1.0"))  # 매도 시 전량:1.0, 절반:0.5 등
# purchases 기록 파일
PURCHASES_FILE = os.getenv("PURCHASES_FILE", "purchases.json")

# 실행 모드
DRY_RUN = True if os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes") else False

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

# 로깅
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("upbit-dca-exit-bot")

# --- 헬퍼 함수들 ---
def parse_allocations(env_str):
    if not env_str:
        return None
    try:
        parts = [p.strip() for p in env_str.split(",") if p.strip()]
        d = {}
        for p in parts:
            k, v = p.split(":")
            d[k.strip()] = float(v)
        return d
    except Exception:
        logger.warning("ALLOCATIONS 파싱 실패, 무시하고 균등 분배를 사용합니다.")
        return None

ALLOCATIONS = parse_allocations(ALLOCATIONS_ENV)

def load_purchases():
    if os.path.exists(PURCHASES_FILE):
        try:
            with open(PURCHASES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.warning("purchases.json 읽기 실패, 새로 생성합니다.")
    return {}

def save_purchases(data):
    try:
        with open(PURCHASES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"purchases.json 저장 실패: {e}")

def get_krw_balance():
    if DRY_RUN or upbit is None:
        # 시뮬레이션: SIM_KRW_BALANCE 환경변수가 있으면 사용, 없으면 100000원 기본
        sim = float(os.getenv("SIM_KRW_BALANCE", "100000"))
        return sim
    try:
        balances = upbit.get_balances()
        for b in balances:
            if b['currency'] == 'KRW':
                return float(b['balance'])
    except Exception as e:
        logger.error(f"KRW 잔고 조회 실패: {e}")
    return 0.0

def get_coin_balance(ticker):
    currency = ticker.split("-")[1]
    if DRY_RUN or upbit is None:
        purchases = load_purchases()
        if ticker in purchases:
            # purchases.json에 기록된 총 매수 수량 합에서 매도된 수량을 빼고 현재 보유량 계산
            total_bought = sum([it.get("amount", 0) for it in purchases[ticker].get("purchased", [])])
            total_sold = sum([it.get("amount", 0) for it in purchases[ticker].get("sold", [])])
            return float(max(0.0, total_bought - total_sold))
        return 0.0
    try:
        balances = upbit.get_balances()
        for b in balances:
            if b['currency'] == currency:
                return float(b.get('balance', 0) or 0)
    except Exception as e:
        logger.error(f"{ticker} 잔고 조회 실패: {e}")
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
    # value check
    price = ticker_price(ticker) or 0
    value_krw = amount * price
    if value_krw < MIN_KRW_ORDER:
        logger.info(f"[{ticker}] 매도 가치 {value_krw:.0f}원 < 최소 {MIN_KRW_ORDER}원, 매도 생략")
        return None

    if DRY_RUN or upbit is None:
        resp = {
            "result": "dry_run_sell",
            "ticker": ticker,
            "amount": amount,
            "price": price,
            "krw": value_krw,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        logger.info(f"[DRY_RUN] SELL {ticker} amt {amount:.8f} @ price {price} -> KRW {value_krw:.0f}")
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
            "target_krw": 0,
            "installments": INSTALLMENTS,
            "purchased": [],
            "sold": [],
            "completed": False,
            "exited": False
        }
    purchases[ticker]["purchased"].append(entry)
    # completed는 purchased 수로 판단 (installments와 비교)
    if len(purchases[ticker]["purchased"]) >= purchases[ticker].get("installments", INSTALLMENTS):
        purchases[ticker]["completed"] = True
    save_purchases(purchases)

def record_sale_entry(ticker, entry):
    purchases = load_purchases()
    if ticker not in purchases:
        purchases[ticker] = {
            "target_krw": 0,
            "installments": INSTALLMENTS,
            "purchased": [],
            "sold": [],
            "completed": False,
            "exited": False
        }
    purchases[ticker].setdefault("sold", []).append(entry)
    # 매도(Exit) 시 exited 플래그 설정
    purchases[ticker]["exited"] = True
    save_purchases(purchases)

def compute_allocations(total_krw):
    if ALLOCATIONS:
        # normalize allocations to sum=1
        total_frac = sum(ALLOCATIONS.get(t, 0) for t in COINS)
        allocs = {}
        for t in COINS:
            frac = ALLOCATIONS.get(t, 0) / total_frac if total_frac > 0 else 0
            allocs[t] = total_krw * frac
        return allocs
    # equal allocation
    per = total_krw / len(COINS) if len(COINS) > 0 else 0
    return {t: per for t in COINS}

def analyze_unrealized(ticker):
    """purchases.json 기반으로 코인의 평균매수가, 투자원금, 보유수량, 현재가, 미실현 손익(krw, pct)를 계산"""
    purchases = load_purchases().get(ticker, {})
    bought = purchases.get("purchased", [])
    total_amount = sum([it.get("amount", 0) for it in bought])
    total_spent = sum([it.get("krw", 0) for it in bought])
    # subtract sold amounts (already accounted in get_coin_balance but for profit calc we want realized/unrealized)
    sold = purchases.get("sold", [])
    total_sold_amount = sum([it.get("amount", 0) for it in sold])
    total_sold_krw = sum([it.get("krw", 0) for it in sold])
    # currently held amount
    held_amount = max(0.0, total_amount - total_sold_amount)
    current_price = ticker_price(ticker) or 0
    current_value = held_amount * current_price
    invested_for_held = 0.0
    # To estimate invested KRW corresponding to held amount, assume FIFO or proportional:
    # For simplicity, compute average buy price and multiply by held_amount
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
    """목표 수익 도달 여부 판단"""
    # parse targets
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
    # no holdings -> cannot exit
    if stats["held_amount"] <= 0 or stats["invested_for_held"] <= 0:
        return False, stats

    # check conditions
    if pct_target is not None and stats["unrealized_pct"] >= pct_target:
        return True, stats
    if krw_target is not None and stats["unrealized_krw"] >= krw_target:
        return True, stats
    return False, stats

def prepare_targets(total_krw):
    purchases = load_purchases()
    # compute per-coin fractions
    if ALLOCATIONS:
        total_frac = sum(ALLOCATIONS.get(t, 0) for t in COINS)
        fracs = {t: (ALLOCATIONS.get(t, 0) / total_frac) if total_frac > 0 else 0 for t in COINS}
    else:
        fracs = {t: 1.0 / len(COINS) for t in COINS}

    for t in COINS:
        target = total_krw * fracs.get(t, 0)
        if t not in purchases:
            purchases[t] = {
                "target_krw": float(target),
                "installments": INSTALLMENTS,
                "purchased": [],
                "sold": [],
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
    logger.info(f"Starting DCA+Exit bot ({client_mode}). Coins: {COINS}")
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

        logger.info(f"총투자금(분할 대상): {total_invest:.0f} KRW (INSTALLMENTS={INSTALLMENTS}, INTERVAL_MIN={INTERVAL_MIN}min)")
        if TARGET_PROFIT_PCT:
            logger.info(f"목표 수익률: {TARGET_PROFIT_PCT}% 이상이면 청산")
        if TARGET_PROFIT_KRW:
            logger.info(f"목표 이익(절대): {TARGET_PROFIT_KRW}원 이상이면 청산")
        logger.info(f"매도 시 비율 SELL_FRACTION={SELL_FRACTION}")

        purchases = prepare_targets(total_invest)

        # 각 코인별로 라운드마다 한 번씩 분할매수 시도
        while True:
            purchases = load_purchases()
            # If all completed OR exited, we move to monitoring
            all_done = all((purchases.get(t, {}).get("completed", False) or purchases.get(t, {}).get("exited", False)) for t in COINS)
            if all_done:
                logger.info("모든 코인의 분할매수가 완료 또는 청산되었습니다. 모니터링 모드로 전환합니다.")
                break

            krw_balance = get_krw_balance()
            logger.info(f"라운드 시작 — 현재 KRW 잔고: {krw_balance:.0f}원")
            for t in COINS:
                try:
                    entry = purchases.get(t, {})
                    if entry.get("exited", False):
                        logger.info(f"[{t}] 이미 청산(exited) 상태. 스킵.")
                        continue
                    completed = entry.get("completed", False)
                    target = float(entry.get("target_krw", 0))
                    installments = int(entry.get("installments", INSTALLMENTS))
                    done = len(entry.get("purchased", []))
                    remaining = installments - done
                    if completed:
                        logger.info(f"[{t}] 분할매수 완료(installments). 스킵.")
                        continue
                    if remaining <= 0:
                        purchases[t]["completed"] = True
                        save_purchases(purchases)
                        logger.info(f"[{t}] 완료로 표시.")
                        continue

                    # 이번 라운드에서 매수할 1회분 금액 = target / installments
                    one_amount = target / installments if installments > 0 else 0
                    # 최소주문보다 작다면 해당 코인 전체 분할을 스킵
                    if one_amount < MIN_KRW_ORDER:
                        logger.info(f"[{t}] 1회분 금액 {one_amount:.0f}원 < 최소 {MIN_KRW_ORDER}원. 이 코인은 자동으로 스킵됩니다.")
                        purchases[t]["completed"] = True
                        save_purchases(purchases)
                        continue

                    # 잔고가 부족하면 스킵
                    if krw_balance < one_amount:
                        logger.warning(f"[{t}] 잔고 부족: 필요 {one_amount:.0f}원, 보유 {krw_balance:.0f}원. 다음 라운드에서 재시도.")
                        continue

                    logger.info(f"[{t}] 분할매수 시도 ({done+1}/{installments}) -> {one_amount:.0f} KRW")
                    resp = place_market_buy(t, one_amount)
                    if resp:
                        # 기록
                        if isinstance(resp, dict):
                            record_purchase_entry(t, resp)
                        else:
                            record_purchase_entry(t, {"result": str(resp), "krw": one_amount, "timestamp": datetime.utcnow().isoformat() + "Z"})
                        # 잔고 갱신 (간단히 차감)
                        krw_balance -= one_amount

                    # 매수 직후 목표수익 달성 여부 확인 -> 즉시 매도(엑시트) 가능
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
                    # API 부하 완화
                    time.sleep(1)
                except Exception as e:
                    logger.error(f"[{t}] 분할매수 처리 중 예외: {e}")
                    logger.debug(traceback.format_exc())

            logger.info(f"라운드 종료 — 다음 라운드까지 {INTERVAL_MIN}분 대기")
            time.sleep(INTERVAL_MIN * 60)

        # 완료 후 모니터링 루프: 주기적으로 목표 달성 시 자동 청산 수행
        logger.info("모니터링 루프 시작. 보유 잔고/현재가/목표 달성 여부를 주기적으로 확인합니다.")
        while True:
            try:
                for t in COINS:
                    try:
                        # skip if already exited
                        purchases = load_purchases()
                        if purchases.get(t, {}).get("exited", False):
                            logger.info(f"[{t}] 이미 청산됨 (exited).")
                            continue
                        stats = analyze_unrealized(t)
                        logger.info(f"[보유] {t} 잔고: {stats['held_amount']:.8f}, 현재가: {stats['current_price']:.0f}, 가치: {stats['current_value']:.0f} KRW, 미실현: {stats['unrealized_krw']:.0f} KRW ({stats['unrealized_pct']:.2f}%)")
                        exit_ok, stats = should_exit(t)
                        if exit_ok and stats["held_amount"] > 0:
                            sell_amount = stats["held_amount"] * SELL_FRACTION
                            logger.info(f"[{t}] 목표 수익 조건 충족 -> 매도 시도 amt {sell_amount:.8f}")
                            sell_resp = place_market_sell(t, sell_amount)
                            if sell_resp:
                                if isinstance(sell_resp, dict):
                                    record_sale_entry(t, sell_resp)
                                else:
                                    record_sale_entry(t, {"result": str(sell_resp), "amount": sell_amount, "krw": sell_amount * (stats["current_price"] or 0), "timestamp": datetime.utcnow().isoformat() + "Z"})
                    except Exception as e:
                        logger.error(f"[{t}] 모니터링 중 예외: {e}")
                        logger.debug(traceback.format_exc())
                    time.sleep(0.5)
                sleep_min = int(os.getenv("MONITOR_INTERVAL_MIN", "60"))
                logger.info(f"{sleep_min}분 대기 후 다시 상태 확인")
                time.sleep(sleep_min * 60)
            except KeyboardInterrupt:
                logger.info("사용자 중단 (KeyboardInterrupt). 종료합니다.")
                return
            except Exception as e:
                logger.error(f"모니터링 루프 예외: {e}")
                logger.debug(traceback.format_exc())
                time.sleep(30)

    except KeyboardInterrupt:
        logger.info("사용자 중단 (KeyboardInterrupt). 종료합니다.")
    except Exception as e:
        logger.error(f"메인 예외: {e}")
        logger.debug(traceback.format_exc())

if __name__ == "__main__":
    main()