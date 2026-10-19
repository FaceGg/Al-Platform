# -*- coding: utf-8 -*-
"""提取双轴判定与最终判定矛盾的 21 行异常数据，全列展示。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import openpyxl

XLSX = r"c:\Users\17723\.trae-cn\attachments\ab96ef22-4462-4446-95dd-43fc416c5f31_拧紧数据.xlsx"
wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
ws = wb["T_EQUIPMENT_TIGHTEN_RECORD"]

header = None
anomalies = []
for row in ws.iter_rows(values_only=True):
    if header is None:
        header = row
        continue
    a, b, f = row[16], row[18], row[25]  # DECIDE_ONE, DECIDE_TWO, DECIDE
    # 双轴OK但最终NG，或双轴NG但最终OK
    if (a == "1" and b == "1" and f == "0") or (a == "0" and b == "0" and f == "1"):
        anomalies.append(row)

print(f"异常行总数: {len(anomalies)}\n")

def fmt(v, w=13):
    s = "" if v is None else str(v)
    return s[:w].ljust(w)

# 打印关键列
keys = [0, 3, 4, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 17, 18, 25]
short = ["ID", "TACT_TIME", "工单", "产线", "工位", "工序", "设备", "程序", "目标", "上限", "下限", "一轴扭矩", "一轴判", "二轴扭矩", "二轴判", "最终判"]
print(" | ".join(s.ljust(w) for s, w in zip(short, [20,13,10,7,8,9,11,4,5,5,5,8,4,8,4,4])))
print("-" * 150)
for r in anomalies:
    print(" | ".join(fmt(r[i], w) for i, w in zip(keys, [20,13,10,7,8,9,11,4,5,5,5,8,4,8,4,4])))
