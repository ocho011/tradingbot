# Session Files

This directory stores session state snapshots for resuming work.

## Usage

### Save Current Session
```bash
/sc:save
```

Creates a timestamped session file with:
- Current git branch
- Active task ID
- In-progress tasks
- Working directory state
- Session notes/context

### Load Session
```bash
/sc:load                    # Load most recent session
/sc:load session-2025-10-19-103000.json   # Load specific session
/sc:load 2                 # Load by index (2nd most recent)
```

Restores:
- Task context
- Branch information
- Work state
- Progress notes

## Session File Format

```json
{
  "timestamp": "2025-10-19T10:30:00Z",
  "branch": "feature/auth",
  "currentTask": "3.2",
  "inProgressTasks": ["3.1", "3.2"],
  "workingDirectory": "/Users/user/project",
  "uncommittedChanges": true,
  "notes": "Working on WebSocket implementation",
  "context": {
    "recentCommits": ["abc123"],
    "modifiedFiles": ["src/websocket.ts"]
  }
}
```

## Best Practices

1. **Save before breaks**: `/sc:save` before lunch, end of day, context switches
2. **Save before risky operations**: Create checkpoint before major refactoring
3. **Load at session start**: `/sc:load` when resuming work
4. **Commit session files**: Consider adding to git for team collaboration
5. **Clean old sessions**: Periodically remove sessions older than 30 days

## .gitignore Recommendation

**Option 1: Ignore all sessions (personal workflow)**
```gitignore
.taskmaster/sessions/*.json
!.taskmaster/sessions/README.md
```

**Option 2: Commit sessions (team collaboration)**
```gitignore
# Don't ignore - commit session files for team visibility
```

## Automatic Cleanup

Session files older than 30 days can be cleaned automatically:
```bash
find .taskmaster/sessions -name "session-*.json" -mtime +30 -delete
```
