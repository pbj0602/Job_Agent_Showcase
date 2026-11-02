# Job_Agent

[English](README.md) · **中文**

一个"人在回路中"（human-in-the-loop）的求职 / 实习搜索 agent。它从公司招聘页收集岗位，逐个判断值不值得投，**每个判断都引用岗位描述里的原句作为依据**，并用一个带审计记录的状态机跟踪每一份申请。读 JD、筛选、准备材料交给 agent；最终的每个决定都由人来做。

所有个人数据（简历事实、联系方式、偏好）都放在仓库之外的私有 _vault_ 里。没有 vault 时，agent 使用一个虚构的演示候选人运行。

## 工作流程

```
 公司招聘页 (ATS)   ┐
 任意采集器写出的   ├─► 导入 ─► 分流 ─────────────► 台账 (SQLite) ─► 挑选 ──────► 准备 ──────► tracker.xlsx
 JSON 岗位记录      ┘   去重    工作许可 · 语言       13 个状态，       每日候选，    JD + 答案     人来决定，
                                 时间 · 方向           强制合法转移，    否决窗口      + 按国家选    然后投递
                                 公司规模 · 证据       审计日志                        简历模板
```

1. **收集**（`job_agent/sources/`）：对 vault 里 `companies.yml` 列出的公司，读取 Greenhouse、Lever、Ashby、SmartRecruiters、Recruitee、Workable、Teamtailor 的公开职位接口；也可以导入任何其他采集器写出的岗位记录（JSON）。`scripts/ats_probe.py` 能查出某家公司用的是哪个 ATS。
2. **分流**（`route.py`、`enrich/`、`season.py`）：每个岗位得到一个状态和一条有证据的理由——各国工作许可、语言要求、实习时间、职业方向、公司规模。
3. **台账**（`store.py`）：`discovered → awaiting_confirm / approved / manual / skipped → tailored → applied → oa / interview / offer / rejected / withdrawn`。只允许 `TRANSITIONS` 表里的转移，每次变化都写入 `events` 表。
4. **挑选与准备**（`pick.py`、`prepare.py`）：按人的偏好顺序（方向、国家、时间）给出每日候选，每家公司有上限。agent 的选择第二天才生效，留出否决的时间。对每个选中的岗位，生成 JD、常见申请问题的答案（`answers.py`），以及对应国家的简历模板。
5. **Tracker**（`tracker.py`）：一张表格完成所有操作——做决定、更新状态、写备注。每次重新生成表格前，先把人的修改读回台账。

## 设计决策

- **每个判断都附证据。** 不只是"跳过：要求瑞典语"，而是存下原句 *"Fluent Swedish is a requirement for this role"*。规则错了一眼就能看出来；规则改了，`reroute` 会对所有还没被人处理过的岗位重新分流。
- **规则是数据，不是代码。** 偏好、工作许可规则、职位方向、各国简历惯例都是 YAML（`demo_vault/`、`packs/`）。换一个求职方向只需要改配置，不用改 Python。
- **人始终在回路中。** agent 负责筛选、排序、准备材料，不替任何人投递。它的选择要等一天才生效，人的决定永远优先于 agent。
- **不确定就交给人。** JD 没读到、语言要求含糊、工作许可路径没核实的岗位，进入手动清单，不靠猜。
- **个人数据永远不进仓库。** `scripts/leak_scan.py` 在 pre-commit hook 和 CI 里，用私有黑名单和通用规则（电话号码、邮箱地址）检查每一个文件。
- **不自动操作 LinkedIn，不绕过验证码。** 需要这些的岗位进入手动清单。

## 运行

```bash
pip install pyyaml openpyxl pytest
python -m job_agent scan       # 读取演示公司的职位接口（未设置 JOB_VAULT 时使用演示 vault）
python -m job_agent route      # 为每个岗位给出状态和理由
python -m job_agent list
python -m job_agent tracker    # 生成 tracker.xlsx
pytest -q
```

用于自己的求职：把 `demo_vault/` 复制到私有位置并填好，设置 `JOB_VAULT=/path/to/your/vault`，再根据官方资料为**你自己的**护照和在读情况写 `work_authorization.yml`——演示数据只是示例。

Tracker 的表头和选项目前是中文，英文界面在规划中。

## 规划

- **数据源插件**：在 vault 里声明数据源（`sources.yml`：ATS 职位板、GitHub README 表格、RSS、JSON feed），新的数据源类型写成一个小的 Python 模块即可接入。
- **多语言界面**：tracker 支持中英文切换。
- **更多市场**：中国校园招聘的规则与数据源（届别、学历要求、秋招 / 春招 / 暑期实习）。
- 检查每份准备好的简历对 JD 关键词的覆盖。
- 根据 JD 和候选人的事实库起草开放题答案（"Why us?"），交给人修改。

## 许可证

MIT
