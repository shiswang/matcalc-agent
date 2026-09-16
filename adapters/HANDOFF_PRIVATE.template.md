# 私密交接清单（模板 · 勿提交真实密钥）

> 用途：代码仓库公开/外发后，**单独**把本文件填完整后加密或内网渠道交给接收方。
> 仓库内只有脱敏模板（`clusters.example.json`）；本清单**不要** commit 进 git。

接收人：________________  日期：____________  对应仓库 tag/commit：____________

---

## 1. 代码锚点

| 项 | 值 |
|----|-----|
| GitHub / 压缩包 | |
| 验收 commit | 例如 `e4309d8` |
| 本地验收 | 已跑 `scripts/smoke_local.ps1` → SMOKE PASS，62 tools |

## 2. 环境

| 项 | 值 |
|----|-----|
| Python | 3.13.x（本机验证版本） |
| Node（仅 DSH） | 22+ |
| 依赖安装 | `pip install -r requirements.txt` |
| 可选 DSH | 版本 / 安装方式： |

## 3. 集群（填入后交给对方写入本地 `clusters.json`）

### 节点 A

| 字段 | 值（私密） |
|------|------------|
| 名称 | master / … |
| host | user@ip |
| port | |
| ssh_key 路径（对方机器） | 例如 `C:\Users\<user>\.ssh\id_rsa_xxx` |
| scheduler | torque / slurm |
| queue | |
| max_ppn | |
| vasp_setup | module load … |
| vasp_exe | |
| workroot | |
| 注意事项 | CRLF/dos2unix、队列名等 |

### 节点 B（可选）

（同上结构）

## 4. SSH 密钥交接

- [ ] 私钥**不**放入邮件正文；使用加密压缩包或内网盘
- [ ] 告知对方：放入约定路径，权限仅本人可读
- [ ] 确认可 `ssh` 免密登录后再跑 `check_connection`

## 5. POTCAR / 版权

- [ ] **不分发** VASP 二进制与 POTCAR
- [ ] 告知对方赝势库应放路径：`potcars/potpaw_PBE/`（gitignore）
- [ ] 集群侧赝势目录（若远程拼 POTCAR）：

## 6. 最小验收（对方机器）

```powershell
cd <repo>
.\scripts\smoke_local.ps1
# 期望 SMOKE PASS + 62 tools

copy clusters.example.json clusters.json
# 填入第 3 节字段后：
.venv\Scripts\python.exe -c "from server import remote; print(remote.check_connection('master'))"
```

## 7. 联系与升级

| 项 | 值 |
|----|-----|
| 技术联系人 | |
| 仓库写权限 | |
| 变更纪律 | 提交前跑 smoke + pytest；加工具保持 62 契约同步 |

## 8. 已知限制（勾选已口头说明）

- [ ] VASP 步骤默认半自动；auto_submit 需真实结构
- [ ] 改 `server/main.py` 后 MCP 需重启
- [ ] Bader 历史数据可能缺失（视节点）
- [ ] 界面 ZSL 大失配会极慢
