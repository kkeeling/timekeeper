#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "google-genai>=0.2.0",
#     "google-api-core>=2.0.0",
#     "python-dotenv>=1.0.0",
#     "pydantic>=2.0.0"
# ]
# ///
"""
Timekeep - Automated time tracking for development projects
Uses git analysis and AI to estimate development time
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError
from google import genai
from google.genai import types
from google.api_core import exceptions as google_exceptions


# Constants for fallback estimation
FALLBACK_BASE_HOURS = 0.5  # Minimum hours for any commits
FALLBACK_LINES_PER_HOUR = 100  # Estimated lines of code per hour
FALLBACK_MAX_HOURS = 8.0  # Maximum daily hours cap

# Pydantic models for structured output
class TaskSummary(BaseModel):
    task: str
    hours: float


class CommitAnalysis(BaseModel):
    total_hours: float
    summary: str
    major_tasks: List[TaskSummary]


def load_project_config(config_path: Path = None) -> List[Dict[str, str]]:
    """Load project configuration from JSON file"""
    if config_path is None:
        config_path = Path(__file__).parent / "projects.json"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Project configuration file not found: {config_path}")
    
    with open(config_path, 'r') as f:
        projects = json.load(f)
    
    # Expand home directory paths
    for project in projects:
        project['path'] = str(Path(project['path']).expanduser())
    
    return projects


def run_git_command(cmd: List[str], cwd: str) -> Optional[str]:
    """Execute a git command using list format and return output"""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Git command failed in {cwd}: {e.stderr}")
        return None
    except Exception as e:
        print(f"Error running git command: {e}")
        return None


def get_commits_for_day(repo_path: str, target_date: datetime) -> List[Dict[str, any]]:
    """Get all commits from all branches for a specific day with statistics"""
    # Format dates for git (analyze full day from midnight to midnight)
    since_str = target_date.strftime("%Y-%m-%d %H:%M:%S")
    until = target_date.replace(hour=23, minute=59, second=59)
    until_str = until.strftime("%Y-%m-%d %H:%M:%S")
    
    # Get commits with file statistics in a single command
    cmd = [
        'git', 'log', '--all', '--no-merges', 
        f'--since={since_str}', f'--until={until_str}',
        '--format=COMMIT_BOUNDARY|||%H|||%an|||%ae|||%at|||%s',
        '--numstat'
    ]
    output = run_git_command(cmd, repo_path)
    
    if not output:
        return []
    
    commits = []
    seen_hashes = set()
    current_commit = None
    
    for line in output.splitlines():
        if line.startswith('COMMIT_BOUNDARY|||'):
            # Save previous commit if exists
            if current_commit and current_commit['hash'] not in seen_hashes:
                seen_hashes.add(current_commit['hash'])
                commits.append(current_commit)
            
            # Parse new commit
            parts = line[18:].split('|||')  # Skip 'COMMIT_BOUNDARY|||'
            if len(parts) == 5:
                current_commit = {
                    'hash': parts[0],
                    'author': parts[1],
                    'email': parts[2],
                    'timestamp': int(parts[3]),
                    'message': parts[4],
                    'files': 0,
                    'additions': 0,
                    'deletions': 0
                }
        elif current_commit and '\t' in line:
            # Parse numstat line
            parts = line.split('\t')
            if len(parts) >= 3:
                current_commit['files'] += 1
                try:
                    # Handle binary files which show '-'
                    add = int(parts[0]) if parts[0] != '-' else 0
                    delete = int(parts[1]) if parts[1] != '-' else 0
                    current_commit['additions'] += add
                    current_commit['deletions'] += delete
                except ValueError:
                    continue
    
    # Don't forget the last commit
    if current_commit and current_commit['hash'] not in seen_hashes:
        commits.append(current_commit)
    
    return commits



async def analyze_commits_batch(commits: List[Dict]) -> Dict[str, any]:
    """Send all commits to Gemini at once for structured analysis"""
    if not commits:
        return {
            'total_hours': 0,
            'summary': 'No commits to analyze',
            'major_tasks': []
        }
    
    # Initialize client
    client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
    
    # Format commits for the prompt
    commits_text = "\n".join([
        f"- [{commit['hash'][:8]}] {commit['message']} "
        f"(+{commit['additions']}/-{commit['deletions']} in {commit['files']} files)"
        for commit in commits
    ])
    
    prompt = f"""Analyze these git commits from today and provide:
