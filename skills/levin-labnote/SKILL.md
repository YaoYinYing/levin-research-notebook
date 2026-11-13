---
name: levin-labnote
description: 用 Levin 的 levin-research-notebook 插件为计算/实验科研任务建可追溯的电子实验记录：初始化记录、登记证据与执行溯源、写观测/结论、自动量纲核查、finalize 出 Markdown/Quarto/LaTeX 源与固定版式 PDF。当用户要"记录这次实验""留下可复现的实验记录""把结果整理成实验报告 PDF""接着上次那个实验继续""登记数据和脚本出处"，或任务涉及 MD/分析/文献调研并需要证据链时使用。
---

# Levin Labnote — 围绕 `levin-research-notebook` 的实验记录工作流

一句话：**把一次科研任务变成一份六个月后还能被自己或别的 agent 重新读懂的记录**，方式是
一个目录、一份 `manifest.json`、一组不可变修订和一份 PDF。计算仍在你原来的地方跑，本插件
只负责记录与成文。

插件只记录，**不执行科学计算**。任何"帮我跑一下 MD"都不是本技能的范围。

## 一、工作流介绍

五阶段，顺序固定。每个阶段用到哪几个工具、以及该阶段的分支文档：

| # | 阶段 | 动作 | 读哪页 |
|---|---|---|---|
| 1 | 立项 | `init` 建记录，拿到 `experiment_id` 与 scratch 目录 | [start](references/start.md) |
| 2 | 采集 | `checkpoint` 写方法/观测/失败/结论，`register_artifact` 登记数据脚本图，`register_run` 登记执行 | [evidence](references/evidence.md) |
| 3 | 成文 | `finalize` 汇总 interpretation/limitations/quantities/strategy 等，渲 PDF | [report](references/report.md) |
| 4 | 校验 | `validate` 看结构有效性 + `final_readiness`（finalize 会卡的全部门禁） | [finalize](references/finalize.md) |
| 5 | 收尾 | 报空间变化；反复 finalize 后用 `prune_reports` 回收旧快照 | [finalize](references/finalize.md) |

最小闭环（照抄即可跑通；完整参数签名见插件仓库的
`skills/levin-research-notebook-runtime/examples/calls.json`）：

```text
research_record_init(workspace_dir, task_id, agent_id, title, objective, purpose, implementer)
research_record_register_artifact(experiment_id, artifact={role:"raw", location:"data/in.csv", description:...})
research_record_register_artifact(experiment_id, artifact={role:"script", location:".../scripts/analyze.py", ...})
research_record_register_run(experiment_id, run={backend:"local", execution_status:"success",
    command:"python analyze.py", environment:{...}, input_ids:[...], output_ids:[...]})
research_record_register_artifact(experiment_id, artifact={role:"figure", location:".../figures/f1.png", run_id:...})
research_record_checkpoint(experiment_id, agent_id, kind:"observation", text:"...", evidence_ids:[...])
research_record_validate(experiment_id)
research_record_finalize(experiment_id, execution_status:"success", interpretation, limitations,
    visualization={beneficial:false, reason:"...", figure_ids:[], reviewed_by:"parent"})
```

顺序上唯一容易踩的坑：**图必须先有 run 才能登记**（图会从该 run 继承 `input_ids`/`script_id`），
然后回头用 `run.id` 更新 run 的 `output_ids`。

## 二、安装

插件与技能是两件事。**装插件**才有工具；本技能只是使用说明书。

插件状态（本机已装）：

```text
plugin_id    levin-research-notebook
deployment   levin-research-notebook__runner__local   （local，ready）
tools        8 个 research_record_* + preflight
version      以 preflight 返回的 plugin_version 为准（写这份时是 0.11.9）
```

- 已装则直接用。首次确认：调 `preflight`，看 `runtime_ready`、`model_ready`、
  `fonts.cjk_available`。
- 未装或要升级：在 Capabilities → Plugins 安装/更新 `levin-research-notebook`，再部署。
  运行时是插件自管环境（`jsonschema` / `filelock` / `reportlab` / `matplotlib` / `bibtexparser`），
  **跨项目复用**，不需要每个项目重装。
- 图谱与工具名：本机插件服务器名带部署后缀，实际暴露的名字形如
  `levin-research-notebook__runner__local`；个别环境里 `register_artifact` 会显示成
  `…__research_record__<hash>` 这类不透明名，是名称长度处理，不是缺陷。**以工具列表实际
  出现的名字为准**，报错信封里写的名字是对的。

本技能自身安装位置：

```text
~/Library/Application Support/Levin Harness/skills/levin-labnote/
```

## 三、说明（它到底做什么、不做什么）

记录落在 `<workspace>/`：

```text
levin_scratch/<task_id>/<agent_id>/          可丢弃的过程文件
levin_notebook/experiments/<exp-id>/
    manifest.json      唯一权威的结构化状态
    record.md          生成的人读视图（勿手改，手改会被归档到 revisions/human-record-*.md）
    notes.md           你自己的笔记，随便改
    revisions/         不可变历史快照
    data/ scripts/ figures/ reports/
levin_notebook/index.md
```

**报告结构**固定九节：标题 + 时间区间 → 三句摘要 + 基本情况表 → 1 目的 → 2 策略 → 3 方法与计划 →
4 材料 → 5 结果（5.1 看到 / 5.2 没看到 / 5.3 意外与处置 / 5.4 量纲核对）→ 6 结论和不足 →
7 下一步 → 8 经验教训 → 9 空间统计 → 尾注 → 分页 → 工件与溯源。`record_type`
（`experiment`/`analysis`/`literature_review`）只换中段。分节与字段对照见
[report](references/report.md)。

