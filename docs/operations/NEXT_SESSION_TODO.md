# 다음 세션 작업 계획

**생성일**: 2025-11-19 18:00
**봇 상태**: Running (PID 27762)

---

## 🎯 즉시 확인할 사항

### 1. 봇이 여전히 실행 중인가?
```bash
# PID 확인
cat tradingbot.pid

# 프로세스 확인
ps -p $(cat tradingbot.pid) -o pid,stat,command

# 최근 로그 확인
tail -30 logs/tradingbot_final.log
```

### 2. 에러 발생 여부 확인
```bash
# CandleStorage 타입 에러 개수 확인
grep "'list' object has no attribute 'empty'" logs/tradingbot_final.log | wc -l

# 최근 에러만 확인
tail -100 logs/tradingbot_final.log | grep ERROR
```

---

## 🔥 우선순위 HIGH - 해야 할 작업

### Issue #3: CandleStorage DataFrame/List 타입 불일치 수정

**에러**:
```
AttributeError: 'list' object has no attribute 'empty'
File: src/services/strategy/integration_layer.py:220
```

**조사 단계**:
1. CandleStorage.get_candles() 메서드 분석
   ```bash
   # 파일 찾기
   find . -name "candle_storage.py" -type f

   # get_candles 메서드 확인
   grep -A30 "def get_candles" src/services/candle_storage.py
   ```

2. 반환 타입 확인
   - DataFrame을 반환하는가?
   - List를 반환하는가?
   - 조건에 따라 다른가?

3. 수정 방법 결정
   - **Option A**: CandleStorage.get_candles()를 DataFrame 반환하도록 수정
   - **Option B**: integration_layer.py에서 list 처리하도록 수정

**예상 작업 시간**: 30-60분

---

## 📋 우선순위 MEDIUM - 계획된 작업

### 1. Position Monitoring Task 구현
**위치**: `src/core/orchestrator.py` (주석으로 템플릿 존재)

**작업**:
- 주석 처리된 position monitoring 코드 활성화
- Background task로 등록
- 테스트 및 검증

**예상 시간**: 1-2시간

---

### 2. Configuration 파일 지원
**목표**: 하드코딩된 설정 제거

**작업**:
- `config.yaml` 또는 `.env`에 다음 추가:
  - `TRADING_SYMBOLS`: ["BTCUSDT", "ETHUSDT"]
  - `TIMEFRAMES`: ["1m", "5m", "15m"]
  - `MAX_SYMBOLS`: 5
- orchestrator.py 수정하여 config에서 로드
- 검증

**예상 시간**: 1시간

---

### 3. 24시간 안정성 모니터링
**작업**:
- 봇을 24시간 실행
- 주기적 상태 체크 (매 6시간)
- Memory leak 체크
- WebSocket reconnection 테스트
- 성능 metrics 수집

**모니터링 명령어**:
```bash
# 메모리 사용량 확인
ps -p $(cat tradingbot.pid) -o pid,vsz,rss,pmem,command

# 로그 크기 확인
ls -lh logs/

# 실시간 모니터링
watch -n 60 'ps -p $(cat tradingbot.pid) -o pid,stat,time,rss && tail -5 logs/tradingbot_final.log'
```

---

## 🌟 우선순위 LOW - 향후 작업

### 1. 다중 Symbol 테스트
- ETHUSDT 추가
- BNBUSDT 추가
- Multi-symbol 동시 처리 검증

### 2. Performance Metrics 수집
- Trade execution time
- Indicator calculation time
- Memory usage trends
- WebSocket latency

---

## 📚 참고 문서

### 이번 세션 작업 내역
- **세션 기록**: `.serena/memories/trading_bot_session_2025-11-19.md`
- **메인 상태**: `docs/operations/mainnet_status_2025-11-18.md`

### 이전 세션 문서
- **Background Task 분석**: `docs/operations/background_task_analysis_2025-11-19.md`
- **Task Registration 구현**: `docs/operations/implementation_task_registration_2025-11-19.md`

### 수정된 파일 (Git 미커밋)
```bash
# 변경 사항 확인
git status

# 수정된 파일:
# - src/core/orchestrator.py (5m timeframe 추가)
# - src/services/strategy/integration_layer.py (import 수정)
```

---

## 🚀 빠른 시작 가이드

### 봇 재시작 필요 시
```bash
# 기존 봇 종료
kill -TERM $(cat tradingbot.pid)

# Python 캐시 클리어
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete 2>/dev/null

# 재시작 (bytecode 생성 안함)
PYTHONDONTWRITEBYTECODE=1 python3 -m src > logs/tradingbot_current.log 2>&1 &
echo $! > tradingbot.pid

# 시작 확인
sleep 5
tail -50 logs/tradingbot_current.log | grep -E "(Started|ERROR)"
```

### 디버깅 팁
```bash
# 에러만 필터링
grep ERROR logs/tradingbot_final.log | tail -20

# 특정 에러 검색
grep "AttributeError" logs/tradingbot_final.log | wc -l

# 5m candle 처리 확인
grep "Processing 5m" logs/tradingbot_final.log | tail -10

# Indicator 계산 확인
grep "Updated.*indicators" logs/tradingbot_final.log | tail -10
```

---

## ✅ 이번 세션 완료 사항

1. ✅ 5m Timeframe 설정 오류 수정
2. ✅ Strategy Layer Import 오류 수정
3. ✅ 모든 timeframe 데이터 처리 검증
4. ✅ 문서화 완료

---

**다음 세션 시작 시**:
1. 이 문서 읽기
2. 봇 상태 확인
3. Issue #3 (CandleStorage 타입) 작업 시작
