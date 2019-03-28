#!/bin/bash
cd $(dirname $(dirname $(realpath $0)))

sudo find -type f \
    | grep -E "\.c$|\.o$|\.so$" \
    | xargs rm -fv

sudo pypy -c "
import os
import subprocess
import time

cc = lambda *a: subprocess.check_call(' '.join(map(str, a)), shell=True, executable='/bin/bash')
c = lambda *a: subprocess.call(' '.join(map(str, a)), shell=True, executable='/bin/bash')

_watch_skips = '/.git/', '/__pycache__/', '/.backups/', '.egg-'

def watch(root, callback=None, skips=_watch_skips, sleep=.1):
    mtimes = {}
    while True:
        files_changed = []
        for path, dirs, files in os.walk(root):
            path += '/'
            if any(skip in path for skip in skips):
                continue
            for file in files:
                file = os.path.abspath(os.path.join(path, file))
                mtime = os.path.getmtime(file)
                if file in mtimes:
                    if mtime != mtimes[file]:
                        files_changed.append(file)
                else:
                    print('watching:', file)
                mtimes[file] = mtime
        if files_changed:
            for file in files_changed:
                print('file changed:', file)
            callback()
        time.sleep(sleep)

def kill_children():
    c('kill \$(ps -ef | grep \'bin/opensnitch-\' | grep -v grep | awk \'{print \$2}\') &>/dev/null')

def restart():
    if hasattr(restart, 'proc'):
        restart.proc.terminate()
    kill_children()
    restart.proc = subprocess.Popen('pypy-ipython -ic \'from opensnitch import rules, trace, dns, conn; import opensnitch, threading; t = threading.Thread(target=opensnitch.main); t.daemon = True; t.start()\'', shell=True)

import atexit
@atexit.register
def exit():
    restart.proc.terminate()
    kill_children()

print('to cleanly exit, ^D out of ipython, then ^C to break out of the watcher loop')
restart()
watch('.', restart)

"
