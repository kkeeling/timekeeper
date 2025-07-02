#!/usr/bin/env python3
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
"""
Timekeep - Automated time tracking for development projects
Uses git analysis and AI to estimate development time
"""

import asyncio
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError
from google import genai
from google.genai import types
from google.api_core import exceptions as google_exceptions
import requests


# Constants for fallback estimation
FALLBACK_BASE_HOURS = 0.5  # Minimum hours for any commits
FALLBACK_LINES_PER_HOUR = 100  # Estimated lines of code per hour
FALLBACK_MAX_HOURS = 40.0  # Maximum daily hours cap (before division by 4)

# Pydantic models for structured output
class TaskSummary(BaseModel):
    task: str
    hours: float


class CommitAnalysis(BaseModel):
    total_hours: float
    summary: str
    major_tasks: List[TaskSummary]


class TimeCampClient:
    """Client for interacting with TimeCamp API"""
    
    def __init__(self, api_token: str):
        self.api_token = api_token
        self.base_url = 'https://www.timecamp.com/third_party/api'
        self.headers = {
            'Authorization': api_token,
            'Content-Type': 'application/json'
        }
    
    def create_time_entry(self, task_id: int, duration: float, date_str: str, 
                        note: str = '') -> Dict[str, any]:
        """
        Create a time entry in TimeCamp
        
        Args:
            task_id: The ID of the task in TimeCamp
            duration: Duration in hours (will be converted to seconds)
            date_str: Date in format 'YYYY-MM-DD'
            note: Description for the time entry
        
        Returns:
            Response data or error information
        """
        url = f'{self.base_url}/entries'
        
        # Convert hours to seconds, rounding to nearest second
        duration_seconds = round(duration * 3600)
        
        payload = {
            'date': date_str,
            'duration': duration_seconds,
            'note': note,
            'task_id': task_id
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            
            if response.status_code == 429:
                return {
                    'success': False,
                    'error': 'API rate limit reached. Please try again later.'
                }
            
            response.raise_for_status()
            
            # Debug: Check if response has content
            if not response.text:
                return {
                    'success': True,
                    'data': {'message': 'Time entry created successfully (no response body)'}
                }
            
            try:
                return {
                    'success': True,
                    'data': response.json()
                }
            except json.JSONDecodeError:
                # Some APIs return 200 with empty body on success
                return {
                    'success': True,
                    'data': {'message': 'Time entry created successfully', 'response': response.text[:100]}
                }
            
        except requests.exceptions.Timeout:
            return {
                'success': False,
                'error': 'Request timed out'
            }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': str(e),
                'status_code': e.response.status_code if e.response is not None else None
            }
    
    def get_tasks(self) -> Optional[Dict[str, Any]]:
        """Get all tasks from TimeCamp to find task IDs"""
        url = f'{self.base_url}/tasks'
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching TimeCamp tasks: {e}")
            return None


def load_project_config(config_path: Path = None) -> List[Dict[str, Any]]:
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


def get_git_author_email(repo_path: str) -> Optional[str]:
    """Get the git author email for a repository, checking local config first then global"""
    # Try local repository config first
    local_email = run_git_command(['git', 'config', 'user.email'], repo_path)
    if local_email:
        return local_email
    
    # Fall back to global config
    global_email = run_git_command(['git', 'config', '--global', 'user.email'], repo_path)
    return global_email


def save_projects_config(projects: List[Dict[str, Any]], config_path: Path = None) -> None:
    """Save the projects configuration back to JSON file"""
    if config_path is None:
        config_path = Path(__file__).parent / "projects.json"
    
    # Convert paths back to strings with ~ for home directory
    projects_to_save = []
    for project in projects:
        project_copy = project.copy()
        # Convert absolute path back to ~ notation if it's in home directory
        path = Path(project_copy['path'])
        home = Path.home()
        try:
            relative_to_home = path.relative_to(home)
            project_copy['path'] = f"~/{relative_to_home}"
        except ValueError:
            # Path is not relative to home, keep as is
            project_copy['path'] = str(path)
        projects_to_save.append(project_copy)
    
    with open(config_path, 'w') as f:
        json.dump(projects_to_save, f, indent=2)
        f.write('\n')  # Add trailing newline


