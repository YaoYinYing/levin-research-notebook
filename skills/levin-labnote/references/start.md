# 立项与恢复

## `research_record_init` 的字段分工

```text
research_record_init(
  workspace_dir, task_id, agent_id, title, objective,
  purpose?, hypothesis?, expected_result?, implementer?, environment_location?,
  record_type?, derived_from?, retention?)
```

| 字段 | 进入报告哪里 | 写不好会怎样 |
|---|---|---|
| `objective` | 摘要第一句「本项目在做什么」 | 写"分析数据"→ 整份报告空洞 |
| `purpose` | 第 1 节 实验目的 | 空着会打印「未记录研究问题。」 |
| `hypothesis` | 页首「为什么要做」（`purpose` 缺省时的回落） | 它**不**进第 1 节，别指望它救场 |
| `expected_result` | 摘要第三句「预期结果」 | 空着打印「立项时未写明预期结果。」 |
| `implementer` | 基本情况表「实施人」 | 空着显示「未记录」 |
| `environment_location` | 基本情况表「环境位置」 | uv/conda 环境路径，不是解释器名 |
| `record_type` | 中段章节模板 | 只能是 `experiment` / `analysis` / `literature_review` |
| `derived_from` | 不渲染，但驱动 validate 的跨记录告警 | 战役分层不写就看不出谁是父谁是子 |

`implementer` 是对象，不是 JSON 字符串：`{"kind": "agent", "name": "Levin", "model": "claude"}`。
`kind` 只能是 `user` 或 `agent`。

## 恢复

`task_id` 相同 **且** `title`、`objective` 逐字节相同才会 resume，返回 `resumed:true` 与同一个
`experiment_id`。任一不同直接拒绝，不会悄悄建第二条。

拿到原文的办法：

```text
research_record_index(workspace_dir, query="")     # 行里带 title 与 objective 原文
```

或直接读 `manifest.json`。抄回去时要一字不差，包括标点与空格。

resume 时可以**补写**但不会**改写** `implementer`、`environment_location`、`expected_result`、
`derived_from`：原值为空才填。这是修 init 漏传的通道，不是事后编辑通道。

## 目录

```text
<workspace>/levin_scratch/<task_id>/<agent_id>/     可丢弃
<workspace>/levin_notebook/experiments/<exp-id>/
    manifest.json   record.md   notes.md   revisions/
    data/  scripts/  figures/  reports/
```

- `manifest.json` 是唯一权威；`record.md` 是生成视图，手改会被归档到
  `revisions/human-record-*.md` 后重建。
- 想留人类批注请写 `notes.md`。
- 持久脚本、小数据、图放实验目录里；**原始数据留在原地**，只登记引用。`raw`/`input` 放在
  `levin_scratch/` 下会被直接拒绝——scratch 可丢，证据不可丢。
- 分析脚本要复制进实验目录并**运行那份副本**，否则登记的校验和与产生输出的代码对不上。

## 读一条已有记录

先 `record.md`（与报告同构），再 `research_record_validate` 看当前结构状态，
`research_record_index(include_summary: true)` 一次看全每条记录的工件/run/检查点计数，不必开 JSON。
