# 限制与恢复（细节版）

`SKILL.md` 里那份是摘要；这里写"为什么"和"怎么办"。每条都能在源码、CI 或实测里核对。

## 工具边界

| 工具 | 它负责的 | 它不替代 |
|---|---|---|
| `init` / `checkpoint` / `index` | 稳定的文件系统实验与进展记录 | Levin 任务规划、Knowledge；现有笔记可作为 input 工件登记 |
| `register_artifact` | 证据身份与引用 | DVC/DataLad 的存储或传输；原有 URL/路径与校验和照旧 |
| `register_run` | 执行溯源与状态历史 | Levin Jobs、Slurm、MLflow 的执行/追踪；记下它们的 id 而不是取代它们 |
| `validate` | schema、引用、有界完整性 | 科学正确性、统计复核、独立复现；那些要另立检查点 |
| `finalize` | 版本化报告源 + 有界固定版式 PDF | 完整 Quarto 出版或期刊排版；要高级版式请自己编 `report.qmd` |
| `prune_reports` | 回收旧 PDF 快照 | 任何证据清理；`revisions/` 与工件永不动 |

## 规模与预算

- 单份 manifest ≤ 2 MB，artifacts/runs/checkpoints 各 ≤ 500，index 最多 10,000 条记录。
- 单次注册与单次校验的哈希预算各 64 MiB；更大的文件引用在案、不哈希，自带摘要标
  `supplied_unverified`。外部引用永不被抓取。
- 报告：≤ 200,000 字符、≤ 20 张图、≤ 500 页。每次 finalize 都是前台同步完成，没有排队。
- `index` 是每记录 haystack 上的子串 AND（≤ 8 词、200k 字符截断），无排序、无全文索引，
  行里只有身份字段。

## 部署

- v0.x 只支持本地。写记录必须指向真实工作区，不能指向 Remote 的临时 staging 副本。
  HPC/Slurm 数据只能作为引用支持。
- 插件运行时环境由插件自管、**跨项目复用**（本机位于
  `~/Library/Application Support/Levin Harness/plugins/envs/levin-research-notebook/runner/<hash>/`）。
  不要每个项目重装。
- 文件锁是本地 advisory `FileLock`；NFS/分布式锁能力不作承诺。

## 渲染

- ReportLab 是必需且钉版本的；Quarto/Typst 是可选项，不会被自动安装。
- QMD 导出设 `execute: enabled: false`。
- Markdown 表格渲成真表格但长单元格截断（全文在 `record.md`）；没有 `| --- |` 分隔行的竖线块
  按字面打印。
- 多行 `$$` 不识别；数学是栅格图，不在文本层。
- 缺字形如实渲成 `[U+XXXX]` 并写进 `unsupported_codepoints` / `transliterated_codepoints`，
  绝不静默替换成别的字。
- 只接受 TrueType 轮廓；`.otf`（CFF）被 ReportLab 拒绝。宿主没有任何可用中文字体时，
  中文会整片缺字——这是"如实报告"而不是 bug。

## 完整性与恢复

- 插件从不写原始数据。校验和能发现别的程序改动过文件；文件系统权限或 WORM 存储不在范围内。
  被管理的输出路径上的符号链接会被拒；这不是对恶意进程并发替换文件的沙箱。
- 中断写入后：查 manifest、`revisions/` 与残留 scratch。校验只读、从不修证据。原子发布
  manifest 可能早于生成 `record.md`/`index.md`；下一次授权变更会刷新视图。不要自动回滚到旧
  manifest，也不要删 scratch。
- 同一位置+同一角色重登记会就地刷新（校验和、可用性、描述、链接），包括当初文件不存在时登记
  的 raw 条目；不同角色是不同记录。raw 的校验和不同则拒绝刷新。**没有**取消登记的工具。
- 只有一次成功的 finalize 会被 `request_id` 记住；被 blocked 或渲染失败的尝试不消耗 id。
- 报告是每次尝试一个快照目录，包括 blocked 的（只有源码没有 PDF）。`render_state=failed`/
  `blocked` 都不是完成；可编辑源码会保留。
- 交付后仍可继续改动，`validate` 会报"报告过期"（报告修订号落后）。要新内容就显式重渲，
  没有任何自动重渲。

## 已知未核实（不要当成已验证）

- 本机只在 macOS 上跑过真实渲染；Linux 与 Windows 的字体候选链最近一次 CI 实测已通过
  （ubuntu 装 TrueType 中文字体、windows 用 Times/SimSun/Consolas），但那是**最近一次**结果，
  不是对任意宿主的承诺。
- `report.tex` 只生成、从未编译过。
- 复杂脚本排版、任意 Unicode 的完整覆盖，都不作保证。

## 什么时候该用真正的 ELN

需要多用户身份与权限、电子签名与合规审计、样品与仪器管理、跨数千条记录全文检索、期刊级排版
的时候，本插件不提供这些。它不是那些产品的替代品，是一条窄路径：**让一次科研任务留下能读、
能 diff、能留存的目录与报告。**
