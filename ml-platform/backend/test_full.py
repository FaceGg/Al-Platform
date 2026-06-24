import sys
sys.path.insert(0, "backend")
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine

c = TestClient(app)
Base.metadata.create_all(bind=engine)
passed = 0
failed = 0

def ok(name, r, exp=200):
    global passed, failed
    s = r.status_code
    if exp and s != exp:
        failed += 1
        print(f"  FAIL [{name}] expected {exp} got {s}: {r.text[:150]}")
        return None
    passed += 1
    print(f"  OK   [{name}] {s}")
    try:
        return r.json()
    except:
        return r.text

# Login
lr = ok("login", c.post("/api/auth/login", data={"username": "admin", "password": "admin123"}))
token = lr["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Health
ok("health", c.get("/api/health"))

# Projects
pr = ok("create project", c.post("/api/projects", json={"name": "ITest", "description": "Integration test"}, headers=h), 201)
pid = pr["id"] if pr else None
ok("list projects", c.get("/api/projects", headers=h))
if pid:
    ok("get project", c.get(f"/api/projects/{pid}", headers=h))
    ok("update project", c.put(f"/api/projects/{pid}", json={"name": "Updated"}, headers=h))

# Templates
ok("list templates", c.get("/api/templates", headers=h))
ok("get template", c.get("/api/templates/weld_quality", headers=h))
if pid:
    ok("instantiate", c.post(f"/api/templates/weld_quality/instantiate?project_id={pid}", headers=h))

# Operators
op = ok("list operators", c.get("/api/operators", headers=h))
if op and "operators" in op:
    print(f"  Operator count: {len(op['operators'])}")

# Knowledge Base
kb = ok("create kb", c.post("/api/knowledge/bases", json={"name": "TestKB", "description": "T"}, headers=h))
kbid = kb["id"] if kb else None
ok("list kb", c.get("/api/knowledge/bases", headers=h))
if kbid:
    ok("get kb", c.get(f"/api/knowledge/bases/{kbid}", headers=h))
    d = ok("upload doc", c.post(
        f"/api/knowledge/bases/{kbid}/documents",
        data={"title": "TestDoc"},
        files={"file": ("t.txt", b"Spot welding quality depends on current and pressure.")},
        headers=h
    ))
    if d and "id" in d:
        ok("vectorize", c.post(f"/api/knowledge/bases/{kbid}/vectorize", headers=h))
        ok("search", c.post(f"/api/knowledge/bases/{kbid}/search", json={"query": "welding"}, headers=h))
        ok("rag", c.post(f"/api/knowledge/bases/{kbid}/rag", json={"query": "What is welding?"}, headers=h))
        ok("hybrid", c.post(f"/api/knowledge/bases/{kbid}/search/hybrid", json={"query": "welding", "top_k": 2}, headers=h))
    ok("list entities", c.get(f"/api/knowledge/bases/{kbid}/graph/entities", headers=h))
    ok("add entity", c.post(f"/api/knowledge/bases/{kbid}/graph/entities", json={"name": "Weld", "entity_type": "process"}, headers=h))
    ok("get graph", c.get(f"/api/knowledge/bases/{kbid}/graph", headers=h))
    ok("chat", c.post(f"/api/knowledge/bases/{kbid}/chats", json={"message": "hello"}, headers=h))
    ok("list chats", c.get(f"/api/knowledge/bases/{kbid}/chats", headers=h))

# Monitor
ok("monitor current", c.get("/api/monitor/current", headers=h))
ok("monitor history", c.get("/api/monitor/history", headers=h))

# Training
ok("training jobs", c.get("/api/training/jobs", headers=h))
ok("automl jobs", c.get("/api/training/automl/jobs", headers=h))
ok("checkpoints", c.get("/api/training/checkpoints?training_job_id=none", headers=h))
ok("model versions", c.get("/api/training/models/versions?project_id=00000000-0000-0000-0000-000000000000", headers=h))

# Labeling
ok("labeling rules", c.post("/api/labeling/rules", json={"data": [[1,2],[3,4]], "columns": ["a","b"], "rules": [{"condition": ">0", "label": "good"}]}, headers=h))

# Orchestration
ok("create agent", c.post("/api/orchestration/agents", json={"name": "Agent1", "agent_type": "executor"}, headers=h))
ok("list agents", c.get("/api/orchestration/agents", headers=h))
tk = ok("create task", c.post("/api/orchestration/tasks", json={"name": "Task1", "input_data": {}}, headers=h))
if tk and "id" in tk:
    tid = tk["id"]
    ok("get task", c.get(f"/api/orchestration/tasks/{tid}", headers=h))
    ok("send msg", c.post("/api/orchestration/messages", json={"task_id": tid, "message_type": "info", "content": "hello"}, headers=h))
ok("list tasks", c.get("/api/orchestration/tasks", headers=h))
ok("reviews", c.get("/api/orchestration/reviews", headers=h))
ok("plan", c.post("/api/orchestration/plan", json={"task_description": "Predict welding quality"}, headers=h))

# Models
if pid:
    ok("list models", c.get(f"/api/projects/{pid}/models", headers=h))

# Users
ok("list users", c.get("/api/admin/users", headers=h))

# Cleanup
if kbid:
    ok("delete kb", c.delete(f"/api/knowledge/bases/{kbid}", headers=h))
if pid:
    ok("delete project", c.delete(f"/api/projects/{pid}", headers=h), 204)

print(f"\n{'='*50}")
print(f"Passed: {passed}, Failed: {failed}")




