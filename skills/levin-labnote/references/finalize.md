# 收尾：validate、finalize、空间、回收

## validate

`research_record_validate(experiment_id)` 只读，报两类东西，要分开读：

- `valid` —— 记录**此刻**结构是否成立。
- `final_readiness.errors` —— `finalize` 会施加的全部门禁，对当前 manifest 求值。

`final_readiness` 在活没干完时列着待办是正常的，它是清单不是判决。告警永不阻断：外部引用、
不可移植路径、报告过期、未声明的 `derived_from` 父记录、缺字形，都出现在那里。

同时返回 `reports`（total/success/blocked/failed 快照数 + `latest_success`），"哪份 PDF 是真的"
不必翻 manifest。

## finalize

```text
research_record_finalize(experiment_id, execution_status, interpretation, limitations,
  visualization, request_id?, lessons?, plans?, strategy?, method_plan?, materials?, results?,
  purpose?, environment_location?, footnotes?, remote_space?, quantities?, references?,
  citations?, reference_sections?, extra_sections?, synthesis?, search_strategy?,
  bibtex?/bibtex_path?, record_type?, font_profile?)
```

`execution_status` 是 `success` 或 `failed`——**运行怎么结束的**，不是"证明了什么"。跑成功但结论
不确定是常态，照实写。

两条决定第二次调用是否安全的语义：

- **省略 ≠ 清空**：没传的字段保留原值；显式传 `[]` 才清空。只补工件的第二次 finalize 不会抹掉
  `lessons`/`plans`/`results`。
- **`request_id` 只记忆成功的 finalize**：被 blocked 的尝试不消耗它，清掉门禁后可用同一 id 重试；
  载荷变了才需要新 id。

`interpretation`、`limitations` 必填且要具体。`visualization` 必填，即使答案是"不做图"：

```text
{"beneficial": false, "reason": "单一标量结果；画图只是装饰，不提供信息。",
 "figure_ids": [], "reviewed_by": "parent"}
```

`beneficial:true` 至少要有一个已接受的图 id。图的工作按
[visualization brief](visualization-agent.md) 交给子代理，科学判断与 `reviewed_by` 留在父级。

## 怎么读返回值

`ok` 不代表完成。看这几个：

| 字段 | 含义 |
|---|---|
| `finalized` | PDF 真的出来了 |
| `report.render_state` | `success` / `blocked` / `failed` |
| `report.pdf_path` | 没交付时是 null |
| `validation` | 当时各门禁状态 |
| `space_usage` | 实测大小与相对 init 的变化 |

被 **blocked** 的尝试不改 `execution_status`，会提交 interpretation/limitations，并留下一个
只有源码没有 PDF 的 `reports/<id>/`（`report.md`、`report.qmd`、`report.tex`）。那个目录不是结果，
对人汇报时要说明。

## 过期

交付报告后任何改动都会让它过期；`validate` 会说，并点名报告修订号与 manifest 修订号。
报告需要反映改动时用新 `request_id` 重新 finalize。没有任何东西会自动重渲。

## 空间统计

`finalize` 会量 `levin_notebook/`、`levin_scratch/` 和实验目录，并报相对 `init` 基线的增量。
遍历有上限（20 万条目、不跟随符号链接），超过会标 `truncated: true` 而不是少报。汇报时用人类
单位——KB/MB/GB，不用字节——并说明 scratch 是保留的、永不自动删除。

有 HPC 就传 `remote_space: [{host, path, bytes, files?, measured_at?, note?}]`。≥1 GiB 的条目
要标出来，那是需要人做决定的量。

## 回收

每次 finalize 都整份复制 PDF，所以 `reports/` 是线性增长：8 条记录 41 次 finalize 到了 88 MB。
`research_record_prune_reports(experiment_id, keep='last-success', dry_run?)` 删旧快照目录与对应
manifest 条目。

它永远至少留一个目录——最新的成功快照，或者一次都没成功时留最新的一次尝试——所以每个 finalize
都被 blocked 的记录不会被清空。它不动 `revisions/` 与工件；回收会推高 manifest 修订号，之后
`validate` 会说交付的 PDF 过期。先 `dry_run:true`，并把结果报出来。

## 该认得出来的失败形态

- `finalize` 返回 `ok:true` 但 `finalized:false`，是被 blocked 了，不是完成。
- blocked 尝试上 `execution_status` 变成 `failed`，那是从失败的 run 继承来的，不是这次阻断导致的。
- 少了 `interpretation` 的记录，manifest 再完美也 finalize 不了：门禁卡的是科学表述，不是 schema。
- 图丢了或读不出来会让渲染失败；源码会保留，修法是刷新那个工件再 finalize。