1. Total estimated development time (including planning, coding, testing, debugging)
2. A summary of what was accomplished
3. Brief breakdown of major tasks

Commits:
{commits_text}

Consider:
- Related commits might be part of the same task
- Small commits (typos, formatting) take minimal time
- Large changes or new features take more time
- Include overhead time for context switching
- Be realistic with time estimates"""
    
    try:
        # Use structured output with Pydantic model
        response = await client.aio.models.generate_content(
            model='gemini-2.0-flash-001',
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type='application/json',
                response_schema=CommitAnalysis,  # Pydantic model ensures structure
                max_output_tokens=1000
            )
        )
        
        # Parse and validate the structured response with Pydantic
        analysis_result = CommitAnalysis.model_validate_json(response.text)
        result_dict = analysis_result.model_dump()
        
        # Divide all time estimates by 4
        result_dict['total_hours'] = round(result_dict['total_hours'] / 4, 2)
        for task in result_dict.get('major_tasks', []):
            task['hours'] = round(task['hours'] / 4, 2)
        
        return result_dict
        
    except json.JSONDecodeError as e:
        # Handle JSON parsing errors
        print(f"JSON parsing error from Gemini API: {e}")
        total_lines = sum(c['additions'] + c['deletions'] for c in commits)
        hours = round(min(FALLBACK_BASE_HOURS + total_lines / FALLBACK_LINES_PER_HOUR, FALLBACK_MAX_HOURS) / 4, 2)
        
        return {
            'total_hours': hours,
            'summary': f'AI analysis failed (JSONDecodeError). Fallback: {len(commits)} commits, {total_lines} lines changed.',
            'major_tasks': [],
            'error': f'JSON parsing error: {e}'
        }
    except ValidationError as e:
        # Handle Pydantic validation errors
        print(f"Response validation error from Gemini API: {e}")
        total_lines = sum(c['additions'] + c['deletions'] for c in commits)
        hours = round(min(FALLBACK_BASE_HOURS + total_lines / FALLBACK_LINES_PER_HOUR, FALLBACK_MAX_HOURS) / 4, 2)
        
        return {
            'total_hours': hours,
            'summary': f'AI analysis failed (ValidationError). Fallback: {len(commits)} commits, {total_lines} lines changed.',
            'major_tasks': [],
            'error': f'Response validation error: {e}'
        }
    except google_exceptions.GoogleAPIError as e:
        # Handle specific Google API errors
        print(f"Gemini API Error: {type(e).__name__}: {e}")
        total_lines = sum(c['additions'] + c['deletions'] for c in commits)
        hours = round(min(FALLBACK_BASE_HOURS + total_lines / FALLBACK_LINES_PER_HOUR, FALLBACK_MAX_HOURS) / 4, 2)
        
        return {
            'total_hours': hours,
            'summary': f'AI analysis failed ({type(e).__name__}). Fallback: {len(commits)} commits, {total_lines} lines changed.',
            'major_tasks': [],
            'error': str(e)
        }
    except Exception as e:
        # Catch any other unexpected exceptions
        print(f"An unexpected error occurred: {type(e).__name__}: {e}")
        total_lines = sum(c['additions'] + c['deletions'] for c in commits)
        hours = round(min(FALLBACK_BASE_HOURS + total_lines / FALLBACK_LINES_PER_HOUR, FALLBACK_MAX_HOURS) / 4, 2)
        
        return {
            'total_hours': hours,
            'summary': f'AI analysis failed (Unexpected Error). Fallback: {len(commits)} commits, {total_lines} lines changed.',
            'major_tasks': [],
            'error': str(e)
        }


async def analyze_project(project: Dict[str, str], since: datetime) -> Dict:
    """Analyze a single project's git history"""
    project_path = project['path']
    project_name = project['name']
    
    # Check if path exists and is a git repo
    if not Path(project_path).exists():
        return {
            'name': project_name,
            'error': f"Path does not exist: {project_path}",
            'total_hours': 0
        }
    
    if not Path(project_path, '.git').exists():
        return {
            'name': project_name,
            'error': f"Not a git repository: {project_path}",
            'total_hours': 0
        }
    
    # Get commits
    commits = get_commits_for_day(project_path, since)
    
    if not commits:
        return {
            'name': project_name,
            'commits': 0,
            'total_hours': 0,
            'summary': 'No commits today',
            'major_tasks': []
        }
    
    # Analyze ALL commits in one API call
    analysis = await analyze_commits_batch(commits)
    
    return {
        'name': project_name,
        'path': project_path,
        'commits': len(commits),
        'total_hours': analysis.get('total_hours', 0),
        'summary': analysis.get('summary', ''),
        'major_tasks': analysis.get('major_tasks', []),
        'error': analysis.get('error')
    }


