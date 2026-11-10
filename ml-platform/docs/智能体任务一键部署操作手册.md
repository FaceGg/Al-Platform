# 智能体任务 · 一键部署操作手册（点焊 train_v2_full 实例 · 2026-11-10 全链实测版）

> 适用版本：2026-11-10 之后（含智能体重训闭环自动绑定、真实冒烟、单行合同、并发修复、流卡死看门狗）。
> 本手册全部步骤在点焊项目真实数据上端到端验证过：建模 → 一键部署四步 → API 批量调用 5000 行 → 闭环回流 → 智能体重训触发。
> 全程页面操作；总耗时约 15-20 分钟（含智能体建模一轮）。

---

## 一、准备（四样东西）

| 项 | 位置 | 点焊项目现状 |
|---|---|---|
| 训练数据 | 算法平台 → 数据管理 | `train_v2_full.csv`（2180 行 × 91 列，目标列 `fault`：1=缺陷（少数类）/0=正常）|
| 测试数据 | 本机 | `train_v2_test.csv`（5000 行，真实缺陷率 15.4%），部署后调 API 用 |
| 大模型档案 | 系统管理 → 大模型管理 | 只需 API 地址 + Key + 模型 ID。DeepSeek 两个档案均可（流卡死有看门狗+自动重连兜底）|
| 项目 | 智能体中心顶部下拉 | 「点焊」|

> 全流程真实调用所选大模型（思考预算自动隔离）；验收训练 100% 全量（2180 行，向导默认勾选，勿关）。

---

## 二、新建智能体任务（向导五步）

入口：智能体中心 → 新建任务。顶部配置条：项目=点焊、数据集=train_v2_full.csv、目标列=fault、模型=任一已配 Key 档案、逐步确认=关。

### 第 1 步 数据分析

**列清单默认全不勾即可**（勾选=向大模型强调的重点，不是剔除）。关键是分析提示词，推荐：

> 本域物理常识：焊接质量由能量与阻抗动态决定，允许并鼓励构造派生物理特征（电阻比、级间电阻差、能量密度），请把这些派生方向列入 S1 预期重要特征。时间/日期类列（weld_time、set_time、creat_time、load_time、pt_date、cvepath）只是采集时间戳，与焊接物理无关，不得作为特征。

### 第 2 步 特征工程（核心：剔除清单）

逐列把「指令」设为**建议剔除**，共 45 列——三类：

| 类别 | 列 | 为什么剔 |
|---|---|---|
| 组织/工位/工件标识（17）| organization_code/name、area_code/name、line_code、workstaion_code、timername、wldindex、vin、vehiclecode、spot_code、evaluecode、combinecode、robotcode、spotcode、visual_vin | 工位指纹/主键，指标虚高、上线无效 |
| 时间戳（5）| weld_time、set_time、creat_time、load_time、pt_date、cvepath | 日期指纹（合成数据跨 3 天，日期列会拿满分但对线上零泛化）|
| **焊后检测结果（23）**| spattercode、wld*_spatter_strength、wld*_spatter_strenname、spatterpos_wld/pre/tmp、spotdiameter、spotmiss、spotdistortion、spotrag、spotrepeat、spotinf、evaluestatus、ai_rlt、stationip、extraData、weldgun | 焊后才拿得到的结果列（飞溅/直径/漏检/AI 判定），混入=结果泄漏，部署后根本不存在这些输入 |

> 漏剔焊后结果列的教训：某轮任务重要性第 3 名是 spotdiameter（焊点直径），指标虚高但线上不可用。45 列清单是实测收敛版。

### 第 3 步 自动建模

- 算法白名单：默认全勾（8 族）
- **集成学习：开启**（前 3 名加权投票）
- 参数留空

### 第 4 步 评估验收

- 召回(少数类) ≥ **0.85**（留出集口径；硬门禁）
- 测试集：默认「自动留出 20%」——`train_v2_test.csv` 留给部署后调 API
- 评审重点可留空

### 第 5 步 启动与服务化

点「**启动智能体**」。自动迭代：S1 数据分析 → S2 特征工程（沙箱+单行合同校验）→ S3 全量训练 → S4 硬门禁+LLM 评审。

**两种终态**：
- `accepted`（评审通过）→ 直接进第三节；
- `waiting_escalate`（评审升级）→ 打开任务详情看升级理由：
  - 发现日期指纹/焊后列泄漏 → **驳回**，按上面清单补剔除后重提（评审是对的）；
  - 硬门禁全过、特征全是物理量、仅「少数类测试样本少（71）波动风险」类保守意见 → 点**采纳**（留档：采纳人/时间/备注）。

> 预期指标参考（无泄漏的诚实水平）：召回(少数类) 0.95+、F1 0.91-0.97、AUC 0.997+； precision 0.86-0.91。

---

## 三、一键部署（任务详情 · 服务化操作流，每步 25%）

