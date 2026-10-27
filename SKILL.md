---
name: agent-usage-report
description: >-
  Agent 使用体检：在本机统计 Claude Code、Codex 等编程 Agent 的会话记录和配置，按官方最佳实践逐项打分，
  生成中文 HTML 体检报告和不含项目信息的分享卡；改完可以复测对比。当用户说：体检、使用报告、
  我用得怎么样、我用对了吗、Agent 用得好不好、Claude Code 体检、Codex 体检、复测、再体检一次、
  生成分享卡时使用。只读本机记录，不联网、不改配置。
---

# Agent 使用体检

脚本负责数数，你负责解读。**你只读脚本输出的 `findings.json`，绝不打开原始会话记录**（`~/.claude/projects`、`~/.codex/sessions` 等），也不要自己去数数字。

下文 `<SKILL>` 指本文件所在目录。

## 流程

1. **确认 Python**：运行 `python3 --version`，需要 3.9 或更高。没有的话试 `uv run --python 3.12 python`；都没有就告诉用户安装 Python（macOS 装 Xcode 命令行工具，Windows 用 `winget install Python.Python.3.12`），然后停下。

2. **统计**：
   - 默认：`python3 <SKILL>/scripts/scan.py run`，统计最近 30 天。
   - 只有两种情况用 `--retest`：用户明确说“复测”“改完了再测一次”；或者 `~/.agent-usage-report/history/` 里最近一条记录已经超过 7 天。history 里只有不满 7 天的记录时，照常用默认命令（同一天反复运行不会做对比）。
   - 用户只想看某个产品：加 `--agents claude_code` 或 `--agents codex`。
   - 命令会在标准输出打印一段 JSON（会话数、总分、文件路径）；`compared_with` 不为空说明这次和上次做了对比。数据量大时可能要一分钟，别中途打断。

3. **读结果**：只读 `~/.agent-usage-report/latest/findings.json`（约 20–30 KB，用读文件工具读；读不全时再分段，别用 `cat`，会被截断）。重点看：
   - `actions`：脚本已按“影响 × 省事 × 安全优先”排好序的改进项，`top3` 就从这里的前几条来。每条的 `steps` 是全部做法（比如 App 里怎么点、CLI 怎么配），挑和用户相关的写进去；不确定用户用哪种就两种都写。
   - `checks[].overall`：一项检查涉及多个 Agent 时，取最差的那个（用错了 > 没用上 > 做对了）；各 Agent 自己的判定在 `agents` 里。
   - `checks[].agents[].evidence`：具体是哪个会话、哪个项目。
   - 只有判定为 bad / unused / info 的检查才带 `rx`（处方）。

4. **写总评**：在同一目录写 `narrative.json`：

   ```json
   {
     "headline": "一句话诊断，20 个汉字左右",
     "summary": "两三句总评：整体水平、最大的亮点、最该改的地方",
     "top3": ["本周就改的第一件事（带上具体命令或做法）", "第二件", "第三件"],
     "card_quote": "分享卡上的金句，20 个汉字左右",
     "findings": {"A3": "可选：把某项的发现句改写得更像人话"}
   }
   ```

   规则：
   - **数字只能来自 findings.json**。渲染时会把总评里的每个数字（包括 87%、3/11 里的 3 和 11）和 findings.json 逐个核对，对不上的会在报告里标黄。
   - 不写项目名、用户名和本机路径。处方里本来就有的命令、配置项和通用文件名（`/new`、`approval_policy`、`PLAN.md`、`~/.codex/config.toml`）可以照写。
   - `top3` 按 `actions` 的顺序取前三条；只有当某条和别的明显重复时才往后顺延。每条写清楚“做什么 + 为什么（带一个数字）”，命令照抄处方，不自己发明。
   - 字数是大概，不用数空格；超一两个字没关系，但别写成长句。
   - 语气像体检医生：直说问题，不吹捧，不说“建议多注意”这种空话。
   - `findings` 只能改写 `rewritable: true` 的检查项（只涉及一个 Agent 的那些）；其他卡片保留脚本原句。
   - 哪段文字会出现在哪：`headline`、`summary`、`top3`、`findings` 只出现在报告里；分享卡只用 `card_quote`，另外加上脚本自己算的分数和强项短板。

5. **渲染**：`python3 <SKILL>/scripts/scan.py render --narrative ~/.agent-usage-report/latest/narrative.json`
   如果输出里 `unverified_numbers` 不为空，改掉那几处数字再渲染一次。

6. **交付**：
   - 告诉用户报告位置：`~/.agent-usage-report/latest/report.html`，分享卡：`~/.agent-usage-report/latest/share-card.html`（页面上有“下载 PNG”按钮；同目录的 `share-card-x.svg`、`share-card-xhs.svg` 是横版和竖版原图）。
   - 如果你有浏览器工具，就打开这两个页面给用户看。有些浏览器工具打不开本地文件，这时先运行 `python3 -m http.server 8790 --bind 127.0.0.1 --directory ~/.agent-usage-report/latest`（后台运行），再打开 `http://localhost:8790/report.html`；看完把这个服务停掉。没有浏览器工具就只给路径。
   - 用三五行总结：总分和等级、最大的亮点、本周就改的三件事。
   - 提醒：改完一周后说“复测”，会和这次对比。

7. **不要替用户改配置**。报告最后有一段“一键交给 Agent”的提示词；用户明确要求时才按它执行，并且每改一处配置文件都先展示 diff、等确认。

## 隐私

- 脚本只读本机文件，不联网，不修改任何 Agent 的配置。
- `facts.json` / `findings.json` 只有计数和脱敏后的短例子；项目一律叫“项目 A/B”。
- `private.json` 里有项目真名，只用于 `--show-projects` 和分享卡安全检查。**不要读它，也不要把它的内容写进回复。**
- 分享卡永远不显示项目名和路径。

## 出问题时

- 某个 Agent 显示“会话级”：Codex 的 `.zst` 记录解不开（需要 Python 3.14+ 或系统 `zstd` 命令），装上 `zstd` 后重跑即可。
- 报告页头某个 Agent 的“记录可识别”低于 80%：该产品的记录格式可能更新了。读 `<SKILL>/references/data-locations.md`，再看 3 行样本的**字段名**（不看字段值），更新 `<SKILL>/scripts/collectors/` 里对应的文件。
- 其他报错：把错误原文告诉用户，不要绕过脚本自己去读原始记录。
