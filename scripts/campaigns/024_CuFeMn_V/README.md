# 024_CuFeMn campaign 代码（V v2 / Cu）

这里放**能产出交付结果的代码**；**数据不在这里**，在 `server/outputs/024_CuFeMn_V/`（workflows、OUTCARs、形成能、zip）。

## 为什么要把两者分开

这批脚本原本就住在数据目录 `server/outputs/024_CuFeMn_V/` 里，而 `server/outputs/` 在 `.gitignore` 中——
`git ls-files` 查这些脚本返回 **0**：能往集群提交作业的代码**从来没进过版本控制**，磁盘一坏就永久丢失，
连"改了哪一行"都查不了。2026-10-20 把它们迁到这里（数据原地不动），从此有 diff、有历史、有备份。

## 布局

```text
scripts/campaigns/024_CuFeMn_V/
├── campaign_paths.py        # 唯一定义"数据在哪"（DATA_ROOT / CU_DATA / REPO）
├── run_bk_unified.py        # 共享 helper：ROOT/CFG/SSH/SCP/moments（被 v2 与 cu 复用）
├── run_v2_campaign.py       # V 系列驱动（约定 +U：Ti 5.2 / Mn 3.9 / Fe 4.0 / Ni 6.2 / V 3.25）
├── monitor_v2_campaign.py   # V 轮询（只调 advance_workflow）
├── verify_defect_energies.py# V 独立复核（直读 OUTCAR 重算形成能）[v1|v2]
├── package_vasp_data.py     # 打包（VCALC_CAMPAIGN=v1|v2|cu）
├── make_delivery_index.py   # 生成交付清单 + sha256（交付前跑）
├── check_packaging_channels.py # 三条打包通道的回归检查（导临时目录，不覆盖已交付 zip）
├── compare_v1_v2.py         # v1（作废）与 v2 的形成能对比
└── cu/
    ├── run_cu_campaign.py       # Cu 驱动（约定 +U：…/ Cu 1.9），import run_v2_campaign 复用 helper
    ├── monitor_cu_campaign.py   # Cu 轮询
    ├── verify_cu_defect_energies.py # Cu 独立复核
    ├── audit_cu_statics.py      # 提交前本地 INCAR 协议审计
    ├── audit_cu_statics_returned.py # 回收后四查（核数/段序/U/k 点）
    ├── audit_cu_results.py      # 旧 Cu 项目 OUTCAR 审计
    ├── compare_cu_v.py          # Cu vs V 共同 8 位点对比
    ├── analyze_cu_vs_v.py       # Cu 能量表与相对排名
    ├── compare_u_assignment.py  # 旧 Cu 与 V 重算的逐元素 U 对照
    ├── extract_cu_zip.py        # 解压旧 Cu 项目归档到 cu/cu_original
    ├── dump_cu_pptx.py          # 导出旧 Cu 项目 pptx 文本（参数/结论）
    └── site_table.py            # 12 位点表（邻接金属 + 到 Cu 距离）
```

## 跑之前要知道

| 变量 | 作用 | 默认 |
|---|---|---|
| `MATCALC_CAMPAIGN_ROOT` | 数据根目录 | `<repo>/server/outputs/024_CuFeMn_V` |
| `MATCALC_OLD_CU_PROJECT` | 旧 Cu 项目几何来源（Cu 驱动的母体起点） | `E:\Project\024_CuFeMn\模拟计算` |
| `VCALC_CAMPAIGN` | 打包通道 `v1\|v2\|cu` | `v1` |
| `V2_ALLOW_SUBMIT` | `=1` 才允许提交作业 | 不提交 |

脚本一律从 `campaign_paths` 取数据路径；**不要在脚本里写死 `__file__` 的父目录当数据目录**。

## 常用命令

```powershell
cd D:\personal_files\pycharm\Ai_model\matcalc-agent\scripts\campaigns\024_CuFeMn_V

# 独立复核（不碰集群，直读 OUTCAR 重算形成能）
python cu\verify_cu_defect_energies.py
python verify_defect_energies.py v2

# 协议审计
python cu\audit_cu_statics.py
python cu\audit_cu_statics_returned.py

# Cu vs V 对比
python cu\analyze_cu_vs_v.py
python cu\compare_cu_v.py

# 打包（写到数据目录的 package/）
$env:VCALC_CAMPAIGN='cu'; python package_vasp_data.py
#   v1（历史对照）写到 024_CuFeMn_V_v1_VASP_data.zip, 不会覆盖 v2 交付包
#   解压暂存目录用完即删; package/ 里只留交付物

# 重新生成交付清单 + sha256（交付前跑）
python make_delivery_index.py

# 三条通道的回归检查（不覆盖已交付 zip）
python check_packaging_channels.py v2
```

**提交作业**需要集群与 `clusters.json`（不入库，用 `clusters.example.json` 引导）：

```powershell
$env:V2_ALLOW_SUBMIT='1'
python cu\run_cu_campaign.py      # 或 monitor_cu_campaign.py <interval> <max_iter> <gate>
```

## 两个驱动之间的关系

`run_v2_campaign.py` 与 `cu/run_cu_campaign.py` 是照着写的，**共享 15 个函数名**。
2026-10-20 用 AST 归一化逐函数比较实测：**只有 2 个真正逐字相同**（`_assert_incar_stage`、`handle`），
其余 13 个已按各自体系的约定/路径改写过（Cu 换元素、换 U、换远端目录、换"旧项目几何来源"）。

所以**没有**抽公共模块：这些是提交集群作业、又无法离线验证的代码，合并的收益小于风险。
替代做法是把这个同构关系钉住——`tests/test_campaign_driver_parity.py`：

- 共享的函数名不许悄悄消失（改名/删除会让人以为两套驱动已合并）；
- `_assert_incar_stage` / `handle` 必须保持逐字一致（漂移就红）；
- 两套 +U 约定必须覆盖同一批元素、共享元素取值相同（账本 #84 的兜底）。

真要合并时，先在集群上跑通两套驱动再动；改完记得同步 `EXPECTED_SHARED_NAMES` / `EXPECTED_IDENTICAL`。

## 仍未入 git 的脚本

v1 时代的一次性脚本**故意留在** `server/outputs/024_CuFeMn_V/`（不入 git）：
`advance.py`、`audit_returned_results.py`、`build_crosscheck.py`、`build_defects.py`、`build_v_inputs.py`、
`check_returned_inputs.py`、`collect_ready_statics.py`、`make_deploy.py`、`plot_defect_formation_comparison.py`、
`plot_sites.py`、`reconstruct_xdatcar.py`、`results.py`、`run_formation_refs.py`、`run_nitrogen_ref.py`、
`submit_ready_statics.py`、`verify_defects.py`、`verify_inputs.py`、`verify_relaxed_sites.py`、`write_overview.py`。

理由：v1 已作废（逐元素 U 映射错误，见账本 #65），这些脚本只用于复现被推翻的第一轮，
与交付结果（v2 / Cu）无依赖；它们仍按旧约定用 `__file__` 的父目录当数据目录，迁移会引入风险。
需要长期保留哪几个，迁进来即可（照 `campaign_paths` 的写法改路径）。