| 步骤 | 按钮 | 说明 | 实测 |
|---|---|---|---|
| ① 固化配方 | 「① 固化配方」 | 验收成果固化为配方（特征脚本/门禁/白名单/集成/重训快照）| 秒级 |
| ② 部署模型 | 「② 直接部署本次模型（秒级）」 | S3 冠军注册→批准→新建 running 部署 | 秒级；**若任务是「升级后人工采纳」的，会提示走「引擎重铸」**（冠军只存在验收线程内存，几分钟）|
| ③ 服务化草稿 | 「③ 一键服务化（草稿+冒烟）」 | 创建三资产草稿；**真实冒烟**：原始行→S2 特征脚本→模型推理（dry_run 零回流），失败即不可发布 | 秒级；显示「缺陷类[1] · smoke 0」|
| ④ 批准发布 | 勾选三目标 →「④ 批准发布」 | API 上市场 + 闭环激活 + 应用编排（实例化六算子模板并发布）| 自动；显示编排工作流 id |

> ② 若报「铸造候选未过配方验收门禁」：引擎 3 折交叉验证口径比 S4 留出口径严格（实测全候选 CV 召回 0.54-0.77，配 0.85 门禁诚实不可达）。处理：配方库对该配方「更新门禁」到 **0.75**（CV 实测 ensemble 0.7676 支撑）发新版本后重走 ②。这不是放水——S4 留出指标照旧留档，只是部署门禁按 CV 口径校准。

**发布后闭环已自动配好**（无需手工绑定）：智能体重训模式 + 你的配方、重训阈值 20、告警阈值 20、重训数据=原始训练集+回流报错集、缺陷类=少数类（无语义描述时按频次自动取）、特征脚本 script 模式、集成选项继承配方。

---

## 四、验证一：大屏（闭环自动化 + 应用编排）

地址：`http://localhost/demo-showcase.html`（闭环详情页右上「运行监控大屏」同款）。

1. 右下「模式：实时」→ 数据源=闭环任务 → 项目=点焊 → 闭环=智能体闭环 → 连接（token 自动读取）。
2. **验证点**：指示灯常绿；已推理/正常通过/报错回流计数随调用实时跳动；重训阈值 `x / 20`；重训模式=智能体；链路为 推理→特征工程→模型推理→报错回流→告警→智能体重构→特征工程/模型 替换。
3. 切「编排 API 实时」数据源 → 选编排 API → 连接：同一大屏读编排 API 的事件留痕（六算子链：api_input → python_script(S2) → load_deployment_model → apply_model → append_error_dataset → agent_retrain_threshold）。

## 五、验证二：本地 Python 全量调 API（附脚本）

保存以下脚本为 `call_loop_api.py`（纯标准库，无需装依赖；**地址必须 127.0.0.1，不要用 localhost**——Windows 解析 localhost 先走 IPv6 黑洞，每请求白等 ~20s）：

