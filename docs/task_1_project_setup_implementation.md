# Task 1: 프로젝트 환경 설정 및 기본 구조 구축

**Status**: ✅ Complete
**Date Completed**: 2024-10-19
**Priority**: High
**Complexity**: 3/10

## Overview

Python 기반 트레이딩 봇 프로젝트의 초기 환경 설정 및 기본 디렉토리 구조를 구축했습니다. 가상환경 생성, 의존성 관리 시스템 설정, 환경 변수 구성, 프로젝트 메타 파일 작성을 포함하여 개발 환경의 기반을 완성했습니다.

## Subtasks Completed

### 1.1 Python 가상환경 및 프로젝트 구조 생성

**구현 내용**:
- Python 3.9+ 가상환경 생성 및 활성화
- 표준 프로젝트 디렉토리 구조 생성

**디렉토리 구조**:
```
tradingbot/
├── src/                    # 소스 코드 (패키지 루트)
│   ├── core/              # 핵심 유틸리티
│   ├── services/          # 비즈니스 로직
│   ├── indicators/        # ICT 지표 엔진
│   ├── strategies/        # 거래 전략
│   ├── database/          # 데이터베이스 모델
│   └── api/               # API 엔드포인트
├── tests/                 # 테스트 코드
│   ├── unit/             # 단위 테스트
│   ├── integration/      # 통합 테스트
│   └── fixtures/         # 테스트 픽스처
├── config/                # 설정 파일
├── data/                  # 데이터 파일 (SQLite DB, 로그)
├── docs/                  # 문서
├── scripts/               # 유틸리티 스크립트
├── examples/              # 예제 코드
└── alembic/              # 데이터베이스 마이그레이션
```

**기술 결정**:
- `src/` 레이아웃 사용으로 패키지 임포트 문제 방지
- 도메인별 모듈 분리로 확장성 확보
- 테스트 디렉토리를 프로젝트 루트에 배치하여 명확한 분리

### 1.2 의존성 관리 및 pyproject.toml 설정

**구현 내용**:
- `pyproject.toml`을 통한 현대적인 Python 프로젝트 설정
- 핵심 및 개발 의존성 정의
- 코드 품질 도구 설정

**주요 의존성** (`pyproject.toml:26-42`):
```toml
dependencies = [
    "aiohttp>=3.9.0",           # 비동기 HTTP 클라이언트
    "ccxt>=4.1.0",              # 거래소 API 통합
    "fastapi>=0.104.0",         # API 서버
    "uvicorn[standard]>=0.24.0", # ASGI 서버
    "python-dotenv>=1.0.0",     # 환경 변수 관리
    "discord-webhook>=1.3.0",   # Discord 알림
    "pydantic>=2.5.0",          # 데이터 검증
    "pandas>=2.1.0",            # 데이터 분석
    "numpy>=1.26.0",            # 수치 계산
    "ta-lib>=0.4.28",           # 기술 분석
    "sqlalchemy>=2.0.0",        # ORM
    "aiosqlite>=0.19.0",        # 비동기 SQLite
    "alembic>=1.13.0",          # DB 마이그레이션
]
```

**개발 의존성** (`pyproject.toml:44-53`):
```toml
dev = [
    "pytest>=7.4.0",            # 테스트 프레임워크
    "pytest-asyncio>=0.21.0",   # 비동기 테스트
    "pytest-cov>=4.1.0",        # 코드 커버리지
    "black>=23.11.0",           # 코드 포맷터
    "flake8>=6.1.0",            # Linter
    "mypy>=1.7.0",              # 타입 체커
    "isort>=5.12.0",            # Import 정렬
]
```

**코드 품질 설정**:

**Black** (`pyproject.toml:66-83`):
- 라인 길이: 100자
- Python 3.9-3.11 타겟팅
- 표준 디렉토리 제외 (.eggs, .git, .venv 등)

**isort** (`pyproject.toml:85-92`):
- Black 프로필 사용 (호환성)
- 라인 길이: 100자
- Multi-line import 스타일 3

**mypy** (`pyproject.toml:94-111`):
- Strict 타입 체킹 활성화
- 타입되지 않은 정의/호출 금지
- 외부 패키지 타입 무시 (ccxt, discord_webhook)

**pytest** (`pyproject.toml:113-132`):
- 비동기 자동 모드
- 코드 커버리지 자동 생성
- 테스트 마커: unit, integration, slow

### 1.3 환경 변수 및 설정 파일 구성