def confirm_and_save_author(project: Dict[str, Any], detected_email: Optional[str], 
                           all_projects: List[Dict[str, Any]], force_reconfigure: bool = False) -> Optional[str]:
    """Interactively confirm or set the author email for a project"""
    project_name = project['name']
    
    # Check if already configured and not forcing reconfiguration
    if 'author_email' in project and not force_reconfigure:
        return project['author_email']
    
    print(f"\n📧 Configuring author email for '{project_name}'...")
    
    if detected_email:
        print(f"Detected git author email: {detected_email}")
        response = input("Use this email for tracking your commits? (y/n): ").strip().lower()
        
        if response == 'y':
            project['author_email'] = detected_email
            save_projects_config(all_projects)
            print(f"✅ Saved author email for '{project_name}'")
            return detected_email
    else:
        print("No git author email detected in local or global config.")
    
    # Ask for email
    while True:
        email = input("Enter the email address used for your commits in this project: ").strip()
        if email and '@' in email:
            project['author_email'] = email
            save_projects_config(all_projects)
            print(f"✅ Saved author email for '{project_name}'")
            return email
        else:
            print("Please enter a valid email address.")
    
    return None


def get_commits_for_day(repo_path: str, target_date: datetime, author_email: Optional[str] = None) -> List[Dict[str, any]]:
    """Get all commits from all branches for a specific day with statistics, optionally filtered by author"""
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
    
    # Add author filter if provided
    if author_email:
        cmd.insert(3, f'--author={author_email}')
    
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



def round_to_half_hour(hours: float) -> float:
    """Round hours to the nearest half hour (0.5 increments)"""
    return round(hours * 2) / 2


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
        
        # Divide all time estimates by 4, round to nearest half hour, and cap total_hours at 10
        result_dict['total_hours'] = min(round_to_half_hour(result_dict['total_hours'] / 4), 10)
        for task in result_dict.get('major_tasks', []):
            task['hours'] = round_to_half_hour(task['hours'] / 4)
        
        return result_dict
        
    except json.JSONDecodeError as e:
        # Handle JSON parsing errors
        print(f"JSON parsing error from Gemini API: {e}")
        total_lines = sum(c['additions'] + c['deletions'] for c in commits)
        hours = min(round_to_half_hour((FALLBACK_BASE_HOURS + total_lines / FALLBACK_LINES_PER_HOUR) / 4), 10)
        
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
        hours = min(round_to_half_hour((FALLBACK_BASE_HOURS + total_lines / FALLBACK_LINES_PER_HOUR) / 4), 10)
        
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
        hours = min(round_to_half_hour((FALLBACK_BASE_HOURS + total_lines / FALLBACK_LINES_PER_HOUR) / 4), 10)
        
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
        hours = min(round_to_half_hour((FALLBACK_BASE_HOURS + total_lines / FALLBACK_LINES_PER_HOUR) / 4), 10)
        
        return {
            'total_hours': hours,
            'summary': f'AI analysis failed (Unexpected Error). Fallback: {len(commits)} commits, {total_lines} lines changed.',
            'major_tasks': [],
            'error': str(e)
        }


