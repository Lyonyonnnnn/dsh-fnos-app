#!/usr/bin/env python3
"""Clash Meta 网关：unix socket 托管 metacubexd，反代 API/WS 到 mihomo，并监督 mihomo 子进程。"""
import argparse, asyncio, os, signal, subprocess, sys, time

CT = {'.js':'text/javascript; charset=utf-8','.mjs':'text/javascript; charset=utf-8',
      '.css':'text/css; charset=utf-8','.html':'text/html; charset=utf-8','.json':'application/json',
      '.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon','.webmanifest':'application/manifest+json',
      '.woff2':'font/woff2','.woff':'font/woff','.map':'application/json','.txt':'text/plain; charset=utf-8'}

def log(msg):
    print(time.strftime('%Y-%m-%d %H:%M:%S'), msg, flush=True)

class Gateway:
    def __init__(self, web, api, prefix, sock):
        self.web = os.path.realpath(web); self.api = api
        self.prefix = (prefix or '').rstrip('/'); self.sock = sock

    def normalize(self, target):
        path = target.split('?', 1)[0]
        p, pre = path.lower(), self.prefix.lower()
        if pre and (p == pre or p.startswith(pre + '/')):
            path = path[len(self.prefix):] or '/'
        return path

    def static_file(self, path):
        rel = os.path.normpath(path.lstrip('/'))
        if rel.startswith('..'): return None
        fp = os.path.join(self.web, rel)
        if os.path.isfile(fp): return fp
        idx = os.path.join(fp, 'index.html')
        return idx if os.path.isfile(idx) else None

    async def handle(self, reader, writer):
        try:
            head = b''
            while b'\r\n\r\n' not in head:
                chunk = await reader.read(4096)
                if not chunk: writer.close(); return
                head += chunk
                if len(head) > 65536: writer.close(); return
            raw, _, rest = head.partition(b'\r\n\r\n')
            lines = raw.split(b'\r\n')
            method, target, _ = lines[0].decode('latin1').split(' ')
            headers, hmap = [], {}
            for ln in lines[1:]:
                k, _, v = ln.decode('latin1').partition(':')
                headers.append((k.strip(), v.strip())); hmap[k.strip().lower()] = v.strip()
            body = rest
            n = int(hmap.get('content-length', '0') or 0)
            while len(body) < n:
                c = await reader.read(n - len(body))
                if not c: break
                body += c
            path = self.normalize(target)
            qs = target.partition('?')[2]
            pathq = path + (('?' + qs) if qs else '')
            if hmap.get('upgrade', '').lower() == 'websocket':
                await self.ws(method, pathq, headers, reader, writer); return
            fp = self.static_file(path)
            if fp:
                data = open(fp, 'rb').read()
                ext = os.path.splitext(fp)[1].lower()
                await self.reply(writer, 200, data, CT.get(ext, 'application/octet-stream'),
                                 [('Cache-Control', 'no-cache' if ext == '.html' else 'public, max-age=86400')])
                return
            if path == '/':
                await self.reply(writer, 200, open(os.path.join(self.web, 'index.html'), 'rb').read(),
                                 'text/html; charset=utf-8'); return
            await self.proxy(method, pathq, headers, body, writer)
        except Exception as e:
            log(f"handle error: {e}")
            try: await self.reply(writer, 502, f"gateway error: {e}".encode())
            except Exception: pass
        finally:
            try: writer.close()
            except Exception: pass

    async def reply(self, w, code, body, ctype, extra=()):
        reason = {101:'Switching Protocols',200:'OK',404:'Not Found',502:'Bad Gateway'}.get(code, 'OK')
        hdr = (f"HTTP/1.1 {code} {reason}\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\n"
               f"Connection: close\r\n")
        for k, v in extra: hdr += f"{k}: {v}\r\n"
        w.write(hdr.encode() + b"\r\n" + body); await w.drain()

    async def proxy(self, method, pathq, headers, body, client):
        r, w = await asyncio.open_unix_connection(self.api)
        req = f"{method} {pathq if pathq.startswith('/') else '/'} HTTP/1.1\r\n"
        for k, v in headers:
            if k.lower() in ('host', 'connection', 'content-length', 'accept-encoding'): continue
            req += f"{k}: {v}\r\n"
        req += f"Host: localhost\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        w.write(req.encode('latin1') + body); await w.drain()
        try:
            while True:
                data = await r.read(65536)
                if not data: break
                client.write(data); await client.drain()
        finally:
            w.close()

    async def ws(self, method, pathq, headers, creader, cwriter):
        r, w = await asyncio.open_unix_connection(self.api)
        hmap = {k.lower(): v for k, v in headers}
        req = (f"{method} {pathq} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {hmap.get('sec-websocket-key','')}\r\n"
               f"Sec-WebSocket-Version: 13\r\n\r\n")
        w.write(req.encode('latin1')); await w.drain()
        hdr = await r.readuntil(b"\r\n\r\n")
        cwriter.write(hdr); await cwriter.drain()
        await asyncio.gather(self.pipe(r, cwriter), self.pipe(creader, w))

    async def pipe(self, r, w):
        try:
            while True:
                d = await r.read(65536)
                if not d: break
                w.write(d); await w.drain()
        except Exception: pass
        finally:
            try: w.close()
            except Exception: pass

    async def serve(self):
        try: os.unlink(self.sock)
        except FileNotFoundError: pass
        srv = await asyncio.start_unix_server(self.handle, path=self.sock)
        os.chmod(self.sock, 0o660)
        log(f"gateway on {self.sock}")
        async with srv: await srv.serve_forever()

def spawn_mihomo(binary, datadir):
    os.makedirs(datadir, exist_ok=True)
    cfg = os.path.join(datadir, 'config.yaml')
    if not os.path.isfile(cfg):
        tpl = os.path.join(os.path.dirname(binary), '..', 'config.template.yaml')
        open(cfg, 'w').write(open(tpl).read().replace('__DATADIR__', datadir))
        log("config.yaml 已初始化")
    for f in ('geoip.dat', 'geosite.dat', 'country.mmdb'):
        dst = os.path.join(datadir, f)
        if not os.path.isfile(dst):
            src = os.path.join(os.path.dirname(binary), '..', 'data', f)
            if os.path.isfile(src):
                import shutil; shutil.copy2(src, dst); log(f"已投放 {f}")
    logf = open(os.path.join(datadir, 'mihomo.log'), 'ab', buffering=0)
    return subprocess.Popen([binary, '-d', datadir, '-f', cfg], stdout=logf, stderr=logf, close_fds=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sock', required=True); ap.add_argument('--web', required=True)
    ap.add_argument('--prefix', default=''); ap.add_argument('--mihomo', required=True)
    ap.add_argument('--datadir', required=True)
    a = ap.parse_args()
    api = os.path.join(a.datadir, 'ctl.sock')
    proc = spawn_mihomo(a.mihomo, a.datadir)
    for _ in range(200):
        if os.path.exists(api) and proc.poll() is None: break
        time.sleep(0.1)
    def bye(*_):
        try: proc.terminate()
        except Exception: pass
        sys.exit(0)
    signal.signal(signal.SIGTERM, bye); signal.signal(signal.SIGINT, bye)
    asyncio.run(Gateway(a.web, api, a.prefix, a.sock).serve())

if __name__ == '__main__':
    main()
