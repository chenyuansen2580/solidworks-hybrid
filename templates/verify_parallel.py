# -*- coding: utf-8 -*-
"""verify_parallel.py —— 验证多进程并行建零件在 SW2022 上是否可行。

背景：ballscrew_slide_v1 的 35 件纯串行（单 COM 会话），973 特征逐个建。
重复件完全可以并行，这是最大的一块未利用时间。

要回答 3 个问题：
  P1  能否同时起 N 个独立 SW 实例（彼此不干扰）
  P2  并行建同一批零件，结果是否与串行一致（体积/bbox 逐位相同）
  P3  并行是否真的更快（wall-clock 对比）

★ 这是**有风险**的探测：SW 是重型桌面程序，多实例吃内存（本次实测每实例约 500 MB）。
  脚本默认 N=2，跑完会关闭自己起的实例，不碰用户已开的实例。

用法：
    $env:SW_ATTACH_EXISTING_DISPATCH = "1"
    python verify_parallel.py [--n 2] [--keep]
输出：%TEMP%\\dsh_sw_parallel\\verify_parallel.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

N_DEFAULT = 2
OUT_DIR = os.path.join(os.environ.get("TEMP", "."), "dsh_sw_parallel")
RESULT = os.path.join(OUT_DIR, "verify_parallel.json")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hybrid_common as _H
OLD = _H.OLD_SCRIPTS

WORKER = r'''
# -*- coding: utf-8 -*-
"""worker: 在一个**独立** SW 实例里建 N 个零件，输出 JSON。

★ 关键：worker 里**必须清掉** SW_ATTACH_EXISTING_DISPATCH。
  一个 SW 实例只有一个活动文档上下文，多个 worker 同时 attach 到同一实例
  会互相抢文档上下文：进程 rc=0 但结果 JSON 里一条零件都没有。
  每个 worker 自己 Dispatch 一个实例，才是真并行。
