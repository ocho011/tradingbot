# Task Completion Workflow (필수 루틴)

## 각 Task/Subtask 구현 완료 후 반드시 수행할 작업

### 1. 구현 내용 문서화 (Documentation)
**위치**: `/Users/osangwon/github/tradingbot/docs/`
**파일명 형식**: `task_X.Y_<descriptive_name>_implementation.md` (예: `task_7.3_trend_recognition_implementation.md`)

**문서 내용 포함사항**:
- Status (✅ Complete, 날짜, 테스트 커버리지)
- Overview (구현 개요)
- Components Implemented (구현된 컴포넌트 상세)
- Integration Details (통합 세부사항)
- Configuration Parameters (설정 파라미터)
- Test Coverage (테스트 커버리지 상세)
- Usage Examples (사용 예제)
- Key Design Decisions (주요 설계 결정사항)
- Performance Characteristics (성능 특성)
- Known Limitations (알려진 제한사항)
- Future Enhancements (향후 개선사항)
- Related Components (관련 컴포넌트)

### 2. Git Commit & Push
**커밋 메시지 형식**:
```
feat: complete Task X.Y - <Task Title>

- 주요 구현 내용 1
- 주요 구현 내용 2
- 테스트 결과 요약

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

**실행 순서**:
1. `git add .`
2. `git status` (변경사항 확인)
3. `git commit -m "..."`
4. `git push`

## 중요 사항
- 모든 Task/Subtask 완료 시 이 워크플로우를 자동으로 수행
- 문서화를 먼저 완료한 후 커밋/푸시 진행
- 테스트가 모두 통과한 상태에서만 완료 처리
