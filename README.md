# Timekeep

A single-file time tracking tool that analyzes git commits across multiple projects to estimate development time. Uses AI-powered analysis (currently stubbed) to provide intelligent time estimates and work summaries.

## Features

- Single-file script using `uv`'s inline dependency management
- Analyzes git commits from ALL branches (not just main/current)
- Local JSON configuration for project paths
- Async LLM stub for future AI-powered time estimation
- De-duplicates commits across branches
- Generates daily summaries with time estimates

## Setup

1. Install `uv` (if not already installed):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Create a `projects.json` file in the same directory as `timekeep.py`:
   ```json
   [
     {
       "name": "My Project",
       "path": "~/dev/my-project"
     },
     {
       "name": "Another Project", 
       "path": "~/work/another-project"
     }
   ]
   ```

## Usage

Run the script directly with `uv`:
```bash
uv run timekeep.py
```

### Output Example
```
Timekeep - Running at 2025-01-01 10:00:00
==================================================
Loaded 2 projects from configuration

Analyzing commits since: 2025-01-01 00:00:00
--------------------------------------------------

My Project:
  📊 Commits: 5
  ⏱️  Time: 7.50 hours
  📝 Work summary:
     - 3.0h: Refactored database schema for better performance
     - 2.5h: Implemented user authentication flow
     - 1.0h: Fixed critical bug in payment module

Another Project:
  📊 Commits: 3
  ⏱️  Time: 4.25 hours
  📝 Work summary:
     - 2.0h: Integrated third-party email service
     - 1.5h: Created new API endpoints
     - 0.75h: Optimized frontend bundle size

==================================================
Total time across all projects: 11.75 hours
```

### Setting up nightly runs

#### macOS/Linux (using cron):
```bash
# Edit crontab
crontab -e

# Add this line for 10pm daily execution
0 22 * * * cd /path/to/timekeeper && uv run timekeep.py >> ~/logs/timekeeper.log 2>&1
```

#### Windows (using Task Scheduler):
1. Open Task Scheduler
2. Create Basic Task
3. Set trigger to Daily at 10:00 PM
4. Set action to start `uv.exe` with arguments `run timekeep.py`

## How it Works

1. **Script Dependencies**: Uses `uv`'s inline script metadata for dependency management
2. **Project Configuration**: Reads local `projects.json` for repository paths
3. **Git Analysis**: Scans ALL branches for commits since midnight
4. **Commit De-duplication**: Removes duplicate commits across branches
5. **Time Estimation**: Currently uses stub that returns mock data
   - Future: Will send commit details to Claude for intelligent analysis
6. **Summary Generation**: Shows top work items by time spent

## Architecture

The entire tool is a single file:
```
timekeeper/
├── timekeep.py         # Single-file script with inline dependencies
└── projects.json       # Project configuration
```

The script includes inline metadata for `uv`:
```python
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "python-dotenv>=1.0.0",
# ]
# ///
```

## Future Enhancements

- [ ] Real LLM integration for intelligent time estimation
- [ ] Caching to avoid re-analyzing same commits
- [ ] TimeCamp API integration for automatic time entry
- [ ] Configurable time ranges (week, month, custom)
- [ ] Export to CSV/JSON formats
- [ ] Click CLI interface for better command-line options
- [ ] Slack/Discord notifications

## Development

The LLM stub (`estimate_time_with_llm`) currently returns random mock data. To integrate real AI analysis:

1. Replace the stub with actual Claude Code SDK calls
2. Send commit details (message, files changed, diff stats)
3. Parse AI response for time estimate and work summary

### Adding Dependencies

To add new dependencies, update the inline script metadata:
```python
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "python-dotenv>=1.0.0",
#     "click>=8.0.0",  # New dependency
# ]
# ///
```

## Contributing

Feel free to submit issues or pull requests to improve Timekeep!