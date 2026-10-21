"""案例总结文档里的数字必须与结果 JSON 一致（防文档漂移）。

`docs/024_CuFeMn_案例总结.md` 是对外的结论汇总，里面的表是**手抄**的——
手抄就会漂。这条用例把文档里的三张表逐格与
`server/outputs/024_CuFeMn_V/defect_formation_comparison_{v2,cu}/formation_energies.json`
以及两系列的形成能对照核对；数据目录不在 git 里，所以 CI 上自动跳过。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / 'docs' / '024_CuFeMn_案例总结.md'
DATA = REPO / 'server' / 'outputs' / '024_CuFeMn_V'
V_JSON = DATA / 'defect_formation_comparison_v2' / 'formation_energies.json'
CU_JSON = DATA / 'defect_formation_comparison_cu' / 'formation_energies.json'


def _sites(path: Path) -> dict[tuple[str, str], float]:
    d = json.loads(path.read_text(encoding='utf-8'))
    return {(s['site'], s['branch']): s['formation_eV'] for s in d['sites']}


def _table_rows(doc: str, header_re: str) -> dict[str, list[str]]:
    """取某张表的行：{首列: [各列文本]}。表头由 header_re 定位。"""
    lines = doc.splitlines()
    rows: dict[str, list[str]] = {}
    inside = False
    for line in lines:
        if re.search(header_re, line):
            inside = True
            continue
        if inside:
            if not line.strip().startswith('|'):
                if rows:
                    break
                continue
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            if set(''.join(cells)) <= set('-: '):   # 分隔行
                continue
            if not cells[0] or cells[0] == '位点':
                continue
            rows[cells[0]] = cells[1:]
    return rows


@pytest.fixture(scope='module')
def doc():
    if not DOC.exists():
        pytest.skip(f'案例总结文档不在: {DOC}')
    if not (V_JSON.exists() and CU_JSON.exists()):
        pytest.skip('结果 JSON 不在本机（数据目录不入 git）')
    return DOC.read_text(encoding='utf-8')


def _num(text: str) -> float:
    """文档里的数字可能带 ** 强调、用排版减号（U+2212）或千分位逗号。"""
    s = (text.replace('*', '')
             .replace('−', '-')     # 排版减号
             .replace('＋', '+')
             .replace(',', '')
             .replace(' ', ''))
    return float(s)


def _is_site(name: str) -> bool:
    """位点名形如 MnFeTi；'**平均**' 这类汇总行不是位点。"""
    return bool(re.fullmatch(r'[A-Z][A-Za-z]{3,8}', name))


def test_v_table_matches_json(doc):
    v = _sites(V_JSON)
    rows = _table_rows(doc, r'^\| 位点 \| O 空位 \| N 取代 O \| 静态作业号 \|')
    rows = {k: c for k, c in rows.items() if _is_site(k)}
    assert len(rows) == 12, f'V 表应有 12 行，实得 {len(rows)}'
    for site, cells in rows.items():
        ov, no, job = cells
        assert abs(_num(ov) - v[(site, 'O-van')]) < 5e-4, f'{site} O-van 文档 {ov} vs JSON {v[(site, "O-van")]}'
        assert abs(_num(no) - v[(site, 'N-O')]) < 5e-4, f'{site} N-O 文档 {no} vs JSON {v[(site, "N-O")]}'
        assert job.isdigit(), f'{site} 作业号不是数字: {job}'


def test_cu_table_matches_json(doc):
    c = _sites(CU_JSON)
    all_rows = _all_tables(doc, r'^\| 位点 \| O 空位 \| N 取代 O \| 静态作业号 \|')
    assert len(all_rows) == 2, f'应有两张位点表，实得 {len(all_rows)}'
    cu_rows = {k: v for k, v in all_rows[1].items() if _is_site(k)}
    assert len(cu_rows) == 12, f'Cu 表应有 12 行，实得 {len(cu_rows)}'
    for site, cells in cu_rows.items():
        ov, no, job = cells
        assert abs(_num(ov) - c[(site, 'O-van')]) < 5e-4, f'{site} O-van 文档 {ov} vs JSON {c[(site, "O-van")]}'
        assert abs(_num(no) - c[(site, 'N-O')]) < 5e-4, f'{site} N-O 文档 {no} vs JSON {c[(site, "N-O")]}'
        assert job.isdigit(), f'{site} 作业号不是数字: {job}'


def _all_tables(doc: str, header_re: str) -> list[dict[str, list[str]]]:
    """按出现顺序返回所有匹配表头的表。"""
    lines = doc.splitlines()
    tables: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] | None = None
    for line in lines:
        if re.search(header_re, line):
            current = {}
            tables.append(current)
            continue
        if current is not None:
            if not line.strip().startswith('|'):
                if current:
                    current = None
                continue
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            if set(''.join(cells)) <= set('-: '):
                continue
            if not cells[0] or cells[0] == '位点':
                continue
            current[cells[0]] = cells[1:]
    return tables


def test_comparison_table_matches_both_json(doc):
    v = _sites(V_JSON)
    c = _sites(CU_JSON)
    rows = {k: v2 for k, v2 in _table_rows(doc, r'^\| 位点 \| V O-van \| Cu O-van \|').items() if _is_site(k)}
    assert len(rows) == 8, f'对照表应有 8 行，实得 {len(rows)}'
    for site, cells in rows.items():
        vo, co, do, vn, cn, dn = cells
        assert abs(_num(vo) - v[(site, 'O-van')]) < 5e-4, f'{site} V O-van {vo}'
        assert abs(_num(co) - c[(site, 'O-van')]) < 5e-4, f'{site} Cu O-van {co}'
        assert abs(_num(vn) - v[(site, 'N-O')]) < 5e-4, f'{site} V N-O {vn}'
        assert abs(_num(cn) - c[(site, 'N-O')]) < 5e-4, f'{site} Cu N-O {cn}'
        assert abs(_num(do) - (c[(site, 'O-van')] - v[(site, 'O-van')])) < 1e-3, f'{site} Δ(O-van) {do}'
        assert abs(_num(dn) - (c[(site, 'N-O')] - v[(site, 'N-O')])) < 1e-3, f'{site} Δ(N-O) {dn}'


def test_headline_averages_in_doc_match(doc):
    """文档摘要里的平均值必须与对照表一致。"""
    v = _sites(V_JSON)
    c = _sites(CU_JSON)
    shared = ['FeTiNi', 'MnFeNi', 'MnFeTi', 'MnMnFe', 'MnMnMn', 'MnMnNi', 'MnTiNi', 'TiMnMn']
    d_ov = [c[(s, 'O-van')] - v[(s, 'O-van')] for s in shared]
    d_no = [c[(s, 'N-O')] - v[(s, 'N-O')] for s in shared]
    m_ov, m_no = sum(d_ov) / len(d_ov), sum(d_no) / len(d_no)
    assert f'{m_ov:+.3f}' in doc, f'O-van 平均 {m_ov:+.3f} 未出现在文档'
    assert f'{m_no:+.3f}' in doc, f'N-O 平均 {m_no:+.3f} 未出现在文档'
    assert f'{max(d_ov) - min(d_ov):.3f}' in doc, 'O-van 差值极差未出现在文档'
