import os
import subprocess
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))


def run_cmd(cmd):
    print('> ' + ' '.join(cmd))
    return subprocess.check_output(cmd, cwd=ROOT, text=True).strip()


def has_changes():
    # Check for uncommitted file changes
    porcelain_status = run_cmd(['git', 'status', '--porcelain'])
    
    # Check if there are local commits that haven't been pushed to origin/main yet
    try:
        ahead_count = run_cmd(['git', 'rev-list', '--count', 'origin/main..main'])
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
        print('Attempting to push commits to origin/main...')
        run_cmd(['git', 'push', 'origin', 'main'])
        print('Auto push completed. Waiting for next change...\n')
    except subprocess.CalledProcessError as exc:
        print('Auto push failed. Check your internet connection or DNS settings:', exc)


def main():
    print('Starting auto-upload watcher for repository at:', ROOT)
    print('This script will commit and push changes to origin/main when files change.')
    print('Press Ctrl+C to stop.\n')

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
