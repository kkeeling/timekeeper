# Timekeep

A single-file time tracking tool that analyzes git commits across multiple projects to estimate development time. Uses Google Gemini AI to provide intelligent time estimates and comprehensive work summaries.

## Features

- Single-file script using `uv`'s inline dependency management
- Analyzes git commits from ALL branches (not just main/current)
- Local JSON configuration for project paths
- **Google Gemini AI integration** for intelligent time estimation
- **Batch processing** - sends all commits in one API call for better context and cost efficiency
- **Structured outputs** using Pydantic models for reliable JSON responses
- De-duplicates commits across branches
- Generates daily summaries with time estimates and major task breakdowns
- **Time rounding** - rounds all time estimates to the nearest half hour
- **Daily cap** - limits time tracking to a maximum of 6 hours per project per day
- **Author filtering** - tracks only your commits by automatically detecting and storing your git email per project
- **TimeCamp integration** (optional) - automatically creates time entries from analyzed commits

## Setup

1. Install `uv` (if not already installed):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Get a Google Gemini API key:
   - Visit https://makersuite.google.com/app/apikey
   - Create a new API key
   - Add it to `.env` file:
     ```bash
     GEMINI_API_KEY=your-actual-api-key-here
     ```

3. Create a `projects.json` file in the same directory as `timekeep.py`:
   ```json
   [
     {
       "name": "My Project",
       "path": "~/dev/my-project",
       "timecamp_task_id": 123456,
       "timecamp_enabled": true
     },
     {
       "name": "Another Project", 
       "path": "~/work/another-project"
     }
   ]
   ```

### TimeCamp Integration (Optional)

To enable automatic time tracking with TimeCamp:

1. Get your TimeCamp API token:
   - Log in to TimeCamp: https://app.timecamp.com
   - Go to Settings → Your Profile: https://app.timecamp.com/app#/settings/users/me
   - Copy your API token

2. Add the token to your `.env` file:
   ```bash
   TIMECAMP_API_TOKEN=your-actual-timecamp-token-here
   ```

3. Find your TimeCamp task IDs:
   - Use the TimeCamp web interface to find task IDs
   - Or run this curl command with your token:
     ```bash
     curl -H "Authorization: YOUR_TOKEN" https://www.timecamp.com/third_party/api/tasks
     ```

4. Update `projects.json` with TimeCamp task IDs:
   ```json
   {
     "name": "Project Name",
     "path": "~/dev/project",
     "timecamp_task_id": 123456,
     "timecamp_enabled": true
   }
   ```

   - `timecamp_task_id`: The ID of the task in TimeCamp
   - `timecamp_enabled`: Set to `false` to disable for specific projects

## Usage

Run the script directly with `uv`:
```bash
# Analyze today's commits
uv run timekeep.py

# Analyze commits from a specific date
uv run timekeep.py 2025-01-01
uv run timekeep.py 2025-06-30

# Disable TimeCamp integration for this run
uv run timekeep.py --no-timecamp
uv run timekeep.py 2025-01-01 --no-timecamp

# Force reconfiguration of author emails for all projects
uv run timekeep.py --reconfigure-author
```

### Author Configuration

Timekeep automatically filters commits to only track those made by you. On first run for each project:

1. It checks your git configuration (local repository config first, then global)
2. Shows you the detected email and asks for confirmation
3. If confirmed, saves it to `projects.json` for future runs
4. If not confirmed, prompts you to enter the correct email

The author email is stored per project in `projects.json`:
```json
{
  "name": "My Project",
  "path": "~/dev/my-project",
  "author_email": "developer@example.com"
}
```

This allows you to use different email addresses for different projects (e.g., personal vs work projects).

The script accepts dates in multiple formats:
- `YYYY-MM-DD` (recommended)
- `YYYY/MM/DD`
- `DD-MM-YYYY`
- `DD/MM/YYYY`

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
  📝 Summary: Implemented user authentication system with JWT tokens, refactored database schema for improved performance, and fixed critical payment processing bug
  🎯 Major tasks:
     - Refactored database schema for better performance (3.0h)
     - Implemented user authentication flow with JWT (2.5h)
     - Fixed critical bug in payment module (1.0h)
  ✅ Submitted to TimeCamp: 7.50h

Another Project:
  📊 Commits: 3
  ⏱️  Time: 4.25 hours
  📝 Summary: Integrated email notification system, expanded API with new endpoints, and optimized application performance
  🎯 Major tasks:
     - Integrated third-party email service (2.0h)
     - Created customer data management endpoints (1.5h)
     - Optimized frontend bundle size (0.75h)

==================================================
Total time across all projects: 11.75 hours
```

### Setting up nightly runs

#### macOS/Linux (using cron):
```bash
# Edit crontab
crontab -e

# Add this line for 10pm daily execution (analyzes current day)
0 22 * * * cd /path/to/timekeeper && uv run timekeep.py >> ~/logs/timekeeper.log 2>&1

# Or to analyze the previous day's commits (useful for end-of-day reporting)
0 22 * * * cd /path/to/timekeeper && uv run timekeep.py $(date -d "yesterday" +\%Y-\%m-\%d) >> ~/logs/timekeeper.log 2>&1
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
5. **Batch AI Analysis**: Sends all commits for a project in a single API call to Google Gemini
   - Uses structured output with Pydantic models for reliable JSON responses
   - Provides better context for more accurate time estimates
   - Cost-efficient (one API call per project instead of per commit)
6. **Summary Generation**: Shows overall summary and major tasks with time breakdowns

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
#     "google-genai>=0.2.0",
#     "google-api-core>=2.0.0",
#     "python-dotenv>=1.0.0",
#     "pydantic>=2.0.0",
#     "requests>=2.31.0"
# ]
# ///
```

## Future Enhancements

- [x] Google Gemini AI integration for intelligent time estimation
- [x] Batch processing for cost efficiency
- [x] Structured outputs with Pydantic
- [x] TimeCamp API integration for automatic time entry
- [ ] Caching to avoid re-analyzing same commits
- [ ] Configurable time ranges (week, month, custom)
- [ ] Export to CSV/JSON formats
- [ ] Click CLI interface for better command-line options
- [ ] Slack/Discord notifications

## Development

The tool now uses Google Gemini AI for intelligent time analysis:

1. **Batch Processing**: All commits for a project are sent in a single API call
2. **Structured Output**: Uses Pydantic models to ensure reliable JSON responses
3. **Smart Analysis**: Gemini understands related commits and provides holistic time estimates
4. **Cost Efficient**: Approximately $0.00015 per project analysis (vs $0.003 with individual calls)

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