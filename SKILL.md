---
name: dsh-fnos-app
description: 给飞牛 fnOS 做带网页面板的 fpk 应用 — unix socket 网关、iframe/url 两种入口、SSO 同源陷阱、纯前端控制台（metacubexd 类）接入、图标生成、打包与实机验证。用户要给 fnOS 做桌面应用、把某个 Web 面板塞进飞牛、或 fpk 点开白屏/连不上后端时使用。
metadata:
  type: reference
---

# 给 fnOS 做「点开就能用」的网页面板应用

## 一句话结论

飞牛桌面磁贴 → `/app/<appname>/` → nginx → **unix socket** → 你自己的进程。
进程里跑一个**同源网关**：静态文件本地发，API 反代到真正的后端（TCP 或 unix），WebSocket 手动透传。
**前端拿到的 origin 必须等于页面自己的 origin**，否则 SSO/跨域会把它拦死。

## 什么时候用

- 要把一个 Web 控制台（metacubexd、面板、后台）做成飞牛桌面图标
- 应用要内置常驻服务（代理内核、采集器），且不想额外暴露 TCP 管理端口
- 现有 fpk 能装但点开白屏 / 面板提示"后端无法连接"

## 目录结构（native 应用）

```
<appname>/
├── manifest                 # 元信息
├── ICON.PNG / ICON_256.PNG  # 应用中心图标
├── cmd/
│   ├── main                 # start|stop|status（status 未运行必须 exit 3）
│   └── install_init …       # 8 个钩子，不做事就 exit 0
├── config/
│   ├── privilege            # {"defaults":{"run-as":"root"}}
│   └── resource
└── app/                     # 装到 /vol1/@appcenter/<appname>
    ├── bin/<daemon>         # 内核二进制
    ├── bin/gateway.py       # 网关（见 reference/）
    ├── ui/config            # 桌面入口定义
    ├── ui/images/icon_{32,64,256}.png
    ├── www/                 # 前端静态文件
    ├── data/                # 随包数据（geoip 等）
    └── config.template.yaml # 首次运行生成到 $TRIM_PKGVAR
```

现有值：`fnpack create <app> -t native` 生成骨架，`fnpack build -d .` 出 `*.fpk`。

## 入口配置：iframe vs url

**iframe（推荐，走飞牛网关，不开端口）**

```json
{".url":{"<app>.Application":{
  "title":"…","icon":"images/icon_{0}.png","type":"iframe","protocol":"",
  "gatewayPrefix":"/app/<app>","gatewaySocket":"app.sock","url":"/app/<app>/",
  "allUsers":false,"control":{"accessPerm":"editable"}}}}
```

- `gatewaySocket` 相对应用目录（`/vol1/@appcenter/<app>/`），nginx 通过 `trim_http_cgi` 转发，**带 Upgrade 头，WS 可用**
- socket 建在应用目录 → 包用户写不进去，`privilege` 一般得 `run-as: root`

**url（Plan B，独立端口）**：`"type":"url"` + `"port": 9099`，绕开 SSO 前缀，同源更简单，但会多一个端口。

## 网关必须做到的 5 件事（reference/gateway.py）

1. **剥前缀**：`/app/<app>/version` → `/version`
2. **静态优先**：命中 `www/` 就本地返回，带正确 `Content-Type` 与缓存头
3. **未知路径全反代**：API 一律打到后端 unix socket / TCP
4. **WS 透传**：客户端带 `Upgrade: websocket` 时，先向后端发握手，把 `101` 原样回给浏览器，然后双向 pipe。**这条最易翻车**，流量图、日志流全靠它
5. **监督子进程**：网关拉起内核，收到 SIGTERM 时把内核一起收掉（`cmd/main` 只记一个 pid）

## 🕳 最大的坑：同源

飞牛的 `/app/` 走统一登录（SSO）。页面能开不代表 API 能通：

- 页面 origin 是 `https://<你的域名>:8443`
- 前端里把后端地址填成 `http://127.0.0.1:9090`、`https://192.168.x.x` 都会挂：
  - https 页面请求 http → 浏览器直接拦（mixed content）
  - 换端口/换主机 → 302 到登录页 / CORS / 证书不匹配，**请求根本发不出去**（nginx 日志里一条都没有）
