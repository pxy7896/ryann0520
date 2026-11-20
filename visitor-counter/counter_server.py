#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""访问计数服务（仅用 Python 标准库，Ubuntu 24.04 自带 python3 可直接运行）

接口：
  GET /visit   记录一次访问（按 IP 去重），返回 {"uv": 独立访客数, "pv": 总访问次数}
  GET /count   只读查询，不计数
  GET /healthz 健康检查
数据存放在同目录 counter.db（SQLite），删除该文件即重新计数。
只监听 127.0.0.1:8899，由 Caddy 反向代理对外提供 HTTPS。
"""
import json
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8899
BASE_UV = 500  # 计数初始值（显示数 = BASE_UV + 真实访客数）；修改后 systemctl restart visitor-counter 生效
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'counter.db')
ALLOWED_ORIGINS = {'https://pxy7896.cn', 'https://www.pxy7896.cn'}

_lock = threading.Lock()


def db():
    c = sqlite3.connect(DB)
    c.execute('CREATE TABLE IF NOT EXISTS visitors (ip TEXT PRIMARY KEY, first_seen TEXT DEFAULT CURRENT_TIMESTAMP)')
    c.execute('CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, value INTEGER)')
    c.execute('INSERT OR IGNORE INTO stats (key, value) VALUES (?, 0)', ('pv',))
    return c


def visit(ip):
    with _lock:
        c = db()
        try:
            with c:
                c.execute('INSERT OR IGNORE INTO visitors (ip) VALUES (?)', (ip,))
                c.execute('UPDATE stats SET value = value + 1 WHERE key = ?', ('pv',))
                uv = c.execute('SELECT COUNT(*) FROM visitors').fetchone()[0]
                pv = c.execute('SELECT value FROM stats WHERE key = ?', ('pv',)).fetchone()[0]
        finally:
            c.close()
        return uv, pv


def counts():
    c = db()
    try:
        uv = c.execute('SELECT COUNT(*) FROM visitors').fetchone()[0]
        pv = c.execute('SELECT value FROM stats WHERE key = ?', ('pv',)).fetchone()[0]
    finally:
        c.close()
    return uv, pv


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        origin = self.headers.get('Origin', '')
        if origin in ALLOWED_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/visit':
            ip = self.headers.get('X-Forwarded-For', self.client_address[0]).split(',')[0].strip()
            uv, pv = visit(ip)
            self._send({'uv': BASE_UV + uv, 'pv': pv})
        elif path == '/count':
            uv, pv = counts()
            self._send({'uv': BASE_UV + uv, 'pv': pv})
        elif path == '/healthz':
            self._send({'ok': True})
        else:
            self.send_error(404)

    def log_message(self, fmt, *args):
        pass  # 静默运行；排查问题时可注释本行查看访问日志


if __name__ == '__main__':
    print('visitor counter listening on 127.0.0.1:%d, db=%s' % (PORT, DB))
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