**它坚决不做的事**（都是硬拒绝，有测试兜底）：不跑科学计算；不改写原始文件（raw 校验和不符
直接拒）；不联网抓外部引用（`ssh://`/`s3://`/`https://` 只登记，永不被访问）；不自动删任何东西；
不换算、不改写你记下的数值。

**三条最容易误解的语义**（细节见 [finalize](references/finalize.md)、[evidence](references/evidence.md)）：

- **省略 ≠ 清空**：`finalize` 没传的字段保留原值，显式传 `[]` 才清空。
- **`ok:true` 不等于完成**：只有 `finalized` + `report.render_state` 说明 PDF 出来了。
- **别名即 id**：注册时的 `reference_id` 可直接用在 `input_ids`/`script_id`/`run_id`/`run.id`/
  `evidence_ids`，落盘前规范化成真 id。

## 四、使用

### 起一个新记录

给 `init` 的这几项直接决定报告读起来像科学还是像占位符：`objective`（做什么）、
`purpose`（为什么接着前面的工作做）、`expected_result`（预期）、`implementer`
（`{kind:"user"|"agent", name, model}`）、`environment_location`（uv/conda 环境路径）。
多条记录组成战役时传 `derived_from: [父实验 id]`。

### 恢复昨天的记录

`task_id` 相同且 `title`、`objective` **逐字节一致**才会 resume；否则拒绝而不是悄悄建重复。
从 `research_record_index` 或 manifest 里抄回原文再调用。

### 记录观测与结论

一个 checkpoint 装一个有意义发现，别一命令一条。`title` 会成为小节标题（3.1、5.1 之类）；
`replica`/`retry` 标重复；`refers_to` 引用前面已写过的方法；`when_note` 只在跨日期时用。
结论必须带 `evidence_ids`，且证据只能是 artifact 或 run——**checkpoint id 不算证据**。
写错不改旧文：追加一条带 `supersedes` 的结论/观测/方法，原文以删除线保留；`failure` 不允许被
supersede。

### 数值要带单位

数值进 `quantities`（`{name, value, unit, uncertainty?, replica?}`），别埋在正文里。量纲不符、
缺单位、无法解析、同名不同数量级、同副本重名 → 阻断；不合本库惯例的单位 → 阻断除非
`unit_acknowledged:true`；名字不在已知量族 → 显式给 `dimension:"L"` 这样的量纲式。
**永不换算你的值。** 完整表格见 [report](references/report.md#数值与量纲)。

### 出报告

`research_record_finalize(..., font_profile="scientific-cjk")` —— 中文本体；或 `cjk-sans`
（章节短、信息密）/ `latin-only`。字体由你自己按内容挑，不问用户。图放到论点旁边用
`\figure{artifact-id}`，别全堆 `\figures`。`finalize` 同时写 `report.md`（权威）/`report.qmd`/
`report.tex`/`report.pdf`。

### 交接给可视化子代理

图形值得做时，用 [visualization brief](references/visualization-agent.md) 交给一个
general-purpose worker；科学判断与 `reviewed_by` 留在你这里。

### 收尾

报空间变化用人类单位（KB/MB/GB，不用字节）。每次 finalize 都整份复制 PDF，反复 finalize 后
调 `research_record_prune_reports`（先 `dry_run:true`）回收旧快照；它永远至少留一份，不动
`revisions/` 与工件。

## 五、当前限制

诚实清单，逐条都能在源码或 CI 里核对。细节与"为什么"见 [limits](references/limits.md)。

**部署与多机**

- 只支持本地部署（`remote_ssh=False`）。写记录必须指向真实工作区，不能指向 Remote 的临时
  staging 副本。
- HPC 数据只能作引用：`source_origin:"remote_copy"` + `remote_host` + `remote_path` 记录来源，
  插件从不连接；落地远程原始文件需要显式 `remote_copy_permission`，且大文件直接拒。
- 文件锁是本地 advisory 锁（`FileLock`），两台机器共享一个 notebook 可能交错写入，NFS 上不保证。

**检索与规模**

- `index` 是每记录 haystack 上的子串 AND（最多 8 个词、200k 字符上限），无排序、无全文索引；
  行里只有身份字段，要"重建方法/结果/局限"得读 `record.md`。
- 单份 manifest ≤ 2 MB，artifacts/runs/checkpoints 各 ≤ 500，单次注册/校验哈希预算 64 MiB。
  超了要拆成多条记录。

**渲染**

- Markdown 表格渲成真表格，但**超长单元格会被截断加 `…`**（全文仍在 `record.md`）。
- 多行 `$$` 块不识别，只认单行；数学是**栅格图**，不在 PDF 文本层里，搜不到也复制不出。
- 复杂排版得上外部 Quarto/Typst；`report.tex` **只生成、从未被编译过**（本机无 TeX/Quarto）。
- 字体只接受 TrueType（`.ttf`/`.ttc`）；ReportLab 拒绝 OpenType/CFF，多数 Source Han/Noto CJK
  的 OTF 版本因此不可用。宿主无中文字体时缺字**如实报 `[U+XXXX]` 而不静默换字**。

**测试与 CI**

- 测试要 `pypdf` 才完整（缺它 1 报错 + 6 跳过，读起来像真失败）；`test_schema_surface` 还需要
  被 gitignore 的 vendored SDK，干净克隆得先 `compile` 或从发布包恢复。
- CI 三平台（ubuntu/macos/windows）已全绿，但这只是最近一次实测结果，不是对任意宿主字体的承诺。

**模型层**

- 没有自动生命周期钩子，也没有可安装的专用 subagent 类型；检查点靠本技能驱动。
- 无湿实验字段（`sample_id`、`storage` 等）——这是刻意不做，不是遗漏。
- 结论的"是否正确"插件无从判断：schema 校验通过 ≠ 科学可复现。这条差别每次都要如实说。