- 正确值永远是**页面自己的 origin + 前缀**：`https://<域名>:<端口>/app/<app>`

判据：`nginx access.log` 里是否有这次请求。
有请求但 302 → 认证/跨域；**没请求** → 浏览器在本地就拦了。

## 其他实测结论

- mihomo 的控制器**不支持** `external-controller: unix:///path`，要用 **`external-controller-unix: /path`**（CLI `-ext-ctl-unix`）
- 纯前端控制台（metacubexd）可在 `config.js` 里预置 `window.__METACUBEXD_CONFIG__ = {defaultBackendURL: …}`，省掉首启配置页
- 图标用 Pillow 生成（`pip install --target /tmp/pil pillow`，PyPI 源直连失败时挂代理 + `--index-url https://pypi.org/simple`）
- 打包前删 `.DS_Store`；`fnpack` 会把它一起塞进去
- **命令行安装（`appcenter-cli install-fpk`）不生成桌面磁贴**，要磁贴必须走「应用中心 → 手动安装」上传
- `cmd/main status`：运行返回 0，未运行必须 **exit 3**，否则应用中心状态判断错

## 本地验证（不用装包）

```bash
cp -a app /tmp/t/app
sed -i 's/mixed-port: 7890/mixed-port: 7891/; s/:1053/:1056/' /tmp/t/app/config.template.yaml
TRIM_APPDEST=/tmp/t/app TRIM_PKGVAR=/tmp/t/var bash cmd/main start
bash cmd/main status                     # 0
curl --unix-socket /tmp/t/app/app.sock http://localhost/version
curl -x http://127.0.0.1:7891 https://ifconfig.me
```

WS 验证：用短脚本握手后读一帧，看到 `HTTP/1.1 101` + 首帧即通。

**端口冲突是头号假故障**：旧实例占着端口时，新实例 bind 失败但进程仍活着，表现成"配置没生效/流量走直连"。先 `ss -ltn` 对一遍。

## 排错表

| 现象 | 先看 |
|---|---|
| 点开白屏 | 网关是否起来；`trim_http_cgi` 是否剥了前缀 |
| 面板"后端无法连接" | 后端地址是否等于页面 origin（含域名端口） |
| 面板能开、数据不刷新 | WS 透传没做或握手头没转发 |
| 端口占用 / 走直连 | `ss -ltn`，旧进程没杀 |
| 装完没图标 | 是不是命令行装的 |

## 上线前检查清单

- [ ] `manifest` 里 `appname`、`version`、`display_name` 改好（升级必须抬高 version）
- [ ] `ui/config` 的 `gatewayPrefix` 与 `cmd/main` 里的 `--prefix` **完全一致**
- [ ] `cmd/main status` 未运行返回 **3**，运行返回 0
- [ ] 打包前删掉 `.DS_Store`
- [ ] 本地 `TRIM_APPDEST/TRIM_PKGVAR` 起一遍，`/version` 能返回 JSON
- [ ] WS 路径握手回 `101`
- [ ] 面板/前端里的后端地址 = 页面 origin（含域名端口），或已用 `defaultBackendURL` 自动算
- [ ] `ss -ltn` 确认端口没被旧实例占着
- [ ] 装完在桌面上看到磁贴（命令行装的不出）

## 数据源自动刷新（订阅类应用）

面板类应用常有一个会变的外部数据源（机场订阅、规则集）。写死在包里，源一换就静默失效。

模式：

1. 启动后延迟 20–30 秒（等网络和后端就绪）拉一次，之后每 24 小时一次
2. 只替换配置里的那一段（如 `proxies:` 块），其余配置不动
3. 替换前备份 `*.bak`，拉取/解析失败就保留旧配置
4. 热重载：`PUT /configs`，body `{"path": "...", "force": true}`，正常回 `204`
5. 全程日志进 `$TRIM_PKGVAR/info.log`，出问题能回溯

## 参考文件

- `reference/gateway.py` — 生产级网关（静态 + 反代 + WS + 子进程监督），改 `--sock/--web/--prefix/--api` 即可复用
- `reference/cmd-main` — 生命周期脚本（pidfile、TERM→KILL）
- `reference/manifest.sample` — 可直接改字段
- `reference/ui-config-iframe.json` — 入口定义