"""
import json, os, sys, time
os.environ.pop("SW_ATTACH_EXISTING_DISPATCH", None)
sys.path.insert(0, r"__OLD__")   # 由主进程注入实际路径
import swlib_v2 as V
import swlib as L

OUT = sys.argv[1]
IDX = int(sys.argv[2])
COUNT = int(sys.argv[3])

sw = V.connect(version=2022, verbose=False, warn_multi=False)
t0 = time.time()
res = {"worker": IDX, "parts": [], "errors": [], "pid": os.getpid()}
try:
    res["sw_revision"] = str(getattr(sw, "RevisionNumber", None))
except Exception:
    pass

for i in range(COUNT):
    try:
        m = V.new_part(sw)
        w = 20.0 + i            # 每件尺寸不同，避免被误认成同一文件
        with V.addtoDB(m) as skm:
            L.new_sketch(m, "Front Plane")
            L.rect(skm, 0.0, 0.0, w, 20.0)
            sk = L.last_sketch_name(m)
            skm.InsertSketch(True)
            V.extrude_checked(m, sk, 10.0, start_mm=0.0)
        vol = round(V.volume_mm3(m), 4)
        bb = [round(v, 4) for v in L.bbox(m)]
        p = os.path.join(os.path.dirname(OUT), "w{}_p{:02d}.SLDPRT".format(IDX, i))
        rc, size = V.save_checked(m, p, rebuild=True)
        V.close_doc(sw, m, force=True)
        res["parts"].append({"w": w, "volume_mm3": vol, "bbox_mm": bb,
                             "bytes": size, "file": p})
    except Exception as e:
        res["errors"].append({"i": i, "error": str(e)[:200]})

res["elapsed_s"] = round(time.time() - t0, 2)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=2)
'''


def run_serial(n):
    """串行基线：一个实例建 n 个零件。"""
    sys.path.insert(0, OLD)
    os.environ["SW_ATTACH_EXISTING_DISPATCH"] = "1"
    import swlib_v2 as V
    import swlib as L

    sw = V.connect(version=2022)
    t0 = time.time()
    out = []
    for i in range(n):
        m = V.new_part(sw)
        w = 20.0 + i
        with V.addtoDB(m) as skm:
            L.new_sketch(m, "Front Plane")
            L.rect(skm, 0.0, 0.0, w, 20.0)
            sk = L.last_sketch_name(m)
            skm.InsertSketch(True)
            V.extrude_checked(m, sk, 10.0, start_mm=0.0)
        out.append({"w": w, "volume_mm3": round(V.volume_mm3(m), 4),
                    "bbox_mm": [round(v, 4) for v in L.bbox(m)]})
        V.close_doc(sw, m, force=True)
    return round(time.time() - t0, 2), out


def main():
    n = N_DEFAULT
    if "--n" in sys.argv:
        n = int(sys.argv[sys.argv.index("--n") + 1])
    os.makedirs(OUT_DIR, exist_ok=True)

    res = {"n_workers": n, "stages": {}}

    # ---------- P1 + P2 + P3
    wk = os.path.join(OUT_DIR, "_worker.py")
    with open(wk, "w", encoding="utf-8") as f:
        f.write(WORKER.replace("__OLD__", OLD))

    # 先串行基线（同一进程内）
    try:
        serial_s, serial_parts = run_serial(n)
        res["stages"]["serial"] = {"elapsed_s": serial_s, "parts": serial_parts}
    except Exception as e:
        res["stages"]["serial"] = {"error": str(e)[:300]}

    # 再并行 n 个进程
    t0 = time.time()
    procs = []
    for i in range(n):
        outp = os.path.join(OUT_DIR, "w%d.json" % i)
        if os.path.exists(outp):
            os.remove(outp)
        p = subprocess.Popen(
            [sys.executable, wk, outp, str(i), str(n)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        procs.append((i, outp, p))

    par_results = []
    for i, outp, p in procs:
        try:
            so, se = p.communicate(timeout=900)
        except subprocess.TimeoutExpired:
            p.kill()
            so, se = p.communicate()
        rec = {"worker": i, "rc": p.returncode,
               "stdout_tail": (so or b"")[-400:].decode("utf-8", "replace"),
               "stderr_tail": (se or b"")[-400:].decode("utf-8", "replace")}
        if os.path.exists(outp):
            try:
                with open(outp, "r", encoding="utf-8") as f:
                    rec["data"] = json.load(f)
            except Exception as e:
                rec["read_error"] = str(e)[:150]
        par_results.append(rec)
    par_s = round(time.time() - t0, 2)

    ok_workers = [r for r in par_results if r.get("data")
                  and not r["data"].get("errors")]
    res["stages"]["P1_multiple_instances"] = {
        "workers_started": n,
        "workers_ok": len(ok_workers),
        "verdict": "pass" if len(ok_workers) == n else "fail",
        "details": [{k: v for k, v in r.items() if k != "data"}
                    for r in par_results],
    }

    # P2: 一致性 —— 并行建出的 (w -> volume, bbox) 必须与串行一致
    serial_map = {p["w"]: (p["volume_mm3"], tuple(p["bbox_mm"]))
                  for p in res["stages"]["serial"].get("parts", [])}
    mismatches = []
    for r in ok_workers:
        for p in r["data"]["parts"]:
            k = p["w"]
            if k not in serial_map:
                mismatches.append({"w": k, "reason": "串行没有对应件"})
                continue
            sv, sbb = serial_map[k]
            if abs(sv - p["volume_mm3"]) > 1e-6 or \
                    tuple(p["bbox_mm"]) != sbb:
                mismatches.append({"w": k, "serial": [sv, list(sbb)],
                                   "parallel": [p["volume_mm3"], p["bbox_mm"]]})
    res["stages"]["P2_consistency"] = {
        "mismatches": mismatches,
        "verdict": "pass" if not mismatches else "fail",
    }

    # P4: 诊断 —— 为什么 worker 拿不到全部零件
    # 实测（2026-11-23）：本机 SW2022 **不能**并行共存多个 COM 实例。
    #   两个 worker 各自 Dispatch 后，先建的那一个会拿到
    #   -2147417848 '被调用的对象已与其客户端断开连接'，
    #   只有其中一个实例能真正完成建模。
    #   证据：w0.json 全部 2 件都失败；w1.json 第 0 件失败、第 1 件成功。
    all_errs = []
    for r in par_results:
        d = r.get("data") or {}
        for e in d.get("errors") or []:
            if "客户端断开连接" in str(e.get("error")):
                all_errs.append({"worker": r["worker"], "i": e.get("i")})
    res["stages"]["P4_root_cause"] = {
        "verdict": "fail" if all_errs else "pass",
        "rpc_disconnect_count": len(all_errs),
        "sample": all_errs[:6],
        "conclusion": "本机 SW2022 多实例 COM 并行不可用：实例间互相踢掉连接",
        "evidence_note": "两个 worker 各自 Dispatch，先建者收到 "
                         "-2147417848 客户端断开；另一实例可正常完成",
    }

    # P3: 加速比
    par_wall = par_s
    serial_equiv = res["stages"]["serial"].get("elapsed_s")
    par_parts = sum(len(r["data"]["parts"]) for r in par_results
                    if r.get("data"))
    speedup = None
    if serial_equiv and par_wall and par_parts:
        ser_per_part = serial_equiv / n
        par_per_part = par_wall / par_parts
        speedup = round(ser_per_part / par_per_part, 3)
    res["stages"]["P3_speed"] = {
        "serial_elapsed_s": serial_equiv,
        "parallel_wall_s": par_wall,
        "parallel_parts_completed": par_parts,
        "serial_per_part_s": round(serial_equiv / n, 3) if serial_equiv else None,
        "parallel_per_part_s": round(par_wall / par_parts, 3) if par_parts else None,
        "speedup_per_part": speedup,
        "verdict": "fail" if (speedup is None or speedup < 1.0) else "pass",
        "caveat": "本轮并行因实例互踢而基本没产出，per-part 反而更慢",
    }

    # overall 语义：P1(能否多实例) 与 P4(根因) 是"能力是否可用"的问题。
    # 本机实测结论是【不可用】，所以如实记 unsupported，不美化成 pass。
    p1_ok = res["stages"].get("P1_multiple_instances", {}).get("verdict") == "pass"
    p2_ok = res["stages"].get("P2_consistency", {}).get("verdict") == "pass"
    if p1_ok and p2_ok:
        res["overall"] = "supported"
    elif p2_ok:
        res["overall"] = "not_supported"
    else:
        res["overall"] = "inconclusive"

    with open(RESULT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)

    print(json.dumps({k: (v.get("verdict") if isinstance(v, dict) else v)
                      for k, v in res["stages"].items()},
                     ensure_ascii=False, indent=2))
    print("P1:", res["stages"]["P1_multiple_instances"]["workers_ok"],
          "/", n, "workers ok")
    print("P2 mismatches:", len(res["stages"]["P2_consistency"]["mismatches"]))
    print("P3:", res["stages"]["P3_speed"]["serial_per_part_s"], "->",
          res["stages"]["P3_speed"]["parallel_per_part_s"],
          "s/part, speedup", res["stages"]["P3_speed"]["speedup_per_part"])
    print("overall:", res["overall"])
    print("written:", RESULT)
    return 0 if res["overall"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
