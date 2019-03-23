# This file is part of OpenSnitch.
#
# Copyright(c) 2019 Nathan Todd-Stone
# me@nathants.com
# https://nathants.com
#
# This file may be licensed under the terms of of the
# GNU General Public License Version 2 (the ``GPL'').
#
# Software distributed under the License is distributed
# on an ``AS IS'' basis, WITHOUT WARRANTY OF ANY KIND, either
# express or implied. See the GPL for the specific language
# governing rights and limitations.
#
# You should have received a copy of the GPL along with this
# program. If not, go to http://www.gnu.org/licenses/gpl.html
# or write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.

import time
import sys
import logging
import opensnitch.conn
import opensnitch.shell
import opensnitch.trace
from opensnitch._netfilter import ffi


DENY = ffi.cast('int', 0)
ALLOW = ffi.cast('int', 1)
REPEAT = ffi.cast('int', 2)

_durations = {'once', '1-minute', '3-minutes', '9-minutes', 'until-quit', 'forever'}
_scopes = {'port-domain', 'domain'}
_granularities = {'just-path', 'args-and-path'}
_actions = {'yes', 'no'}
_rules_file = '/etc/opensnitch.rules'
_rules = {}

def parse_rule(line):
    try:
        action, dst, dst_port, proto, path, args = line.split(None, 5)
    except ValueError:
        logging.error(f'invalid rule, should have been "action dst dst_port proto path", was: {line}')
        return
    try:
        if dst_port != '-':
            dst_port = int(dst_port)
    except ValueError:
        logging.error(f'invalid rule: {line}')
        logging.error(f'ports should be numbers, was: {dst_port}')
        return
    if proto not in opensnitch.conn.protos:
        logging.error(f'invalid rule: {line}')
        logging.error(f'bad proto, should be one of {opensnitch.conn.protos}, was: {proto}')
        return
    if action not in _actions:
        logging.error(f'invalid rule: {line}')
        logging.error(f'bad action, should be one of {_actions}, was: {action}')
        return
    return action, dst, dst_port, proto, path, args

def persist_rule(k, v):
    dst, dst_port, proto, path, args = k
    action, _duration, _start = v
    with open(_rules_file, 'a') as f:
        f.write(f'{action} {dst} {dst_port} {proto} {path} {args}\n')

def load_permanent_rules():
    try:
        with open(_rules_file) as f:
            lines = reversed(f.read().splitlines()) # lines at top of file are higher priority
    except FileNotFoundError:
        with open(_rules_file, 'w') as f:
            lines = []
    i = 0
    for i, line in enumerate(lines):
        rule = parse_rule(line)
        if rule:
            action, dst, dst_port, proto, path, args = rule
            _rules[(dst, dst_port, proto, path, args)] = action, None, None
    for (dst, dst_port, proto, path, args), (action, _, _) in sorted(_rules.items(), key=str):
        logging.info(f'loaded rule: {action} {dst} {dst_port} {proto} {path} {args}')
    if list(lines):
        logging.info(f'loaded {i + 1} rules from: {_rules_file}')
    opensnitch.trace.run_thread(_gc)

def check(conn, prompt=True):
    src, dst, _src_port, dst_port, proto, pid, path, args = conn
    src = opensnitch.dns.get_hostname(src)
    dst = opensnitch.dns.get_hostname(dst)
    try:
        keys = [
            (dst, dst_port, proto, path, args),
            (dst, dst_port, proto, path, '-'),
            (dst, '-', proto, path, args),
            (dst, '-', proto, path, '-'),
        ]
        for k in keys:
            try:
                rule = _rules[k]
                break
            except KeyError:
                pass
        else:
            raise KeyError
    except KeyError:
        try:
            if not prompt:
                return
            duration, scope, action, granularity = opensnitch.shell.co(f'DISPLAY=:0 opensnitch-prompt "{opensnitch.conn.format(conn)}" 2>/dev/null').split()
        except:
            logging.error('failed run opensnitch-prompt')
            return opensnitch.rules.DENY
        else:
            if granularity == 'just-path':
                args = '-'
            if duration == 'once':
                return ALLOW if action == 'yes' else DENY
            else:
                _duration = duration
                if duration == 'until-quit':
                    duration = pid
                elif '-minute' in duration:
                    minutes = int(duration.split('-')[0])
                    duration = 60 * minutes
                elif duration == 'forever':
                    duration = None
                if scope == 'domain':
                    dst_port = '-'
                k = dst, dst_port, proto, path, args
                v = action, duration, time.monotonic()
                _rules[k] = v
                if duration is None:
                    persist_rule(k, v)
                    logging.info(f'add permanent rule: {action} {dst} {dst_port} {proto} {path} {args}')
                else:
                    logging.info(f'add temporary rule: {action} {_duration} {dst} {dst_port} {proto} {path} {args}')
                return check(conn)
    else:
        action, duration, start = rule
        if action == 'yes':
            return ALLOW
        elif action == 'no':
            return DENY
        assert False

def _gc():
    while True:
        pids = set(opensnitch.shell.co("ps -e | awk '{print $1}'").splitlines())
        for k, (action, duration, start) in list(_rules.items()):
            dst, dst_port, proto, path, args = k
            if isinstance(duration, int) and time.monotonic() - start > duration:
                logging.info(f'rule expired: {action} {dst} {dst_port} {proto} {path} {args}')
                del _rules[k]
            if isinstance(duration, str) and duration != 'forever' and duration not in pids:
                logging.info(f'rule for pid {duration} expired: {action} {dst} {dst_port} {proto} {path} {args}')
                del _rules[k]
        time.sleep(1)
    logging.error('trace gc exited prematurely')
    sys.exit(1)