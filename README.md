# Agent 使用体检（agent-usage-report）

> **v0.1 beta** · 只在你的电脑上运行，不联网、不上传 · 目前支持 **Claude Code** 和 **Codex**（Cursor 只体检配置）

给你的编程 Agent 做一次体检：哪些用对了、哪些用错了、哪些功能还没用上，每一条都附上可以直接执行的改法。改完过一周再测一次，看分数变化。

## 一键体检（不用安装）

把 [prompt/quick-prompt.md](prompt/quick-prompt.md) 里那段提示词整段复制，发给你的 Claude Code 或 Codex。它会下载这个仓库的固定版本、核对哈希，然后在本机统计、出报告。几分钟后你会拿到：

- `~/.agent-usage-report/latest/report.html`：体检报告
- `~/.agent-usage-report/latest/share-card.html`：分享卡（页面上能下载 PNG，不含项目名和路径）

想长期用、改完复测对比，就按下面“安装”一节装成 Skill。

## 它做什么

- **脚本数数，模型解读**：Python 脚本在本机统计会话记录和配置，模型只读汇总后的数字（几十 KB），不读几百 MB 的原始记录，也编不了数字（渲染时会逐个核对）。
- **按官方最佳实践打分**：23 项检查（其中 3 项信号较弱，只展示不计分），每项都附官方文档链接，以及可以照做的命令、提示词或配置。
- **看结果，不只看用法**：统计你多常需要指出“不对 / 报错 / 还是不行”，以及前后半段的趋势。
- **跨 Agent**：Claude Code（终端、桌面 App、VS Code）和 Codex（CLI、App）放在一份报告里，Cursor 体检配置。
- **有证据**：每个结论都写明是哪个会话、哪个项目（项目用“项目 A/B”代称）。
- **能复测**：每次的结果存进历史，复测时自动对比。
- **能晒**：分享卡横版 1200×675、竖版 1080×1350。
- **只在本机**：不联网，不上传，不修改任何 Agent 的配置。

> beta 说明：目前只在少数机器上验证过（macOS，Claude Code 桌面版和 Codex 桌面版为主）。终端版、VS Code 插件、Windows、Linux 的记录格式按官方文档适配，欢迎提 issue 反馈。

## 和官方工具有什么不同

| | 官方 `/insights` | 官方 `/doctor`、`/skill-doctor` | 本工具 |
|---|---|---|---|
| 形式 | 模型读会话写叙事复盘（英文） | 安装和配置检查，可以自动修 | 逐项打分的体检单 + 复查单（中文） |
| 数字来源 | 模型给每个会话打标签 | 本机统计 | 本机脚本统计，模型只解读 |
| 范围 | Claude Code | Claude Code | Claude Code + Codex（+ Cursor 配置） |
| 复测对比 | 无 | 无 | 有 |
| 分享卡 | 无 | 无 | 有 |

官方工具能修的问题，本工具的处方会直接让你去跑官方工具，不重复造轮子。

它和 `/insights` 是互补关系：`/insights` 读会话内容，能说出“哪次部署搞砸了”，还能写出针对项目的 CLAUDE.md 规则；本工具不读内容，所以做不到这些。本工具回答的是另一个问题：你的用法和配置离官方建议差多少，改完有没有变好。

## 安装

需要 Python 3.9 或更高版本（只用标准库，不装任何依赖）。

```bash
git clone https://github.com/kobingogo/agent-usage-report ~/.claude/skills/agent-usage-report
```

Codex、OpenCode、pi 用户可以装到共享目录：

```bash
git clone https://github.com/kobingogo/agent-usage-report ~/.agents/skills/agent-usage-report
```

然后对 Agent 说“给我做个体检”。

不想装？把 [prompt/quick-prompt.md](prompt/quick-prompt.md) 里的提示词整段发给 Agent，做一次试吃版。

## 直接用脚本

```bash
python3 scripts/scan.py detect          # 本机有哪些 Agent、数据量多大
python3 scripts/scan.py run             # 统计最近 30 天，生成报告
python3 scripts/scan.py run --retest    # 复测：只看上次体检之后的记录，并对比
python3 scripts/scan.py render --narrative ~/.agent-usage-report/latest/narrative.json
```

输出在 `~/.agent-usage-report/latest/`：

| 文件 | 内容 |
|---|---|
| `report.html` | 体检报告 |
| `share-card.html` | 分享卡（页面上能下载 PNG） |
| `findings.json` | 给模型读的判定和处方 |
| `facts.json` | 全部统计数字 |
| `private.json` | 项目真名映射，只在本机用于 `--show-projects` 和分享卡安全检查 |

历史记录在 `~/.agent-usage-report/history/`，只存分数和判定。

## 检查项

| 分区 | 检查 |
|---|---|
| A 上下文管理（25%） | 换任务就清空、很少被自动压缩、主动压缩、纠错别超过两次、调研交给子代理 |
| B 任务方法（25%） | Plan 模式、让 Agent 自己验证、/goal、独立审查；提示词具体、跑偏就打断（仅参考） |
| C 配置卫生（20%） | 规则文件覆盖、规则文件长度、Skill 装用比、重复安装、MCP 闲置、权限、hooks、密钥 |
| D 效率（10%） | 缓存命中率；按任务挑模型（仅参考） |
| E 结果信号（20%） | 返工率（每 100 条消息里指出问题的次数，含前后半段趋势）、一次做对的会话占比 |

另有“功能雷达”展示 /btw、/rewind、worktree、并行会话、Agent 向你提问等功能各用了几次，不计分。

口径、阈值和来源见 [references/metrics.md](references/metrics.md)，检查项和处方在 [checks/checks.json](checks/checks.json)。

## 支持的产品

| 产品 | 状态 |
|---|---|
| Claude Code | ✅ 逐条分析 |
| Codex | ✅ 逐条分析（7 天前压缩的 `.zst` 需要 Python 3.14+ 或系统 `zstd` 命令，否则降级为会话级） |
| Cursor | ⚙️ 只体检配置 |
| OpenCode、pi、Gemini CLI | 计划中（v1.1） |

各产品的数据位置见 [references/data-locations.md](references/data-locations.md)。

## 加一个新产品

1. 在 `scripts/collectors/` 新建一个文件，继承 `Collector`，实现 `detect()`、`collect()`、`read_config()`
2. 加进 `scripts/collectors/__init__.py` 的 `ALL`
3. 在 `checks/checks.json` 里给适用的检查项加上该产品的 `applies_to`、`basis`、`rx`
4. 在 `tests/fixtures/` 放一份脱敏样例，加测试

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## 发布（维护者）

试吃版提示词要下载固定版本并核对哈希。打 tag 之后：

```bash
curl -fsSL -o aur.tar.gz https://github.com/kobingogo/agent-usage-report/archive/refs/tags/v0.1.1-beta.tar.gz
shasum -a 256 aur.tar.gz
```

把结果填进 `prompt/quick-prompt.md` 的 `<SHA256>`，同时替换 `<OWNER>`、`<VERSION>`。

## 许可证

MIT
