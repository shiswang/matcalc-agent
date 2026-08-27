"""监控层回归：以真机 vasp5.4.4 OUTCAR/OSZICAR 片段为锚（nmo 114 原子弛豫）。"""
from server.matcalc import monitor as mo

# 真机锚：nmo 弛豫 OUTCAR 尾部特征行（08-26 从 master 抓取）
_REAL_OUTCAR_TAIL = (
    "   energy  without entropy=     -712.73500123  energy(sigma->0) =     -712.73499999\n"
    "  energy  without entropy=     -712.73491000  energy(sigma->0) =     -712.73490000\n"
    "  energy  without entropy=     -712.73485778  energy(sigma->0) =     -712.73485799\n"
    "------------------------ aborting loop because EDIFF is reached ---\n"
    "  free  energy   TOTEN  =        -712.73486200 eV\n"
)

_NMO_OSZICAR = """\
DAV:  27    -0.692944607131E+03    0.32813E-04   -0.83352E-05 22912
DAV:  28    -0.692944613161E+03   -0.60307E-05   -0.11539E-04 21760
DAV:  29    -0.692944621089E+03   -0.79280E-05   -0.59859E-05 19104
   1 F= -.71273486E+03 E0= -.71273486E+03  d E =-.429822E-06  mag=    61.0001
"""


def test_monitor_relax_converged_green():
    out = mo.monitor_relax(_REAL_OUTCAR_TAIL)
    assert out.startswith("弛豫监控")
    assert "3 步" in out or "离子步" in out
    assert "-712.734858" in out            # 最新能量精确命中真机值
    assert "✅ 收敛标记已出现" in out
    assert "🟢" in out


def test_monitor_relax_stagnation_yellow():
    # 连续多步几乎不动且无收敛标记 → 🟡
    tail = (
        "  energy  without entropy=     -700.00000001\n"
        "  energy  without entropy=     -700.00000002\n"
        "  energy  without entropy=     -700.00000003\n"
        "  energy  without entropy=     -700.00000002\n"
    )
    out = mo.monitor_relax(tail)
    assert "🟡" in out and "停滞" in out


def test_monitor_relax_abnormal_red():
    bad = "BOZAI: something exploded before any ionic step"
    out = mo.monitor_relax(bad)
    assert out.startswith("🔴")


def test_monitor_relax_not_outcar_rejected():
    assert mo.monitor_relax("hello world").startswith("错误")


def test_monitor_aimd_with_real_anchor():
    aimd_osz = "".join(
        f" {i} F= -700.{i:05d}E+03 E0= -700.{i:05d}E+03 d E =-.1E-04 mag= 61.0{i}\n"
        for i in range(1, 11)
    ) + " T= 298.5\n T= 301.2\n T= 302.7\n"
    out = mo.monitor_aimd(aimd_osz, aimd_osz, target_steps=100, target_temp=300.0)
    assert "AIMD 监控" in out
    assert "10/100 步 (10%)" in out
    assert "300" in out                     # 温度均值落在目标附近
    assert "61.0" in out                    # 磁矩读数


def test_monitor_aimd_no_data_rejected():
    assert mo.monitor_aimd("", "").startswith("错误")
