import subprocess
import pytest
import os

co = lambda *a: subprocess.check_output(' '.join(map(str, a)), shell=True, executable='/bin/bash').decode('utf-8').strip()
cc = lambda *a: subprocess.check_call(' '.join(map(str, a)), shell=True, executable='/bin/bash')

rules_file = co('mktemp')
log_file = co('mktemp')
os.environ['TINYSNITCH_RULES'] = rules_file

def logs():
    xs = co(f'cat {log_file} | grep -e "INFO allow" -e "INFO deny"').splitlines()
    xs = [x.split(' INFO ')[-1].replace('->', '').replace('|', ' ').split(None, 6) for x in xs]
    xs = [' '.join((action, proto, dst)) for action, proto, src, dst in xs]
    return xs

def run(*rules):
    co('echo >', rules_file)
    for rule in rules:
        co('echo', rule, '>>', rules_file)
    cc(f'(sudo tinysnitchd --rules {rules_file} 2>&1 | tee {log_file}) &')

udp_client = """

import socket
import sys
client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
msg = bytes(sys.argv[1], 'utf-8')
adr, port = sys.argv[2].split(':')
client_socket.sendto(msg, (adr, int(port)))
msg, adr = client_socket.recvfrom(1024)
print(msg.decode())

"""

udp_server = """

import socket
import sys
server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server_socket.bind(('', int(sys.argv[1])))
while True:
    msg, adr = server_socket.recvfrom(1024)
    if msg == b'ping':
        server_socket.sendto(b'pong', adr)
    else:
        server_socket.sendto(b'say wut now?', adr)

"""

def setup_module():
    assert co('sudo whoami') == 'root'
    cc('tinysnitch-iptables-add')
    with open('/tmp/tinysnitch_test_udp_client.py', 'w') as f:
        f.write(udp_client)
    with open('/tmp/tinysnitch_test_udp_server.py', 'w') as f:
        f.write(udp_server)

def setup_function():
    assert co('ps -ef | grep tinysnitch | grep -v -e test -e grep | wc -l') == '0', 'fatal: tinysnitch is not running'

def teardown_function():
    pids = [x.split()[1] for x in co('ps -ef|grep tinysnitch').splitlines()]
    cc('sudo kill', *pids, '&>/dev/null || true')

def test_outbound_allow():
    run('allow 1.1.1.1 53 udp',
        'allow google.com 80 tcp')
    assert co('curl -v google.com 2>&1 | grep "^< HTTP"') == '< HTTP/1.1 301 Moved Permanently'
    assert logs() == ['allow udp 1.1.1.1:53',
                      'allow udp 1.1.1.1:53',
                      'allow tcp google.com:80']

def test_outbound_deny():
    run('deny 1.1.1.1 53 udp')
    with pytest.raises(subprocess.CalledProcessError):
        cc('curl -v google.com')
    assert logs() == ['deny udp 1.1.1.1:53',
                      'deny udp 1.1.1.1:53']

def test_outbound_deny_tcp():
    run('allow 1.1.1.1 53 udp',
        'deny google.com 80 tcp')
    with pytest.raises(subprocess.CalledProcessError):
        cc('curl -v google.com')
    assert logs() == ['allow udp 1.1.1.1:53',
                      'allow udp 1.1.1.1:53',
                      'deny tcp google.com:80']

def test_inbound_allow():
    run(f'allow localhost 8000 tcp')
    proc = subprocess.Popen(f'cd $(mktemp -d) && echo bar > foo && python3 -m http.server', shell=True)
    try:
        assert co('curl localhost:8000/foo') == 'bar'
        assert logs() == [f'allow tcp localhost:8000',
                          f'allow tcp localhost:8000']
    finally:
        proc.terminate()

def test_inbound_deny_dst():
    run(f'deny localhost 8000 tcp')
    proc = subprocess.Popen('cd $(mktemp -d) && echo bar > foo && python3 -m http.server', shell=True)
    try:
        with pytest.raises(subprocess.CalledProcessError):
            cc('curl localhost:8000/foo')
        assert logs() == [f'deny tcp localhost:8000']
    finally:
        proc.terminate()

def test_inbound_deny_src():
    run(f'deny localhost 8000 tcp')
    proc = subprocess.Popen('cd $(mktemp -d) && echo bar > foo && python3 -m http.server', shell=True)
    try:
        with pytest.raises(subprocess.CalledProcessError):
            cc('curl localhost:8000/foo')
        assert logs() == [f'deny tcp localhost:8000']
    finally:
        proc.terminate()

def test_inbound_allow_udp():
    run(f'allow localhost 1200 udp')
    proc = subprocess.Popen('python3 /tmp/tinysnitch_test_udp_server.py 1200', shell=True)
    try:
        for _ in range(5):
            try:
                assert co('timeout 1 python3 /tmp/tinysnitch_test_udp_client.py ping 0.0.0.0:1200') == 'pong'
                break
            except:
                pass
        assert logs() == ['allow udp localhost:1200',
                          'allow udp localhost:1200']
    finally:
        proc.terminate()

def test_inbound_deny_dst_udp():
    run(f'deny localhost 1200 udp')
    proc = subprocess.Popen('python3 /tmp/tinysnitch_test_udp_server.py 1200', shell=True)
    try:
        for _ in range(5):
            try:
                assert co('timeout 1 python3 /tmp/tinysnitch_test_udp_client.py ping 0.0.0.0:1200') == 'pong'
                break
            except:
                pass
        assert logs() == ['deny udp localhost:1200'] * 3
    finally:
        proc.terminate()

def test_inbound_deny_src_udp():
    run(f'deny localhost 1200 udp')
    proc = subprocess.Popen('python3 /tmp/tinysnitch_test_udp_server.py 1200', shell=True)
    try:
        for _ in range(5):
            try:
                assert co('timeout 1 python3 /tmp/tinysnitch_test_udp_client.py ping 0.0.0.0:1200') == 'pong'
                break
            except:
                pass
        assert logs() == ['deny udp localhost:1200'] * 3
    finally:
        proc.terminate()
