import os
import subprocess
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))


def run_cmd(cmd):
    print('> ' + ' '.join(cmd))
    return subprocess.check_output(cmd, cwd=ROOT, text=True).strip()


def has_changes():
    status = run_cmd(['git', 'status', '--porcelain'])
    return status != '', status


def commit_and_push(status):
    print('\nDetected changes:')
    print(status)
    try:
        run_cmd(['git', 'add', '--all'])
        message = f'Auto commit: {datetime.now():%Y-%m-%d %H:%M:%S}'
        run_cmd(['git', 'commit', '-m', message])
    except subprocess.CalledProcessError as exc:
        print('No commit created or commit failed:', exc)
        return

    try:
        run_cmd(['git', 'push', 'origin', 'main'])
        print('Auto push completed. Waiting for next change...\n')
    except subprocess.CalledProcessError as exc:
        print('Auto push failed:', exc)


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
