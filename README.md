# dsh-fnos-app

**给飞牛 fnOS 做「点开就能用」的网页面板应用** —— 一份踩过坑的实操手册（Agent Skill）。

它教的不是"怎么写个 Hello World fpk"，而是**怎么把一个已经存在的 Web 控制台（metacubexd、各类后台、监控面板）原封不动地塞进飞牛桌面**，让它像 Lucky 一样：点图标 → 面板直接出来 → 能用，全程不额外暴露管理端口。

---

## 这份 skill 能帮你做什么

### 1. 把一个 Web 面板做成飞牛桌面应用
生成一个完整的 native fpk 应用骨架：`manifest` + 桌面入口 + 生命周期脚本 + 图标 + 前端静态资源 + 后端守护进程。装完在桌面出现磁贴，点开即用。

### 2. 用 unix socket 网关代替暴露端口
飞牛的 `/app/<name>/` 走统一网关：

```
桌面磁贴 → /app/clashmeta/ → nginx → trim_http_cgi → app.sock → 你的网关进程
```

应用**不需要开 TCP 管理端口**，管理面藏在 socket 后面。skill 提供一套生产级网关（`reference/gateway.py`），静态文件、API 反代、WebSocket 透传、子进程监督四件事都写好了，改几个参数就能复用。

### 3. 解决 WebSocket 面板"能开但不动"
流量图、日志流、实时状态全靠 WebSocket。网关必须自己向后端发握手、把 `101` 原样回给浏览器、然后双向 pipe —— 少一步，面板就是"打开正常、数据不动"。skill 里把这段单列成一条必做项。

### 4. 治好「后端无法连接」这个经典报错
这是本次实战里最值钱的一条：

- 页面 origin 是 `https://你的域名:8443`
- 你把后端地址填成 `http://127.0.0.1:9090` → https 页面请求 http，浏览器直接拦
- 填成 `https://192.168.1.5` → 跨域/证书不匹配，请求**根本发不出去**，服务器日志里一条都没有

判据也给了：去翻 nginx access log，**有请求但 302 是认证问题，没请求就是浏览器在本地拦的**。正确值永远等于「页面 origin + 前缀」。

### 5. 避开生命周期和打包的暗坑
- `cmd/main status` 未运行必须 `exit 3`，否则应用中心状态判断全错
- 命令行装的 fpk **不生成桌面磁贴**，必须走「应用中心 → 手动安装」
- 打包前要删 `.DS_Store`
- 端口被旧实例占着时，新进程 bind 失败但看着像"配置没生效"——头号假故障

### 6. 数据源自动刷新
订阅、规则集这类会变的外部数据，写死在包里就会静默失效。skill 给了一套模式：启动延迟拉取 → 只替换配置里的那一段 → 失败保留旧配置 → `PUT /configs {"force":true}` 热重载 → 回 `204`。

---

## 目录

| 文件 | 作用 |
|---|---|
| `SKILL.md` | 主手册：目录结构、ifframe/url 两种入口、网关五件事、同源陷阱、上线检查清单、排错表 |
| `reference/gateway.py` | 生产级网关：静态 + 反代 + WS 101 透传 + 子进程监督 |
| `reference/cmd-main` | 生命周期脚本：pidfile、TERM→KILL、status 退出码 |
| `reference/manifest.sample` | manifest 模板，改字段即用 |
| `reference/ui-config-iframe.json` | 桌面入口定义模板 |

## 安装

```bash
git clone https://github.com/Lyonyonnnnn/dsh-fnos-app.git
cp -a dsh-fnos-app ~/.agents/skills/
```

之后 agent 遇到「给飞牛做个桌面应用」「fpk 点开白屏」「面板连不上后端」「把某个面板塞进飞牛」会自动加载这份手册。

## 适用前提

- 飞牛 fnOS ≥ 1.1.3100（`os_min_version`）
- 会跑 `fnpack create / build`
- 想装的是 **x86** 平台的应用

## License

MIT
