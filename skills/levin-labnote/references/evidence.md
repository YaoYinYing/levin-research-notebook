# 证据：检查点、工件、运行

## 检查点 `research_record_checkpoint`

```text
kind ∈ method | observation | failure | conclusion | resume | note
```

一个检查点装一个有意义发现，不要一命令一条，也不要贴整段日志。

| 字段 | 作用 |
|---|---|
| `title` | 渲染成小节标题（方法 3.1、结论 6.1 …）；不给就取正文前 80 字 |
| `replica` / `retry` | 标题后加 `replica #n` / `retry #n` |
| `when_note` | 标题下一行引用块，只在方法跨日期时用 |
| `refers_to` | 「见 1. <标题>」，不重复已写过的方法 |
| `supersedes` | 更正的指向；原条保留并加删除线 |
| `evidence_ids` | 支撑证据，结论必填 |
| `execution_status` | 顺带更新记录当前状态 `wip/success/failed` |

渲染位置：`method` → 方法小节；`observation` → 5.1 看到了什么；`failure` → 5.3 意外与处置；
`conclusion` → 结论小节；`resume`/`note` → 尾部独立的「恢复与备注」区（只在有这类检查点时
出现，不打乱固定编号）。

规则：

- 结论没有 `evidence_ids` 直接拒。
- `evidence_ids` 只收**工件与运行**的 id（或它们的别名）。**检查点 id 不是证据**，报错会明说。
- 不写"无结果"/"failed"/"error"这类空话，失败必须写清坏在哪。
- `failure` 不允许被 `supersedes`——失败发生过，改它正是本插件要防的事。恢复另记 `resume`。

## 引用别名

注册时给的 `reference_id` 在这些字段里都能直接当 id 用：

`artifact.input_ids`、`artifact.script_id`、`artifact.run_id`、`run.input_ids`、
`run.output_ids`、`run.id`、`checkpoint.evidence_ids`。

```text
register_artifact(..., artifact={"role":"input","location":"data/trace.csv",
                                 "description":"...","reference_id":"alt-build-data"})
register_run(..., run={"reference_id":"run-figs","backend":"local", ...})
register_artifact(..., artifact={"role":"figure","run_id":"run-figs", ...})
```

落盘前会规范化成真 id，所以记录不会"注册成功、校验失败"。更新时**省略 `reference_id` 会保留
原值**，常规刷新不会毁掉别名。

另一个坑：`run.id` 在新建时表示**更新**，要新建就别传 id。

## 工件 `research_record_register_artifact`

角色：`raw` / `input` / `derived` / `script` / `figure` / `log` / `table` / `deliverable`。

- `deliverable` 是给人看的成品（简报、文档）；`derived` 是中间计算结果。二者都不是
  `finalize` 自己产出的 PDF。
- 注册只读文件，不复制不改动。
- 校验和就地计算（单次预算 64 MiB）；自带校验和会标成 `supplied_unverified`。没有校验和
  = 未核实证据，不是完整性证明。
- 文件还不存在就先登记为 `availability: missing`，`validate` 会报；文件出现后重登记同一
  位置+同一角色会**就地刷新**，不产生重复条目。
- 工作区外路径或 scheme URL 会被接受并告警不可移植，且**永不被访问**。
- `raw` 的校验和变了会被拒；要改只能恢复字节或换 `task_id`。
- `figure` 必须有产生它的 `run_id`；`input_ids` 与 `script_id` 可从该 run 继承。没有 run 的图
  就是装饰，直接拒。

## 运行 `research_record_register_run`

```text
backend ∈ local | levin | slurm | external
```

`host` 对 local/levin 自动填，其余必填——写计算**真正跑在哪台机器**。`environment` 必填：
软件、版本、种子。失败的运行必须给 `failure` 文本。

可用顺序：登记脚本与输入 → 登记 run（带 `input_ids`）→ 登记图（指向该 run）→ 回头更新 run 的
`output_ids`。

## 远程与 HPC

原始远程数据**留在远程**。在远程算，只把轻量结果拉回来。

- 原始件用 `source_origin:"remote_copy"` + `remote_host` + `remote_path` 登记；`ssh://`、`s3://`
  是正常写法。
- 真要落地远程 `raw`/`input` 的副本，还必须给 `remote_copy_permission` 写明谁授权；大文件一律拒。
- 拉回来的 derived 结果过大会告警：留在主机上引用即可。
- finalize 时用 `remote_space` 报远程占用，≥1 GiB 的条目要标出来。

## 底线

不覆盖原始数据，不上传私有数据，不偷偷访问外部引用，不删 scratch，不把大数据提交进 git。
任务完成不隐含任何保留策略。命令、元数据、URL 里都不许出现凭据；带 userinfo 或查询串的 URL
直接被拒。
