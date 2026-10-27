# 一段提示词：给你的 Agent 做个体检（试吃装）

> 适合不想安装 Skill 的读者：整段复制，发给 Claude Code、Codex 或其他能跑命令的 Agent。
> 它会下载**固定版本**的统计脚本，并核对哈希，不让 Agent 现编统计逻辑。这样每个人数出来的数字口径一致。
> 想长期用、要复测对比，请安装 Skill（见 README）。

下面的地址和哈希固定在 v0.1.0-beta 这个版本上。以后发新版时，维护者按 README「发布」一节重新计算并替换。

---

```text
帮我做一次“Agent 使用体检”。严格按下面的步骤做，不要跳步，也不要自己去读我的会话记录原文。

1. 确认 python3 版本 ≥ 3.9（运行 python3 --version）。不满足就告诉我怎么装，然后停下。

2. 下载固定版本的体检脚本并核对哈希：
   mkdir -p ~/.agent-usage-report/tool && cd ~/.agent-usage-report/tool
   curl -fsSL -o aur.tar.gz https://github.com/kobingogo/agent-usage-report/archive/refs/tags/v0.1.0-beta.tar.gz
   核对 sha256 必须等于 4711d52942acf28c81ac916b9873525aee3ed0049fd858b84d6d1023f7a14755（macOS 用 shasum -a 256 aur.tar.gz，Linux 用 sha256sum aur.tar.gz）。
   不一致就删掉文件、告诉我、停下。一致就解压：tar -xzf aur.tar.gz --strip-components=1

3. 运行统计（只读本机记录，不联网，不改配置）：
   python3 ~/.agent-usage-report/tool/scripts/scan.py run

4. 只读 ~/.agent-usage-report/latest/findings.json（文件较大，用读文件工具读）。不要打开 facts.json、private.json 或任何原始会话记录。

5. 按 ~/.agent-usage-report/tool/SKILL.md 第 4 步的格式，写 ~/.agent-usage-report/latest/narrative.json：
   一句话诊断、两三句总评、本周就改的三件事、一句分享卡金句。数字只能用 findings.json 里的；不写项目名和路径。

6. 渲染：python3 ~/.agent-usage-report/tool/scripts/scan.py render --narrative ~/.agent-usage-report/latest/narrative.json
   如果输出里 unverified_numbers 不为空，改掉那几处数字再渲染一次。

7. 告诉我：报告在 ~/.agent-usage-report/latest/report.html，分享卡在 ~/.agent-usage-report/latest/share-card.html；
   用三五行总结总分、最大亮点、本周就改的三件事。不要替我改任何配置。
```

---

## 不能联网时的降级版

如果 Agent 所在环境不能下载，就只做配置体检（不涉及会话记录）：

```text
不要读任何会话记录。只用 ls 和 wc 帮我看这几件事，列成一张表：
1. ~/.claude/CLAUDE.md、~/.codex/AGENTS.md 是否存在、各多少行；我最常用的项目根目录里有没有 CLAUDE.md 或 AGENTS.md
2. ~/.claude/skills、~/.agents/skills、~/.codex/skills 里各有多少个 Skill，有哪些重名
3. ~/.claude.json 里的 mcpServers、~/.codex/config.toml 里的 [mcp_servers.*] 各有几个
4. ~/.codex/config.toml 里 approval_policy 和 sandbox_mode 的值
然后告诉我：使用习惯部分（会话长度、子代理、Plan 模式、验证）需要安装完整版 Skill 才能统计。
```