**구현 내용**:
- `.env.example` 템플릿 파일 생성
- 모든 설정 항목에 대한 명확한 문서화
- 개발/프로덕션 환경 분리 지원

**환경 변수 카테고리** (`.env.example`):

**1. Binance API 설정** (Lines 6-10):
```bash
BINANCE_API_KEY="your_binance_api_key_here"
BINANCE_SECRET_KEY="your_binance_secret_key_here"
BINANCE_TESTNET=true  # 테스트넷/메인넷 전환
```

**2. 거래 설정** (Lines 13-18):
```bash
TRADING_MODE="paper"                        # paper/live 모드
TRADING_DEFAULT_LEVERAGE=10                 # 레버리지 (1-125)
TRADING_MAX_POSITION_SIZE_USDT=1000.0      # 최대 포지션 크기
TRADING_RISK_PER_TRADE_PERCENT=1.0         # 거래당 리스크 (%)
```

**3. Discord 알림** (Lines 21-23):
```bash
DISCORD_WEBHOOK_URL=""  # 선택 사항
```

**4. 데이터베이스** (Lines 26-28):
```bash
DATABASE_PATH="data/tradingbot.db"
```

**5. 로깅 설정** (Lines 31-36):
```bash
LOG_LEVEL="INFO"                    # DEBUG, INFO, WARNING, ERROR
LOG_FILE_PATH="logs/tradingbot.log"
LOG_MAX_SIZE_MB=10
LOG_BACKUP_COUNT=5
```

**6. API 서버** (Lines 39-43):
```bash
API_HOST="0.0.0.0"
API_PORT=8000
API_RELOAD=false  # 개발 전용
```

**7. Task Master AI & 개발 도구** (Lines 48-60):
```bash
ANTHROPIC_API_KEY="..."      # Claude API (필수)
PERPLEXITY_API_KEY="..."     # Perplexity (선택)
OPENAI_API_KEY="..."         # OpenAI (선택)
GOOGLE_API_KEY="..."         # Gemini (선택)
# ... 기타 AI 제공자
```

**보안 고려사항**:
- `.gitignore`에 `.env` 파일 추가
- API 키는 절대 커밋하지 않음
- 템플릿만 버전 관리에 포함

### 1.4 프로젝트 메타 파일 및 문서 작성

**구현 내용**:
- `README.md` - 프로젝트 개요 및 사용법
- `LICENSE` - MIT 라이선스
- `.gitignore` - 버전 관리 제외 파일
- `CLAUDE.md` - AI 어시스턴트 컨텍스트
- `pyproject.toml` 메타데이터

**프로젝트 메타데이터** (`pyproject.toml:5-24`):
```toml
[project]
name = "tradingbot"
version = "0.1.0"
description = "Cryptocurrency trading bot with ICT indicators and automated strategies"
requires-python = ">=3.9"
license = {text = "MIT"}
authors = [{name = "osangwon", email = "your.email@example.com"}]
keywords = ["trading", "cryptocurrency", "binance", "ICT", "automation"]
```

**프로젝트 URL** (`pyproject.toml:55-58`):
```toml
[project.urls]
Homepage = "https://github.com/ocho011/tradingbot"
Repository = "https://github.com/ocho011/tradingbot"
Issues = "https://github.com/ocho011/tradingbot/issues"
```

**.gitignore 주요 항목**:
```
# 환경 파일
.env
venv/
.venv/

# 데이터베이스
*.db
data/

# 로그
logs/
*.log

# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.coverage
htmlcov/

# IDE
.vscode/
.idea/
.cursor/
```

## 기술 스택 선택 근거

### Python 3.9+
- 타입 힌팅 개선 (PEP 585, 604)
- 비동기 프로그래밍 성능 향상
- Dictionary merge 연산자 (|)
- 안정성과 최신 기능의 균형

### pyproject.toml over setup.py
- PEP 517/518 표준 준수
- 현대적인 Python 프로젝트 구조
- 통합된 설정 파일 (빌드, 도구, 메타데이터)
- 더 나은 가독성과 유지보수성

### Setuptools Build System
- 광범위한 호환성
- 안정적이고 잘 문서화됨
- pip와 완벽한 통합

### Development Tools
- **Black**: 논쟁의 여지가 없는 코드 스타일
- **Flake8**: PEP 8 준수 및 코드 품질 검사
- **mypy**: 정적 타입 체킹으로 버그 조기 발견
- **isort**: Import 문 자동 정렬
- **pytest**: 강력한 테스트 프레임워크

