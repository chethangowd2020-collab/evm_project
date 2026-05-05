import os
import subprocess
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))


def run_cmd(cmd):
    print('> ' + ' '.join(cmd))
    try:
        return subprocess.check_output(cmd, cwd=ROOT, text=True, stderr=subprocess.STDOUT).strip()
    except FileNotFoundError:
        raise RuntimeError("Command not found. Please ensure 'git' is installed and in your PATH.")
    except subprocess.CalledProcessError as e:
        error_msg = e.output.strip() if e.output else "Unknown Git error"
        if "not a git repository" in error_msg.lower():
            raise RuntimeError(f"Directory is not a Git repository. Run 'git init' first.\nDetails: {error_msg}")
        raise RuntimeError(f"Git command failed (exit {e.returncode}):\n{error_msg}")


def has_changes():
    # Check for uncommitted file changes
    porcelain_status = run_cmd(['git', 'status', '--porcelain'])
    
    # Check if there are local commits that haven't been pushed to origin/main yet
    try:
        branch = run_cmd(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
        ahead_count = run_cmd(['git', 'rev-list', '--count', f'origin/{branch}..{branch}'])
    except Exception:
        ahead_count = '0'
        
    # Return True if there are modified files OR unpushed commits
    return (porcelain_status != '' or ahead_count != '0'), porcelain_status


def commit_and_push(status):
    # Only attempt to commit if there are actually modified files
    if status != '':
        print('\nDetected file changes to commit:')
        print(status)
        try:
            run_cmd(['git', 'add', '--all'])
            message = f'Auto commit: {datetime.now():%Y-%m-%d %H:%M:%S}'
            run_cmd(['git', 'commit', '-m', message])
        except subprocess.CalledProcessError as exc:
            print('No commit created or commit failed:', exc)
            return

    try:
        branch = run_cmd(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
        
        # Sync with remote first to avoid "rejected (fetch first)" errors
        print(f'Syncing with origin/{branch}...')
        run_cmd(['git', 'pull', '--rebase', 'origin', branch])
        
        print(f'Attempting to push commits to origin/{branch}...')
        run_cmd(['git', 'push', 'origin', branch])
        print('Auto push completed. Waiting for next change...\n')
    except Exception as exc:
        print(f'\nAuto sync/push failed: {exc}')
        print('If this was a merge conflict, please resolve it manually.\n')


def main():
    print('Starting auto-upload watcher for repository at:', ROOT)
    print('This script will commit and push changes to the remote branch when files change.')
    print('Press Ctrl+C to stop.\n')

    # Initial check for git availability
    try:
        run_cmd(['git', '--version'])
    except Exception as e:
        print(f"Error: {e}")
        return

    last_status = ''
    try:
        while True:
            changed, status = has_changes()
            if changed and status != last_status:
                print('Change detected, waiting 5 seconds for stability...')
                time.sleep(5)
                changed2, status2 = has_changes()
                if changed2:
                    commit_and_push(status2)
                    last_status = ''
                else:
                    print('Changes cleared before commit.')
            else:
                last_status = status
            time.sleep(2)
    except KeyboardInterrupt:
        print('\nAuto-upload watcher stopped.')


if __name__ == '__main__':
    main()