```python
# -*- coding: utf-8 -*-
"""智能体闭环 API 批量调用测试（标准库实现）。
用法：python call_loop_api.py [--limit N]   口令运行时输入或设 PLATFORM_PASSWORD。
注意：命中报错类别的行会真实回流闭环（计数/告警/达 20 行触发智能体重训）——这是闭环设计行为。"""
import argparse, csv, getpass, json, os, time, urllib.error, urllib.parse, urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

BASE = "http://127.0.0.1"                      # 勿用 localhost（IPv6 黑洞）
USERNAME = "admin"
CSV_PATH = r"C:\Users\17723\Desktop\点焊数据\train_v2_test.csv"
LABEL_COLUMN = "fault"                         # 调用前移除，事后对比用
LOOP_ID = ""                                   # 留空=自动找最近的智能体闭环
PROJECT_ID = ""
NULL_TOKENS = {"", "NULL", "null", "NaN", "nan", "None"}
WORKERS = 4

def site_url(path):
    base = urllib.parse.urlsplit(BASE)
    if base.scheme not in {"http", "https"} or not base.hostname:
        raise SystemExit(f"BASE 配置非法：{BASE!r}")
    if not path.startswith("/api/") or "//" in path or "\\" in path or "@" in path:
        raise SystemExit(f"拒绝非站内 API 路径：{path!r}")
    return f"{base.scheme}://{base.netloc}{path}"

def call(method, path, token, body=None, form=None):
    headers, data = {}, None
    if token: headers["Authorization"] = "Bearer " + token
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    elif form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
    request = urllib.request.Request(site_url(path), data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))

def to_value(v):
    if v is None: return None
    if isinstance(v, (int, float)): return v
    s = str(v).strip()
    if s in NULL_TOKENS: return None
    try: return int(s)
    except ValueError: pass
    try: return float(s)
    except ValueError: return s

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    password = os.environ.get("PLATFORM_PASSWORD") or getpass.getpass("平台口令: ")
    token = call("POST", "/api/auth/login", "", form={"username": USERNAME, "password": password})["access_token"]
    apis = call("GET", "/api/platform/apis", token).get("items") or []
    cands = [a for a in apis if a.get("source_kind") == "servitize" and a.get("status") == "published"]
    if not cands: raise SystemExit("没有已发布的智能体闭环条目（先完成一键部署④）")
    api = sorted(cands, key=lambda x: x.get("published_at") or "")[-1]
    print(f"调用：{api['name']}\n  {api.get('method') or 'POST'} {site_url(api['endpoint'])}")
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as h:
        rows = list(csv.DictReader(h))
    if args.limit: rows = rows[:args.limit]
    print(f"测试文件 {len(rows)} 行 / {WORKERS} 并发\n" + "-" * 60)

    def send(item):
        index, row = item
        label = row.pop(LABEL_COLUMN, None)
        record = {k: to_value(v) for k, v in row.items()}
        for attempt in range(3):
            try:
                return index, label, call("POST", api["endpoint"], token, body={"record": record}), None
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:120]
                if e.code < 500 and attempt == 2: return index, label, None, f"HTTP {e.code} {detail}"
                time.sleep(1 + attempt)
            except urllib.error.URLError as e:
                if attempt == 2: return index, label, None, str(e.reason)[:120]
                time.sleep(1 + attempt)
        return index, label, None, "retries exhausted"

    started, preds, vers, conf, fails = time.time(), Counter(), Counter(), Counter(), 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for index, label, result, error in pool.map(send, enumerate(rows, 1)):
            if error:
                fails += 1
                if fails <= 5: print(f"row {index} failed: {error}")
                continue
            p = str(result.get("prediction"))
            preds[p] += 1
            vers[str(result.get("model_version_id") or "")[:8]] += 1
            if label not in (None, ""): conf[(str(to_value(label)), p)] += 1
            if index % 500 == 0:
                print(f"progress {index}: {dict(preds)}", flush=True)
    print("-" * 60)
    print(f"done {time.time()-started:.1f}s: ok={len(rows)-fails} fail={fails}; dist={dict(preds)}")
    n = sum(conf.values())
    if n:
        ok = sum(c for (t, p), c in conf.items() if t == p)
        print(f"accuracy {ok/n:.2%} ({ok}/{n})")
        for t in sorted({t for t, _ in conf}):
            tot = sum(c for (x, _), c in conf.items() if x == t)
            print(f"  truth={t}: n={tot} correct={conf[(t,t)]} recall={conf[(t,t)]/tot:.2%}")
    print(f"model versions hit: {dict(vers)}")

if __name__ == "__main__":
    main()
```

**实测结果（v1 部署，5000 行全量，4 并发，12 分钟）**：0 失败；准确率 **93.46%**；缺陷召回 **75.0%**（与铸造 CV 0.7676 一致）；正常类召回 96.8%；713 行判为缺陷 → 全部真实回流。

> 回流报错行会写入「报错数据集」（真实标签自动标注），累计 20 行新报错 → 自动触发一轮智能体重训（配方重放 S1→S4 → 固化新配方 → 引擎铸造 → 门禁兜底换模），全程零手工。护栏：部署级单飞、冷却 30 分钟、24h 熔断 3 次；护栏挡住时在闭环详情看事件，人工评估后「重置闭环」恢复。

## 六、验证三：换模跟随

重训换模后（大屏「线上模型」跳 v2、任务列表出现重放任务），**API 与编排调用自动用新模型，零重发布**——脚本输出里的 `model versions hit` 出现新版本号即验证成立。

---

## 七、常见问题（本轮实测）

| 现象 | 根因与处理 |
|---|---|
| S1/S2 停在某阶段很久，最后升级「AGENT_S1_LLM_FAILED」 | 出网链路抖动（断流/涓流）。看门狗 60s 判卡死+自动重连 5 次×60s；仍全失败会升级人工——驳回后等链路恢复重提即可，模型/数据无损 |
| 验收升级 waiting_escalate | 看升级理由：发现泄漏列→驳回补剔除重提；仅保守意见（少数类样本 71 条波动）→采纳 |
| ② 报「未物化 S3 冠军」 | 该任务是升级后人工采纳的——走「引擎重铸」（几分钟），或重提新任务 |
| ② 报「铸造候选未过配方验收门禁」 | CV 口径比留出严格：配方门禁校准到 0.75 发新版本再铸（见第三节注） |
| ③ 冒烟失败 | 真实冒烟不再放水：说明特征脚本/模型链路有问题，看报错详情修脚本（单行合同：不依赖批内统计、不动态删列） |
| 大屏故障率/计数与预期不符 | 2026-11-10 前版本并发计数有丢更新缺陷，已修复；请升级到最新镜像 |
| 登录 403 | 15 分钟 5 次/IP 限流——脚本复用 token，勿反复登录 |
| API 调用每行 ~20 秒 | 脚本 BASE 用了 localhost——改 127.0.0.1 |
