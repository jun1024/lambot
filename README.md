# PAMT

설명
- Upbit(업비트) 마켓을 대상으로 동작하는 예제 자동매매(트레이딩) 봇 모음입니다.
- 본 저장소에는 여러 전략 예제가 포함되어 있으며, 현재 기본 제공 예제는 분할매수(DCA) 기반의 "가격 하락 트리거" 전략(Drop-Buy) + 목표 수익 자동 청산(Exit) 기능입니다.
- pyupbit 라이브러리를 사용하여 업비트 Open API와 통신합니다.
- 대상 코인 예시: KRW-BTC, KRW-ETH, KRW-XRP (코드 상단의 COINS 변수로 관리)

주요 기능(현 시점)
- 분할매수(DCA, Installments)
  - 각 코인별 목표 투자금(target_krw)을 INSTALLMENTS 회수로 분할하여 매수합니다.
  - 초기 매수(Initial Buy)를 수행할지 여부 설정 가능.
- 가격 하락 트리거(Deep/Drop Buying)
  - 마지막 매수 가격에서 지정한 비율(DROP_PCT 또는 코인별 DROP_PCT_PER_COIN)만큼 하락할 때마다 다음 분할매수를 실행합니다.
  - 코인별로 개별 DROP_PCT을 지정할 수 있어 유연한 분할매수 트리거 설정이 가능합니다.
- 코인별 비중 지정(ALLOCATIONS)
  - ALLOCATIONS 환경변수로 코인별 비중을 퍼센트(예: 50,30,20) 또는 분수(예: 0.5,0.3,0.2) 형태로 직접 지정 가능.
  - 일부만 지정하면 나머지 코인은 자동으로 잔여 비중을 분배하여 합이 1.0이 되도록 정규화합니다.
- 목표 수익 청산(Exit)
  - TARGET_PROFIT_PCT(%) 또는 TARGET_PROFIT_KRW(절대 KRW) 중 하나 이상을 설정하면 해당 기준을 만족할 때 자동으로 설정한 비율(SELL_FRACTION)만큼 시장가로 매도합니다.
  - 매수/매도 기록은 purchases.json에 저장되어 재시작 시에도 진행 상태를 이어갑니다.
- DRY_RUN(모의) 모드 지원
  - 기본적으로 .env의 DRY_RUN=true로 설정되어 있어 실제 주문이 발생하지 않습니다. 실거래 전 반드시 DRY_RUN 상태로 충분히 테스트하세요.

사전 준비
1. Python 3.8+ 권장
2. 의존성 설치:
   ```
   pip install -r requirements.txt
   ```
3. 업비트 Open API 키 발급:
   - 업비트에서 Access Key / Secret Key 발급 후 `.env` 파일에 입력하세요.

파일 요약
- bot_dca_drop_on_drop.py : 가격 하락 트리거 기반 DCA + Exit(청산) 전략 메인 코드
- purchases.json : 실행 시 생성/갱신 — 매수/매도 기록과 트리거(마지막 매수가격/다음 매수가격) 저장
- requirements.txt : pyupbit, python-dotenv 등 의존성
- .env : 실행 설정 및 민감정보(예: API 키)

설정 (.env) 예시
- 프로젝트 루트에 `.env` 파일을 생성하고 아래 예시를 참고해 값을 채워 넣으세요.

```text
# Upbit API 키 (실거래 시 필수)
UPBIT_ACCESS_KEY=your_access_key_here
UPBIT_SECRET_KEY=your_secret_key_here

# DRY_RUN=true -> 실제 주문을 보내지 않습니다. 실거래로 전환하려면 false로 변경하세요.
DRY_RUN=true

# DRY_RUN일 때 사용할 시뮬레이션 KRW 잔고
SIM_KRW_BALANCE=100000

# 분할매수 관련
INSTALLMENTS=5                # 각 코인별 총 분할 매수 횟수
MIN_KRW_ORDER=5000            # 업비트 최소 주문금액(원)

# 자금 할당: 총 보유 KRW의 몇 퍼센트를 투자할지 (0.0 ~ 1.0)
TOTAL_INVEST_FRACTION=0.5

# 또는 절대 금액을 사용하려면 아래 주석 해제하고 숫자 입력
# TOTAL_INVEST_KRW=100000

# 코인별 분할매수 비중 (퍼센트 또는 소수 형태 허용)
# 예(퍼센트): ALLOCATIONS="KRW-BTC:50,KRW-ETH:30,KRW-XRP:20"
# 예(분수) : ALLOCATIONS="BTC:0.5,ETH:0.3,XRP:0.2"
# 빈 값이면 균등 분배 사용
ALLOCATIONS=KRW-BTC:50,KRW-ETH:30,KRW-XRP:20

# 전역 가격 하락 트리거 (퍼센트, 예: 2.0 -> 2% 하락시 매수)
DROP_PCT=2.0

# 코인별 DROP_PCT을 개별로 지정하려면 아래와 같이 설정하세요.
# 일부만 지정하면 지정되지 않은 코인은 전역 DROP_PCT 값을 사용합니다.
# 형식: DROP_PCT_PER_COIN="KRW-BTC:2,ETH:3,XRP:5" 또는 "BTC:2,ETH:3,XRP:5"
DROP_PCT_PER_COIN=KRW-BTC:2,KRW-ETH:3,KRW-XRP:5

# 초기 매수 여부: 시작 시 1회분을 바로 매수할지 (true/false)
INITIAL_BUY=true

# 모니터링 주기 (분)
MONITOR_INTERVAL_MIN=5
# 또는 초 단위로 직접 설정하려면 MONITOR_INTERVAL_SEC 사용 (선택)
# MONITOR_INTERVAL_SEC=300

# Exit(청산) 관련: 목표 수익률 또는 절대 KRW 이익
TARGET_PROFIT_PCT=10
# TARGET_PROFIT_KRW=5000

# 매도 시 매도 비율 (1.0 = 전량 매도, 0.5 = 절반 매도 등)
SELL_FRACTION=1.0

# 진행 기록 파일명 (purchases.json 기본)
PURCHASES_FILE=purchases.json
```

