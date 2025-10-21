# PAMT (Python Automated Market Trader)

간단 설명
- PAMT는 Upbit(KRW 마켓)를 대상으로 동작하는 학습/예제용 자동매매 도구 모음입니다.
- 현재 제공되는 주요 전략:
  1. 분할매수(DCA, Installments) 기반의 "가격 하락 트리거(Drop-Buy)"
  2. 목표 수익 도달 시 자동 청산(Exit)
- pyupbit 라이브러리를 사용하여 Upbit Open API와 통신합니다.
- 예시 대상 코인: KRW-BTC, KRW-ETH, KRW-XRP (코드 상단의 `COINS` 변수로 변경 가능)

주요 기능 요약
- 분할매수(DCA)
  - 총투자금(total_invest)을 남은 분할 회차 수로 나누어 동적으로 매수 금액을 계산합니다.
  - `INITIAL_BUY` 옵션으로 시작 시 1회분 매수 가능.
- 가격 하락 트리거 (Drop-Buy)
  - 마지막 매수가에서 지정한 퍼센트(`DROP_PCT`)만큼 하락하면 다음 분할매수 실행.
  - 코인별로 개별 트리거 설정 가능: `DROP_PCT_PER_COIN`.
- 자동 매수 우선순위
  - 가격 하락 트리거가 충족되는 코인부터 순차적으로 매수하여, 별도 비중 설정 없이 예산을 활용합니다.
- 목표 수익 청산(Exit)
  - `TARGET_PROFIT_PCT`(%) 또는 `TARGET_PROFIT_KRW`(절대값)으로 청산 조건 설정.
  - `SELL_FRACTION`으로 매도 비율(전량/부분)을 지정.
- 상태/기록
  - `purchases.json`에 매수/매도 기록, 트리거 가격, 완료/청산 상태를 저장하여 재시작 시 이어서 동작.
- 실행 환경
  - 기본적으로 `DRY_RUN=true`로 동작(모의). 실제 주문 전 반드시 충분한 테스트 권장.
- 운영 도구
  - 메인 봇 스크립트: `bot_dca_exit.py` (분할매수 + Exit 통합 버전)
  - 로컬 GUI: `gui.py` (tkinter 기반) — .env 편집, 시작/중지, 로그 보기
  - 웹 대시보드: `app.py` (Flask) — .env 편집/저장, 시작/중지, 실시간 로그(SSE), purchases.json 미리보기/다운로드

설치 (로컬)
1. Python 3.8+ 권장
2. 의존성 설치:
   ```
   pip install -r requirements.txt
   ```
   - GUI만 사용 시 tkinter는 기본 포함되어 있어 별도 설치 불필요.
   - 웹 대시보드는 Flask와 python-dotenv가 필요합니다 (requirements.txt 포함).

환경 변수 (.env)
- 프로젝트 루트에 `.env` 파일을 생성하여 설정합니다. 주요 변수 예시:
  ```
  UPBIT_ACCESS_KEY=your_access_key_here
  UPBIT_SECRET_KEY=your_secret_key_here
  DRY_RUN=true
  SIM_KRW_BALANCE=100000
  INSTALLMENTS=5
  MIN_KRW_ORDER=5000
  TOTAL_INVEST_FRACTION=0.5
  # TOTAL_INVEST_KRW=100000
  DROP_PCT=2.0
  DROP_PCT_PER_COIN=KRW-BTC:2,KRW-ETH:3,KRW-XRP:5
  INITIAL_BUY=true
  MONITOR_INTERVAL_MIN=5
  TARGET_PROFIT_PCT=10
  # TARGET_PROFIT_KRW=5000
  SELL_FRACTION=1.0
  PURCHASES_FILE=purchases.json
  ```
- `.env.example` 또는 GUI/웹 대시보드에서 템플릿을 불러와 편집하세요.

빠른 사용법 (CLI)
1. `.env` 설정 (`DRY_RUN=true` 권장)
2. 봇 실행:
   ```
   python bot_dca_exit.py
   ```
3. 로그/진행 상황은 콘솔과 `purchases.json`에서 확인.

GUI (로컬)
1. `gui.py` 실행:
   ```
   python gui.py
   ```
2. 데스크탑 환경에서 .env 편집, 봇 시작/중지, 실시간 로그 확인 가능.

웹 대시보드
1. `app.py` 실행:
   ```
   python app.py
   ```
2. 브라우저에서 `http://127.0.0.1:5000` 접속
3. .env 편집, Start/Stop, 실시간 로그(SSE), purchases.json 미리보기 및 다운로드 가능

purchases.json 구조 (요약)
- 각 티커 키 아래 예:
  ```json
  "KRW-BTC": {
    "installments": 5,
    "purchased": [
      {"krw": 20000, "price": 50000000, "amount": 0.0004, "timestamp": "..."},
      ...
    ],
    "sold": [...],
    "last_buy_price": 48000000,
    "next_buy_price": 47040000,
    "completed": false,
    "exited": false
  }
  ```
- 전체 예산과 잔여 회차는 저장된 매수 기록을 기반으로 동적으로 계산되며, `target_krw` 필드를 사용하지 않습니다.
- 파일을 직접 편집하지 마세요. 무결성 보장을 위해 프로그램에서 관리됩니다.

안전 및 주의사항 (중요)
- 이 코드는 예제/학습용입니다. 실제 매매 시 손실 책임은 사용자에게 있습니다.
- 실거래 전 반드시 `DRY_RUN=true`로 충분히 테스트하세요.
- 거래소의 최소 주문 단위, 수수료, 슬리피지, API 호출 제한 등을 고려한 추가 예외 처리/재시도 로직을 권장합니다.
- 웹 대시보드는 기본적으로 인증/암호화 미지원입니다. 로컬에서만 사용하거나 별도 인증/HTTPS 적용 후 공개 배포하세요.
- `purchases.json` 또는 `.env` 파일에 민감정보(특히 API 키)를 안전하게 관리하세요.

개선 및 확장 아이디어
- 하락폭에 비례해 매수 금액을 가중 조정하는 스케일-인 로직
- 코인별 서로 다른 `DROP_PCT`, `TARGET` 설정을 UI에서 직접 편집
- 텔레그램/슬랙 알림, 이메일 알림 연동
- 백테스트 기능(과거 데이터 기반 시뮬레이션)
- 부분매도(목표 도달 시 일부 매도) 및 리밸런싱

참고
- Upbit Open API 문서: https://docs.upbit.com
- pyupbit: https://github.com/sharebook-kr/pyupbit

라이선스
- 학습/예제 목적의 코드입니다. 사용 시 출처 표기권장. 상업적 사용 등은 별도 검토하세요.