# GitHub Trending 每日简报（22:00 全站总榜 + 周日周报）

每天抓一次 GitHub **全站总榜**，落快照 + 出简报，和上一份快照 diff 出**新上榜 / 名次变化 / 跌出榜单**；
对 **vibecoding 工具** 和 **agent 可用的插件 / skill / MCP** 额外抓 README + 元数据，供「干嘛的 / 值不值得试 / 坑」点评；另有**赛道雷达**用 Search API 补 Trending 之外的新品；每周日再聚合一份周报。

## 运行

```bat
run_daily.cmd                          :: 全站日榜（默认）
run_daily.cmd --lang python            :: 按语言（python / typescript / rust …）
run_daily.cmd --since weekly           :: 周榜
run_daily.cmd --no-readme              :: 跳过 README 抓取（快跑）
run_daily.cmd --from-snapshot <path>   :: 用已有快照重建报告（不联网抓榜）
run_weekly.cmd                         :: 最近 7 天聚合周报
```

> PowerShell 执行策略禁止 `.ps1`，入口是 `.cmd`（内部直调捆绑 Python）。

## 配 GITHUB_TOKEN（可选，但建议）

匿名只有 **core 60/h、search 10/min**；配 token 后 5000/h，日报和雷达都不会卡。

1. 生成 token（不需要任何额外权限，只读公开仓库即可）：
   - Fine-grained：<https://github.com/settings/personal-access-tokens/new> → Repository access 选 **Public repositories (read-only)** → Generate
   - 或 Classic：<https://github.com/settings/tokens/new> → **不勾任何 scope** → Generate
2. 二选一放好（脚本按 **环境变量 → 项目内 `.github_token` → 用户目录 `~/.github_token`** 顺序读）：

   ```bat
   :: 方式 A：项目内文件（立刻生效，不用重启 DSH —— 推荐）
   echo ghp_你的token > "C:\Users\Administrator\Documents\deepseek-harness\default-workspace\github-trending\.github_token"

   :: 方式 B：用户环境变量（要重启 DSH 才被定时任务继承）
   setx GITHUB_TOKEN "ghp_你的token"
   ```
3. 验证：

   ```bat
   run_daily.cmd --check-auth
   ```

   看到 `core: x/5000` 且打印出 token 身份（登录名）就是生效了。

> `.github_token` 已写进 `.gitignore`；token 只读、随时可在 GitHub 设置里撤销。不要把 token 贴到公开聊天/issue 里。

## 产物

| 路径 | 内容 |
|---|---|
| `snapshots/YYYY-MM-DD.daily.json` | 当天快照（排名、今日新增星、总星、语言、标签、README 摘要、创建/最后提交时间、open issues、source） |
| `reports/YYYY-MM-DD.daily.md` | 日报：前十表 / 重点盯（vibecoding·agent 插件）/ 新上榜 / 近期起量候选 / 持续热 / 赛道雷达 / 跌出榜单 / 完整榜 |
| `reports/week-YYYY-MM-DD.md` | 周报：累计涨幅、榜单常客、本周新面孔、重点赛道 |
| `repos_cache.json` | 仓库元数据 + README 摘要缓存（README 3 天过期，坑信号规则改版会自动重抓） |

## 「新出现」怎么判定

1. **主判据**：与上一份 `snapshots/*.daily.json` diff → 今天有、昨天没有 = 🆕 新上榜（附 ↑↓ 名次变化）。
2. **近似判据**（首日无基线）：日榜有、月榜无 → 「近期起量候选」（月榜只 20 个名额，仅供参考）。
3. **赛道标签**：按描述/话题命中 `vibecoding`（vibe coding / prompt-to-app / no-code …）或 `agent-plugin`（skill / plugin / MCP / claude code / cursor / codex …）。
4. **赛道雷达**：Search API 查近 60–90 天新建的 vibe coding / agent skill 项目，补 Trending 看不到的赛道新品。

## 已知限制 / 坑

- **`raw.githubusercontent.com` 在本机不可用** → README 走 `api.github.com/repos/{repo}/readme`（base64）。
- **`github.com:443` 偶发连不上**（DNS 正常、TCP 被拒）：trending 页面取不到时自动降级为 **GitHub Search API 近似榜**（报告顶部会 3 行警示，且没有「今日新增星」）；再不行退出码 2。
- **未登录 API 限额很紧**：core 60/h、search 10/min。首次见到的仓库才会调 core，其余走缓存；限额耗尽时脚本**只保留页面数据、不再逐仓库重试**（不会卡住）。设置 `GITHUB_TOKEN` 可彻底避免。
- GitHub 的 `?since=daily` 页面有时返回少于 25 个仓库（2026-10-23 只有 9 个），此时「前十」= 当前全部上榜。
- 日/周/月榜是三个不同榜单，并不互为子集，交叉对比只能当参考。
- 「赛道雷达」结果按星排序、不做人工筛选，会混入噪音仓库（如蹭 vibe coding 关键词的），简报里要自己过一遍。