사용 방법 (간단)
1. 의존성 설치:
   ```
   pip install -r requirements.txt
   ```
2. .env 파일을 생성하고 설정을 채웁니다. 기본적으로 DRY_RUN=true로 두고 테스트하세요.
3. 실행:
   ```
   python bot_dca_drop_on_drop.py
   ```
   - DRY_RUN=true인 경우 purchases.json에 시뮬레이션 기록이 남습니다.
   - 실거래로 전환하려면 UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY를 설정하고 DRY_RUN=false로 변경한 뒤 소액으로 충분히 테스트하세요.

purchases.json 구조(요약)
- 각 티커별로 아래와 같은 정보가 저장됩니다:
  - target_krw : 코인별 목표 투자금
  - installments : 분할 횟수
  - purchased : 매수 기록 배열 (각 항목: krw, price, amount, timestamp)
  - sold : 매도 기록 배열
  - last_buy_price : 가장 최근 매수 단가 (트리거 산출용)
  - next_buy_price : 다음 매수 트리거 가격
  - completed : 분할매수 완료 여부
  - exited : 목표 달성으로 청산 완료 여부

설계/동작 원리(요약)
- 총투자금(total_invest)은 잔고 * TOTAL_INVEST_FRACTION 또는 TOTAL_INVEST_KRW로 결정됩니다.
- ALLOCATIONS 비중에 따라 코인별 target_krw를 계산하고, one_amount = target_krw / INSTALLMENTS 로 각 회차 매수 금액을 설정합니다.
- INITIAL_BUY가 true면 각 코인에 대해 1회분을 즉시 매수(가능한 경우)하고, 그 가격을 기준으로 다음 매수 트리거(next_buy_price)를 last_buy_price * (1 - DROP_PCT/100)로 설정합니다. (코인별 DROP_PCT가 지정된 경우 해당 값 사용)
- 모니터링 루프에서 현재가가 next_buy_price 이하로 내려가면 해당 코인의 한 회분을 시장가로 매수하고, last_buy_price/next_buy_price를 갱신합니다.
- 매수 직후 및 모니터링 주기마다 should_exit()로 미실현 손익을 계산하여 TARGET_PROFIT_PCT 또는 TARGET_PROFIT_KRW 조건을 만족하면 SELL_FRACTION만큼 시장가로 매도하고 exited=True로 표시합니다.

주의사항(중요)
- 이 코드는 예제/학습용이며, 실제 투자에 따른 손실 책임은 사용자 본인에게 있습니다.
- 실거래 전 반드시 DRY_RUN=true 모드에서 충분히 테스트하세요.
- 업비트의 최소 주문단위, 수수료, 슬리피지, API 호출 제한 등에 따른 실패/예외 처리를 코드에 추가하는 것을 권장합니다.
- purchases.json 파일을 직접 편집하지 마세요. 데이터 무결성이 손상될 수 있습니다.
- 자동매매는 큰 손실을 초래할 수 있습니다. 작게 테스트하고 단계적으로 적용하세요.

권장 개선 및 확장 아이디어
- 코인별로 매수 금액을 하락폭에 따라 가변화(더 깊은 하락 시 더 많은 금액 구매)하는 스케일-인 로직 추가
- 텔레그램/슬랙/이메일 알림(매수/매도/오류 알림)
- 백테스트/시뮬레이션 모듈(과거 데이터로 분할매수+청산 시뮬레이션)
- 부분매도, 목표별 분할 청산 전략(예: 목표 도달 시 30% 매도 등)
- 더 정교한 잔고 관리(실시간 잔고 확인, 주문 실패 시 재시도 및 롤백)

참고
- Upbit Open API 문서: https://docs.upbit.com
- pyupbit: https://github.com/sharebook-kr/pyupbit

라이선스
- 본 프로젝트는 학습/예제용이며 별도의 라이선스 정책이 없으므로, 사용 시 출처 표기와 함께 자유롭게 참고하셔도 됩니다.