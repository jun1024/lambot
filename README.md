```markdown
# PAMT — Web Dashboard Extension

이 프로젝트에 웹 기반 대시보드(Flask)를 추가했습니다. 대시보드는 .env 환경변수 편집, 봇 시작/중지, 실시간 로그 스트리밍(SSE), purchases.json 미리보기/다운로드 기능을 제공합니다.

빠른 시작
1. 의존성 설치
   ```
   pip install -r requirements.txt
   ```
2. 파일 위치 확인
   - bot_dca_drop_on_drop.py (또는 사용중인 봇 스크립트)와 app.py, templates/, static/이 동일한 프로젝트 루트에 있어야 합니다.
3. 실행
   ```
   python app.py
   ```
4. 브라우저에서 열기
   - http://127.0.0.1:5000

주요 기능
- 웹에서 .env를 편집하고 저장
- Start / Stop 버튼으로 봇 실행 제어 (서브프로세스로 실행)
- 실시간 로그 스트리밍 (SSE) — 로그는 bot stdout/stderr를 캡처하여 표시합니다
- purchases.json 미리보기 및 다운로드
- 기본값으로 DRY_RUN=true 권장

보안 & 운영 주의
- 이 대시보드는 로컬/개인 환경에서의 실험용입니다. 프로덕션으로 배포하려면 인증(로그인), HTTPS, API 키 암호화/비밀관리, CSRF 방지 등 보안 조치가 필요합니다.
- bot 실행은 로컬 파이썬 프로세스로 수행됩니다. 호스트 시스템의 자원, 프로세스 권한 등에 주의하세요.
- DRY_RUN=true 상태에서 충분히 테스트한 다음 UPBIT_ACCESS_KEY/UPBIT_SECRET_KEY를 설정해 실거래로 전환하세요.

확장 아이디어
- 웹에서 COINS 리스트 편집 기능 추가
- 텔레그램/슬랙 알림 설정 UI
- 백테스팅 결과 표시
- 사용자 인증 및 원격 배포 (Docker + nginx + gunicorn)

파일 목록 (추가된/중요)
- app.py — Flask 웹 대시보드 실행기
- templates/index.html — 대시보드 UI
- static/style.css — 간단한 스타일
- requirements.txt — Flask 포함 의존성

참고
- 기존 README의 내용(전략 설명, 위험 고지 등)은 유지하세요. 이 웹 대시보드는 운영 편의성을 위한 도구이며, 전략/리스크 관리는 코드 레벨에서 신중하게 점검해야 합니다.
```