def print_project_summary(project_result: Dict):
    """Print a formatted summary for a project"""
    name = project_result['name']
    
    if project_result.get('error'):
        print(f"\n{name}: ❌ {project_result['error']}")
        return
    
    commits = project_result['commits']
    hours = project_result['total_hours']
    summary = project_result.get('summary', '')
    
    print(f"\n{name}:")
    print(f"  📊 Commits: {commits}")
    print(f"  ⏱️  Time: {hours:.2f} hours")
    
    if summary:
        print(f"  📝 Summary: {summary}")
    
    major_tasks = project_result.get('major_tasks', [])
    if major_tasks:
        print("  🎯 Major tasks:")
        # Sort by hours descending and take the top 5
        sorted_tasks = sorted(major_tasks, key=lambda t: t.get('hours', 0), reverse=True)[:5]
        for task in sorted_tasks:
            print(f"     - {task['task']} ({task.get('hours', 0)}h)")


def parse_date_argument() -> Optional[datetime]:
    """Parse date from command line arguments"""
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
        try:
            # Try to parse the date in various formats
            for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y']:
                try:
                    return datetime.strptime(date_str, fmt).replace(hour=0, minute=0, second=0, microsecond=0)
                except ValueError:
                    continue
            
            # If no format worked, raise an error
            raise ValueError(f"Could not parse date '{date_str}'. Please use format YYYY-MM-DD")
        except ValueError as e:
            print(f"Error: {e}")
            print("Usage: uv run timekeep.py [date]")
            print("Examples:")
            print("  uv run timekeep.py                # Analyze today's commits")
            print("  uv run timekeep.py 2025-01-01     # Analyze commits from specific date")
            sys.exit(1)
    
    return None


async def main():
    """Main execution function"""
    # Load environment variables
    load_dotenv()
    
    # Check for API key
    if not os.getenv('GEMINI_API_KEY'):
        print("Error: GEMINI_API_KEY not found in environment or .env file")
        print("Please set your Gemini API key:")
        print("  export GEMINI_API_KEY='your-api-key'")
        print("Or add it to .env file")
        print("\nGet your API key from: https://makersuite.google.com/app/apikey")
        sys.exit(1)
    
    print(f"Timekeep - Running at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    
    try:
        # Load project configuration
        projects = load_project_config()
        print(f"Loaded {len(projects)} projects from configuration")
        
        # Get the date to analyze (from argument or default to today)
        target_date = parse_date_argument()
        if target_date is None:
            # Default to today
            target_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        print(f"\nAnalyzing commits from: {target_date.strftime('%Y-%m-%d')}")
        print("-" * 50)
        
        # Analyze each project
        tasks = []
        for project in projects:
            task = analyze_project(project, target_date)
            tasks.append(task)
        
        # Wait for all analyses to complete
        results = await asyncio.gather(*tasks)
        
        # Print summaries
        total_hours_all = 0
        for result in results:
            print_project_summary(result)
            if not result.get('error'):
                total_hours_all += result['total_hours']
        
        print("\n" + "=" * 50)
        print(f"Total time across all projects: {total_hours_all:.2f} hours")
        
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Please create a projects.json file with your project configurations")
    except Exception as e:
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())