async def analyze_project(project: Dict[str, str], since: datetime, 
                         all_projects: List[Dict[str, Any]], force_reconfigure: bool = False) -> Dict:
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
    
    # Get or confirm author email
    detected_email = get_git_author_email(project_path)
    author_email = confirm_and_save_author(project, detected_email, all_projects, force_reconfigure)
    
    if not author_email:
        return {
            'name': project_name,
            'error': "No author email configured",
            'total_hours': 0
        }
    
    # Get commits filtered by author
    commits = get_commits_for_day(project_path, since, author_email)
    
    if not commits:
        return {
            'name': project_name,
            'commits': 0,
            'total_hours': 0,
            'summary': f'No commits by {author_email} on this day',
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
    print(f"  ⏱️  Time: {hours:.1f} hours")
    
    if summary:
        print(f"  📝 Summary: {summary}")
    
    major_tasks = project_result.get('major_tasks', [])
    if major_tasks:
        print("  🎯 Major tasks:")
        # Sort by hours descending and take the top 5
        sorted_tasks = sorted(major_tasks, key=lambda t: t.get('hours', 0), reverse=True)[:5]
        for task in sorted_tasks:
            print(f"     - {task['task']} ({task.get('hours', 0)}h)")


def submit_to_timecamp(client: TimeCampClient, project: Dict, result: Dict, 
                      date_str: str) -> bool:
    """Submit time entry to TimeCamp if configured"""
    # Check if TimeCamp is enabled for this project (defaults to False for opt-in)
    if not project.get('timecamp_enabled', False):
        return False
    
    # Check if project has TimeCamp task ID
    task_id = project.get('timecamp_task_id')
    if not task_id:
        return False
    
    # Skip if no time to report
    if result.get('error') or result.get('total_hours', 0) == 0:
        return False
    
    # Create note from summary and major tasks
    note_parts = [f"Timekeep: {result.get('summary', 'Development work')}"]
    major_tasks = result.get('major_tasks', [])[:3]  # Top 3 tasks
    if major_tasks:
        note_parts.append("\nTasks:")
        for task in major_tasks:
            note_parts.append(f"- {task['task']} ({task.get('hours', 0)}h)")
    
    note = '\n'.join(note_parts)
    
    # Submit time entry
    response = client.create_time_entry(
        task_id=task_id,
        duration=result['total_hours'],
        date_str=date_str,
        note=note
    )
    
    if response['success']:
        print(f"  ✅ Submitted to TimeCamp: {result['total_hours']}h")
        return True
    else:
        print(f"  ⚠️  TimeCamp submission failed: {response['error']}")
        return False


def parse_arguments():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description="A single-file time tracking tool that analyzes git commits across multiple projects",
        epilog="Examples:\n"
               "  uv run timekeep.py                    # Analyze today's commits\n"
               "  uv run timekeep.py 2025-01-01         # Analyze commits from specific date\n"
               "  uv run timekeep.py --no-timecamp      # Disable TimeCamp integration",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        'date',
        nargs='?',
        default=None,
        help='Optional date to analyze commits from (YYYY-MM-DD, YYYY/MM/DD, DD-MM-YYYY, DD/MM/YYYY)'
    )
    parser.add_argument(
        '--no-timecamp',
        action='store_true',
        help='Disable TimeCamp integration for this run'
    )
    parser.add_argument(
        '--reconfigure-author',
        action='store_true',
        help='Force reconfiguration of author email for all projects'
    )
    return parser.parse_args()


async def main():
    """Main execution function"""
    # Parse command-line arguments
    args = parse_arguments()
    
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
    
    # Check for TimeCamp token (optional)
    timecamp_token = os.getenv('TIMECAMP_API_TOKEN')
    timecamp_client = None
    
    if args.no_timecamp:
        print("TimeCamp integration disabled (--no-timecamp flag)")
    elif timecamp_token:
        timecamp_client = TimeCampClient(timecamp_token)
        print("TimeCamp integration enabled")
    else:
        print("TimeCamp integration disabled (no TIMECAMP_API_TOKEN found)")
    
    print(f"Timekeep - Running at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    
    try:
        # Load project configuration
        projects = load_project_config()
        print(f"Loaded {len(projects)} projects from configuration")
        
        # Get the date to analyze (from argument or default to today)
        target_date = None
        if args.date:
            # Try to parse the date in various formats
            for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y']:
                try:
                    target_date = datetime.strptime(args.date, fmt).replace(hour=0, minute=0, second=0, microsecond=0)
                    break
                except ValueError:
                    continue
            
            if target_date is None:
                print(f"Error: Could not parse date '{args.date}'. Please use format YYYY-MM-DD")
                sys.exit(1)
        else:
            # Default to today
            target_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        print(f"\nAnalyzing commits from: {target_date.strftime('%Y-%m-%d')}")
        print("-" * 50)
        
        # Analyze each project
        tasks = []
        for project in projects:
            task = analyze_project(project, target_date, projects, args.reconfigure_author)
            tasks.append(task)
        
        # Wait for all analyses to complete
        results = await asyncio.gather(*tasks)
        
        # Print summaries and submit to TimeCamp
        total_hours_all = 0
        date_str = target_date.strftime('%Y-%m-%d')
        
        for i, result in enumerate(results):
            print_project_summary(result)
            if not result.get('error'):
                total_hours_all += result['total_hours']
                
                # Submit to TimeCamp if client is available
                if timecamp_client:
                    submit_to_timecamp(timecamp_client, projects[i], result, date_str)
        
        print("\n" + "=" * 50)
        print(f"Total time across all projects: {total_hours_all:.1f} hours")
        
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Please create a projects.json file with your project configurations")
    except Exception as e:
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())