# dsh-fnos-app

给飞牛 fnOS 做「点开就能用」的网页面板应用 —— 一份踩过坑的实操手册（Agent Skill）。

把一个 Web 控制台（metacubexd、各类面板、后台）包成飞牛桌面图标的 fpk 应用：
桌面 → `/app/<app>/` → nginx → **unix socket** → 你自己的网关进程；
网关里静态文件本地发，API 反代到真正的后端，WebSocket 手动透传。

## 里面有什么

| 文件 | 作用 |
|---|---|
| `SKILL.md` | 主手册：结构、入口配置、网关五件事、同源陷阱、排错表、上线清单 |
| `reference/gateway.py` | 生产级网关（静态 + 反代 + WS + 子进程监督），改参数即可复用 |
| `reference/cmd-main` | 生命周期脚本（pidfile、TERM→KILL、status 退出码） |
| `reference/manifest.sample` | manifest 模板 |
| `reference/ui-config-iframe.json` | 桌面入口定义模板 |

## 装上它

```bash
cp -a dsh-fnos-app ~/.agents/skills/        # Claude Code / DSH 的技能目录
# 或者：~/.dsh/agents/skills/，看你用的 harness
```

之后 agent 遇到「给 fnOS 做个桌面应用」「fpk 点开白屏」「面板连不上后端」会自动加载。

## 它真正解决的问题

1. **同源**：飞牛 `/app/` 走统一登录，页面 origin 是 `https://域名:端口`，
   后端地址必须等于「页面 origin + 前缀」，否则请求在浏览器端就被拦，服务器日志里一条都没有
2. **WebSocket**：`nginx → trim_http_cgi → unix socket` 这条链带 Upgrade 头，
   但你的网关必须自己完成握手透传，否则流量图/日志流不动
3. **生命周期**：`status` 未运行必须 `exit 3`，否则应用中心状态是错的
4. **装包**：命令行装的 fpk 不生成桌面磁贴，必须走应用中心「手动安装」
5. **假故障**：端口被旧实例占着时新进程 bind 失败但看着像「配置没生效」

## License

MIT
