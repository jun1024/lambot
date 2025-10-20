#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Upbit EMA Crossover Trading Bot (BTC/ETH/XRP)
- Strategy: 15min EMA(7) / EMA(25) crossover
- Uses pyupbit for Upbit Open API
- DRY_RUN=True: 시뮬레이션 모드 (실제 주문을 보내지 않음)
"""

import time
import os
import logging
from dotenv import load_dotenv
import pyupbit
import pandas as pd
from datetime import datetime
import traceback

# Load environment variables from .env (if exists)
load_dotenv()

# Configuration
COINS = ["KRW-BTC", "KRW-ETH", "KRW-XRP"]
INTERVAL = "minute15"
EMA_SHORT = 7
EMA_LONG = 25
SLEEP_SECONDS = 30  # 루프 대기 (초)
ALLOCATION_PER_TRADE = 0.1  # 매수 시 KRW 잔고의 몇 퍼센트로 매수할지 (예: 0.1 = 10%)
MIN_KRW_ORDER = 5000  # 업비트 최소원금 (KRW)
DRY_RUN = True if os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes") else False

# Load API keys (optional, 필요 시 .env에 설정)
ACCESS = os.getenv("UPBIT_ACCESS_KEY", "")
SECRET = os.getenv("UPBIT_SECRET_KEY", "")

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger("upbit-bot")

# Upbit client (only create if keys provided and not dry run)
if ACCESS and SECRET and not DRY_RUN:
    upbit = pyupbit.Upbit(ACCESS, SECRET)
    logger.info("Upbit client initialized (LIVE).")
else:
    upbit = None
    if DRY_RUN:
        logger.info("DRY_RUN mode enabled. No real orders will be placed.")
    else:
        logger.warning("API 키 없음 또는 DRY_RUN 모드가 켜져 있습니다. 시뮬레이션으로 동작합니다.")


def safe_get_ohlcv(ticker, interval=INTERVAL, count=100):
    """pyupbit.get_ohlcv 래퍼: 실패 시 재시도"""
    for attempt in range(3):
        try:
            df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
            if df is not None and len(df) >= EMA_LONG + 5:
                return df
        except Exception as e:
            logger.warning(f"get_ohlcv 실패 {ticker} attempt={attempt+1}: {e}")
        time.sleep(1 + attempt)
    return None


def calculate_emas(df, short=EMA_SHORT, long=EMA_LONG):
    closes = df['close']
    ema_short = closes.ewm(span=short, adjust=False).mean()
    ema_long = closes.ewm(span=long, adjust=False).mean()
    return ema_short, ema_long


def get_krw_balance():
    """KRW 잔고 조회"""
    if DRY_RUN or upbit is None:
        # 시뮬레이션: 환경변수 또는 100,000원으로 가정
        krw_sim = float(os.getenv("SIM_KRW_BALANCE", "100000"))
        return krw_sim
    try:
        balances = upbit.get_balances()
        for b in balances:
            if b['currency'] == 'KRW':
                return float(b['balance'])
    except Exception as e:
        logger.error(f"get_krw_balance error: {e}")
    return 0.0


def get_coin_balance(ticker):
    """코인(종목) 잔고 조회. ticker 예: 'KRW-BTC' -> currency 'BTC'"""
    currency = ticker.split("-")[1]
    if DRY_RUN or upbit is None:
        # 시뮬레이션: 0으로 시작
        return float(os.getenv(f"SIM_BAL_{currency}", "0"))
    try:
        balances = upbit.get_balances()
        for b in balances:
            if b['currency'] == currency:
                return float(b.get('balance', 0) or 0)
    except Exception as e:
        logger.error(f"get_coin_balance error: {e}")
    return 0.0


def place_market_buy(ticker, krw_amount):
    """시장가 매수"""
    krw_amount = float(krw_amount)
    if krw_amount < MIN_KRW_ORDER:
        logger.info(f"매수 금액 {krw_amount} KRW < 최소 {MIN_KRW_ORDER}원, 주문 취소")
        return None
    if DRY_RUN or upbit is None:
        logger.info(f"[DRY_RUN] BUY {ticker} KRW {krw_amount:.0f}")
        return {"result": "dry_run", "ticker": ticker, "krw": krw_amount}
    try:
        resp = upbit.buy_market_order(ticker, krw_amount)
        logger.info(f"BUY order placed: {resp}")
        return resp
    except Exception as e:
        logger.error(f"buy_market_order error: {e}")
        logger.debug(traceback.format_exc())
        return None


def place_market_sell(ticker, volume):
    """시장가 매도"""
    volume = float(volume)
    if DRY_RUN or upbit is None:
        logger.info(f"[DRY_RUN] SELL {ticker} Volume {volume}")
        return {"result": "dry_run", "ticker": ticker, "vol": volume}
    try:
        resp = upbit.sell_market_order(ticker, volume)
        logger.info(f"SELL order placed: {resp}")
        return resp
    except Exception as e:
        logger.error(f"sell_market_order error: {e}")
        logger.debug(traceback.format_exc())
        return None


def ticker_price(ticker):
    """현재가 조회"""
    try:
        ticker_info = pyupbit.get_orderbook(tickers=[ticker])
        if ticker_info and len(ticker_info) > 0:
            return float(ticker_info[0]['orderbook_units'][0]['ask_price'])
    except Exception as e:
        logger.warning(f"ticker_price error: {e}")
    return None


def main_loop():
    logger.info(f"Starting main loop. Coins: {COINS}, Interval: {INTERVAL}")
    last_signal = {t: None for t in COINS}  # 'buy'/'sell'/None
    while True:
        try:
            krw_balance = get_krw_balance()
            logger.info(f"KRW Balance: {krw_balance:.0f} KRW")

            for ticker in COINS:
                df = safe_get_ohlcv(ticker, interval=INTERVAL, count=EMA_LONG + 10)
                if df is None:
                    logger.warning(f"OHLCV data 가져올 수 없음: {ticker}")
                    continue

                ema_short, ema_long = calculate_emas(df, EMA_SHORT, EMA_LONG)
                # 현재와 이전의 EMA 값
                cur_short = ema_short.iloc[-1]
                cur_long = ema_long.iloc[-1]
                prev_short = ema_short.iloc[-2]
                prev_long = ema_long.iloc[-2]

                logger.info(f"{ticker} EMA{EMA_SHORT:.0f}:{cur_short:.1f} EMA{EMA_LONG:.0f}:{cur_long:.1f}")

                signal = None
                # 골든 크로스: 이전에는 short <= long, 현재 short > long
                if prev_short <= prev_long and cur_short > cur_long:
                    signal = "buy"
                # 데드 크로스: 이전에는 short >= long, 현재 short < long
                elif prev_short >= prev_long and cur_short < cur_long:
                    signal = "sell"

                # 상태 판단 및 주문
                if signal == "buy":
                    # 이미 포지션 있는지 확인
                    coin_bal = get_coin_balance(ticker)
                    logger.info(f"{ticker} 현재 코인잔고: {coin_bal}")
                    if coin_bal <= 0:
                        buy_krw = krw_balance * ALLOCATION_PER_TRADE
                        buy_krw = max(buy_krw, 0)
                        if buy_krw >= MIN_KRW_ORDER:
                            logger.info(f"{ticker} 매수 신호 감지 -> 매수 시도 KRW {buy_krw:.0f}")
                            place_market_buy(ticker, buy_krw)
                            last_signal[ticker] = "buy"
                        else:
                            logger.info(f"{ticker} 매수 신호였으나 매수금액 부족: {buy_krw:.0f} KRW")
                    else:
                        logger.info(f"{ticker} 이미 잔고가 있어 매수하지 않음 (잔고: {coin_bal})")
                elif signal == "sell":
                    coin_bal = get_coin_balance(ticker)
                    if coin_bal > 0:
                        # 자산 가치를 계산해 최소 주문 금액 확인
                        price = ticker_price(ticker) or df['close'].iloc[-1]
                        value_krw = coin_bal * price
                        if value_krw >= MIN_KRW_ORDER:
                            logger.info(f"{ticker} 매도 신호 감지 -> 전량 매도 시도 (수량 {coin_bal})")
                            place_market_sell(ticker, coin_bal)
                            last_signal[ticker] = "sell"
                        else:
                            logger.info(f"{ticker} 매도 가능하나 가치 {value_krw:.0f}원 < 최소 {MIN_KRW_ORDER}원, 매도하지 않음")
                    else:
                        logger.info(f"{ticker} 보유 없음, 매도 안함")
                else:
                    logger.debug(f"{ticker} 신호 없음")

                time.sleep(1)  # 여러 코인 조회 시 API 부하 완화

        except KeyboardInterrupt:
            logger.info("사용자 중단 (KeyboardInterrupt). 종료합니다.")
            break
        except Exception as e:
            logger.error(f"메인 루프 예외: {e}")
            logger.debug(traceback.format_exc())

        time.sleep(SLEEP_SECONDS)


if __name__ == "__main__":
    main_loop()