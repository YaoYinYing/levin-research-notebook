# 报告：分节、数值、图、字体

## 分节表

固定骨架 + 由 `record_type` 决定的中段。空字段渲成明确的「未记录」行，缺口可见而不是消失。

| 章节 | 数据来自 |
|---|---|
| 标题 + `***YYYY-MM-DD HH:MM:SS — YYYY-MM-DD HH:MM:SS***` | `title` 与记录时间 |
| 三句摘要 + 基本情况表 | `objective` / `purpose` / `expected_result`、`implementer`、runs、`environment_location` |
| 1. 实验目的 | 只读 `purpose` |
| 2. 实验策略 | `strategy: [{title, text}]` → 2.1、2.2 … |
| 3. 实验方法和计划 | `method_plan` 要点 + method 检查点 → 3.1、3.2 … |
| 4. 实验材料 | 主机/架构、数据与脚本工件、`materials`、软件版本、非默认参数 |
| 5. 实验结果 | 5.1/5.2/5.3 来自 `results.*` 与 observation/failure 检查点；5.4 来自 `quantities` |
| 6. 实验结论和不足 | 结论检查点、`interpretation`、`limitations` |
| 7. 下一步计划 | `plans` |
| 8. 经验教训 | `lessons` |
| 9. 数据空间统计 | 实测 notebook/scratch 用量 + `remote_space` |
| 尾注 | `footnotes` |
| 工件与溯源（新页） | 工件与 run，摘要与路径用代码块 |

`record_type` 只换中段：`experiment` 如上；`analysis` 换成目的与依据/分析策略/方法与流程/
数据与工具/分析结果/证据综合；`literature_review` 换成研究问题与范围/检索策略/文献清单/
证据综合/复算与核验/引用关系。`extra_sections` 只能追加，不能改骨架顺序。

只渲出来的章节吃编号，所以没有策略的记录根本不会出现 2.x。

## 数值与量纲

带单位的数值进 `quantities`，别埋在正文里：

```text
{"name": "rmsd",     "value": 2.1,   "unit": "Å"}
{"name": "delta_g",  "value": -42.3, "unit": "kJ/mol", "uncertainty": 3.1}
{"name": "kd",       "value": 4e-10, "unit": "M",      "replica": 1}
```

5.4 表会打印记录单位、该量族的规范单位、量纲式。级别是刻意的：

| 情形 | 结果 |
|---|---|
| 量纲不符（温度记成 `ps`） | 阻断 |
| 名称暗示有单位却没给（`rmsd` 无单位） | 阻断 |
| 单位无法解析（`furlong`） | 阻断 |
| 名称不在已知量族且没声明 `dimension` | 阻断 |
| 合法但不合本库惯例（`kcal/mol` 对本库 `kJ/mol`） | 阻断，除非承认 |
| 同名两种数量级（`rmsd` 同时 `Å` 与 `nm`） | 阻断 |
| 同一副本重名 | 阻断 |

两个例外通道：

```text
{"name": "d_attack", "value": 12.0, "unit": "Å", "dimension": "L"}
{"name": "delta_g",  "value": -10.1, "unit": "kcal/mol", "unit_acknowledged": true}
```

`dimension` 填**量纲式**（`L`、`M L^2 T^-2 N^-1`、`1`），不是单位——你是在告诉检查器这是什么量。
`unit_acknowledged` 表示「就是要用这个单位」，该项转为「惯例差异」不再阻断。两者都不换算数值。

已有量族覆盖长度、时间、质量、物质的量、摩尔浓度（`mol/L`、`M`、`mM`、`µM`、`nM`、`pM`）、
温度、能量、电位（`V`、`mV`）、力、力常数、压强、面积、体积、密度、速率、速度、角度、比例。
一个量族里常规的十进前缀（`mV`、`µM`）算惯例、不告警；真换数量级才告警。

复本用 `replica`：三条轨迹同名 `rmsd` 会保持三行并带副本列。

检查器**永不换算或改写你的值**。只有真正无量纲的分数才省 `unit`。谐振力常数
（`kJ mol-1 nm-2`）与力（`kJ/mol/nm`）是两个量纲，这是刻意的。

## 数学

`$E_a = 59.5\ \mathrm{kJ\,mol^{-1}}$` 与**单行** `$$ \Delta G = \Delta H - T\Delta S $$` 走
matplotlib mathtext 离线渲：不装 TeX，不联网。mathtext 渲不出来的表达式回退成字面 `$…$`，
不会被丢掉。数学是栅格图，因此**不在 PDF 文本层**——搜不到也复制不出，正文文字可以。
显示数学必须写在一行，多行 `$$` 块不识别。

## 图

`\figures` 会把所有已接受图表堆一处。优先在论点旁写 `\figure{artifact-id}`，读者不用去别处找图；
没被这样引用的才会追加到「其余图表」。图按可印高度约 62% 缩放，装不下就换页而不是缩到看不清；
图注来自工件描述。找不到 `artifact-id` 会打印可见占位而不是让渲染失败。

不要为了让版面好看而缩小图——让它占一整页。

## 字形覆盖

`validate` 会把将要渲染的文本（记录视图 + 所有检查点正文）逐字对一遍当前 profile 实际解析到的
字体，按码位报缺字并给上下文片段。正文对 serif/CJK 面检查，代码块单独对 mono 面检查——
Menlo 有 `⇒`，所以拿 mono 检查正文会把一个在 PDF 里仍缺的字判成正常。上下标会转写成 caret
记法，不报缺。

这条告警是建议性的：仍可 finalize，渲完的 `unsupported_codepoints` 才是权威记录。因为检查点
只追加，修法是在 finalize 前改措辞或用 `supersedes` 更正，不是编辑旧文。

## 可编辑产物

每个报告目录里有：

| 文件 | 角色 |
|---|---|
| `report.md` | 权威；由 manifest 重新生成 |
| `report.qmd` | Quarto 包装，`execute: enabled: false` |
| `report.tex` | 独立 xelatex/lualatex 源（article + xeCJK + Times/Menlo） |
| `report.pdf` | ReportLab 产出的固定版式成品 |

成品 PDF 从不依赖 TeX；`report.tex` 是给"想自己排版"的人。重生成而不是手改 `report.md`。

## 字体

渲染器从不问用户选字体。它按 **profile**（排版意图）在本机实际存在的字体里解析，并记录用了什么。

| Profile | 正文（拉丁 + 中日韩） | 什么时候用 |
|---|---|---|
| `scientific-cjk`（默认） | Times + 宋体 | 中文正文、英文术语、正式记录 |
| `cjk-sans` | Times + 黑体正文 | 章节短、信息密的简报 |
| `latin-only` | Times + 宋体兜底 | 英文报告、少量中文 |

按内容选，不是按偏好。`auto` 等于默认。

两个宿主事实：缺中文面时 PDF 里是静默的，但在两处会喊出来——渲染前 `preflight.fonts.cjk_available`、
渲染后 `report.fonts.notes`，**先查前者**，为 false 时中文一律变 `[U+XXXX]`。第二，只有 TrueType
轮廓（`.ttf`/`.ttc`）能用；ReportLab 拒绝 OpenType/CFF，多数 Source Han / Noto CJK 的 OTF 版本
因此不可用，候选链写了多个平台的拼写而不是一个期望名字。

代码栅栏用 Menlo（或平台等宽）并带关键字/字符串/注释高亮，记得给栅栏标语言。图内文字用
matplotlib 的 Arial + 黑体，图注用正文字体。