## 검증 방법

### 1. 가상환경 확인
```bash
python --version  # Python 3.9+ 확인
pip list         # 설치된 패키지 확인
```

### 2. 의존성 설치 테스트
```bash
pip install -e ".[dev]"  # 개발 의존성 포함 설치
```

### 3. 코드 품질 도구 실행
```bash
black src/ tests/        # 코드 포맷팅
isort src/ tests/        # Import 정렬
flake8 src/ tests/       # Linting
mypy src/                # 타입 체킹
pytest tests/            # 테스트 실행
```

### 4. 환경 변수 로드 테스트
```python
from dotenv import load_dotenv
import os

load_dotenv()
assert os.getenv("BINANCE_API_KEY") is not None
```

## 프로젝트 구조 설계 원칙

### 1. 관심사의 분리 (Separation of Concerns)
- `core/`: 범용 유틸리티 및 기반 클래스
- `services/`: 외부 시스템과의 통합
- `indicators/`: ICT 지표 계산 로직
- `strategies/`: 거래 전략 구현
- `database/`: 데이터 영속성 레이어
- `api/`: HTTP API 인터페이스

### 2. 테스트 용이성
- 테스트 디렉토리를 소스와 분리
- Fixtures를 통한 테스트 데이터 관리
- 단위/통합 테스트 명확한 구분

### 3. 확장성
- 모듈화된 구조로 새 기능 추가 용이
- 플러그인 방식의 전략 시스템
- 다중 거래소 지원 가능한 아키텍처

### 4. 보안
- 환경 변수로 민감 정보 관리
- `.gitignore`로 비밀 정보 유출 방지
- 테스트넷 우선 개발 (BINANCE_TESTNET=true)

## 개발 워크플로우

### 초기 설정
```bash
# 1. 저장소 클론
git clone https://github.com/ocho011/tradingbot.git
cd tradingbot

# 2. 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 의존성 설치
pip install -e ".[dev]"

# 4. 환경 변수 설정
cp .env.example .env
# .env 파일 편집하여 API 키 입력

# 5. 데이터베이스 초기화
alembic upgrade head

# 6. 테스트 실행
pytest
```

### 일상 개발
```bash
# 코드 작성 후 품질 검사
black src/ tests/
isort src/ tests/
flake8 src/ tests/
mypy src/

# 테스트 실행
pytest --cov=src

# Git 커밋
git add .
git commit -m "feat: add new feature"
```

## 알려진 제약사항

1. **TA-Lib 설치 복잡성**:
   - 시스템 의존성 필요 (C 라이브러리)
   - macOS: `brew install ta-lib`
   - Ubuntu: `sudo apt-get install ta-lib`
   - Windows: 바이너리 설치 필요

2. **Python 버전 호환성**:
   - Python 3.9 미만 지원 안 함
   - 일부 타입 힌팅 기능 3.9+ 전용

3. **개발 환경 차이**:
   - Windows/Linux/macOS 간 경로 처리 차이
   - 환경 변수 설정 방식 차이

## 향후 개선 사항

1. **Docker 컨테이너화**:
   - 일관된 개발 환경 제공
   - 의존성 설치 간소화
   - 프로덕션 배포 용이

2. **Pre-commit Hooks**:
   - 커밋 전 자동 품질 검사
   - Black, isort, flake8 자동 실행
   - 테스트 실패 시 커밋 방지

3. **CI/CD 파이프라인**:
   - GitHub Actions 설정
   - 자동 테스트 및 배포
   - 코드 커버리지 추적

4. **환경별 설정 분리**:
   - `config/dev.yaml`, `config/prod.yaml`
   - 환경별 로깅 레벨
   - 환경별 DB 설정

## 관련 파일

- `pyproject.toml` - 프로젝트 설정 및 의존성
- `.env.example` - 환경 변수 템플릿
- `.gitignore` - 버전 관리 제외 파일
- `README.md` - 프로젝트 문서
- `LICENSE` - MIT 라이선스
- `alembic.ini` - DB 마이그레이션 설정

## 참고 자료

- [PEP 517 - Build System](https://peps.python.org/pep-0517/)
- [PEP 518 - pyproject.toml](https://peps.python.org/pep-0518/)
- [Setuptools Documentation](https://setuptools.pypa.io/)
- [Python Packaging Guide](https://packaging.python.org/)
- [Black Code Style](https://black.readthedocs.io/)
