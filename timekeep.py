#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
# ]
# ///
"""
Timekeep - Automated time tracking for development projects
Uses git analysis and AI to estimate development time
"""

import asyncio
import json
import subprocess
import random
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional


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



async def estimate_time_with_llm(commit_info: Dict) -> Dict[str, any]:
    """
    Stub: Simulates sending commit data to LLM for time estimation
    
    In the future, this will send commit details to Claude for analysis
    """
    # Simulate async API call
    await asyncio.sleep(0.1)
    
    # Mock responses based on imaginary LLM analysis
    mock_responses = [
        {"hours": 2.5, "summary": "Implemented user authentication flow with JWT tokens and session management"},
        {"hours": 1.0, "summary": "Fixed critical bug in payment processing module affecting checkout flow"},
        {"hours": 3.0, "summary": "Refactored database schema for better performance and added indexes"},
        {"hours": 0.5, "summary": "Updated documentation and added comprehensive unit tests"},
        {"hours": 1.5, "summary": "Created new API endpoints for customer data management"},
        {"hours": 2.0, "summary": "Integrated third-party service for email notifications"},
        {"hours": 0.75, "summary": "Optimized frontend bundle size and improved load times"},
        {"hours": 4.0, "summary": "Built complete feature for real-time collaboration"},
        {"hours": 1.25, "summary": "Resolved merge conflicts and standardized code formatting"},
        {"hours": 2.75, "summary": "Implemented caching layer to reduce database queries"}
    ]
    
    # For now, return a random mock response
    # In production, this would analyze the commit details
    response = random.choice(mock_responses)
    
    # Add commit details to response
    response['commit_hash'] = commit_info['hash']
    response['author'] = commit_info['author']
    response['message'] = commit_info['message']
    
    return response


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
            'summaries': []
        }
    
    # Analyze each commit with the LLM stub
    tasks = []
    for commit in commits:
        # Stats are already included in commit from get_commits_since
        # Create async task for LLM analysis
        task = estimate_time_with_llm(commit)
        tasks.append(task)
    
    # Wait for all LLM analyses to complete
    results = await asyncio.gather(*tasks)
    
    # Calculate totals
    total_hours = sum(r['hours'] for r in results)
    
    return {
        'name': project_name,
        'path': project_path,
        'commits': len(commits),
        'total_hours': total_hours,
        'summaries': results
    }


def print_project_summary(project_result: Dict):
    """Print a formatted summary for a project"""
    name = project_result['name']
    
    if 'error' in project_result:
        print(f"\n{name}: ❌ {project_result['error']}")
        return
    
    commits = project_result['commits']
    hours = project_result['total_hours']
    
    print(f"\n{name}:")
    print(f"  📊 Commits: {commits}")
    print(f"  ⏱️  Time: {hours:.2f} hours")
    
    if project_result['summaries']:
        print("  📝 Work summary:")
        # Show top 3 work items by time
        top_work = sorted(project_result['summaries'], 
                         key=lambda x: x['hours'], 
                         reverse=True)[:3]
        
        for work in top_work:
            print(f"     - {work['hours']}h: {work['summary']}")


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
            if 'error' not in result:
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