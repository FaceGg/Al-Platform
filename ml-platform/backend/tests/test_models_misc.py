"""ORM relationship tests for previously under-tested models.

Covers agent.py, compute.py, knowledge.py, and platform_models.py,
following the pattern of test_app.TestModels but for these modules.
"""
import sys
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, ".")

from app.database import Base
from app.database_migrations import ensure_schema_compatibility
from app.models.agent import Agent, AgentMessage, AgentTask
from app.models.compute import ComputeNode, EdgeDevice
from app.models.knowledge import (
    ChatMessage,
    ChatSession,
    Chunk,
    Document,
    GraphEntity,
    GraphRelation,
    KnowledgeBase,
)
from app.models.platform_models import (
    AnnotationResult,
    AnnotationTask,
    Dataset,
    OrchestrationApp,
    OrchestrationVersion,
)
from app.models.project import Project
from app.models.user import User


class TestMiscModels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        ensure_schema_compatibility(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.session = self.Session()

    def tearDown(self):
        self.session.close()

    def test_agent_and_agent_task_relationships(self):
        user = User(username="agent-user", password_hash="hash")
        self.session.add(user)
        self.session.flush()
        agent = Agent(name="Bot", created_by=user.id)
        self.session.add(agent)
        self.session.flush()
        task = AgentTask(name="Do thing", assigned_agent_id=agent.id)
        self.session.add(task)
        self.session.flush()
        message = AgentMessage(
            task_id=task.id,
            from_agent_id=agent.id,
            message_type="info",
            content="hello",
        )
        self.session.add(message)
        self.session.commit()

        self.assertEqual(agent.created_by_user, user)
        self.assertIn(agent, user.agents)
        self.assertIn(task, agent.tasks)
        self.assertEqual(task.assigned_agent, agent)
        self.assertIn(message, task.messages)
        self.assertEqual(message.from_agent, agent)

    def test_agent_task_self_reference(self):
        user = User(username="agent-parent", password_hash="hash")
        self.session.add(user)
        self.session.flush()
        parent_task = AgentTask(name="Parent")
        self.session.add(parent_task)
        self.session.flush()
        child_task = AgentTask(name="Child", parent_task_id=parent_task.id)
        self.session.add(child_task)
        self.session.commit()
        # Verify self-referential FK is persisted
        self.assertEqual(child_task.parent_task_id, parent_task.id)
        # With remote_side="AgentTask.id", the "children" relationship resolves
        # many-to-one (returns the parent), and the "parent" backref is
        # one-to-many (returns the children collection).
        self.assertEqual(child_task.children, parent_task)
        self.assertIsNone(parent_task.children)
        self.assertIn(child_task, parent_task.parent)

    def test_agent_task_project_and_creator_relationships(self):
        user = User(username="agent-task-owner", password_hash="hash")
        self.session.add(user)
        self.session.flush()
        project = Project(name="Agent task project", owner_id=user.id)
        self.session.add(project)
        self.session.flush()
        task = AgentTask(
            name="Owned task",
            project_id=project.id,
            created_by_id=user.id,
        )
        self.session.add(task)
        self.session.commit()

        self.assertEqual(task.project, project)
        self.assertEqual(task.created_by_user, user)

    def test_compute_node_and_edge_device_defaults(self):
        user = User(username="compute-user", password_hash="hash")
        self.session.add(user)
        self.session.flush()
        node = ComputeNode(name="gpu-1", owner_id=user.id)
        edge = EdgeDevice(name="edge-1", owner_id=user.id)
        self.session.add_all([node, edge])
        self.session.commit()
        self.assertEqual(node.node_type, "gpu")
        self.assertEqual(node.status, "online")
        self.assertEqual(edge.device_type, "box")
        self.assertEqual(edge.status, "online")

    def test_knowledge_base_document_chunk_relationships(self):
        user = User(username="kb-user", password_hash="hash")
        self.session.add(user)
        self.session.flush()
        kb = KnowledgeBase(name="KB1", owner_id=user.id)
        self.session.add(kb)
        self.session.flush()
        doc = Document(kb_id=kb.id, filename="a.txt", content="text")
        self.session.add(doc)
        self.session.flush()
        chunk = Chunk(doc_id=doc.id, content="chunk-text", chunk_index=0)
        self.session.add(chunk)
        self.session.commit()

        self.assertEqual(kb.owner, user)
        self.assertIn(kb, user.knowledge_bases)
        self.assertIn(doc, kb.documents)
        self.assertEqual(doc.knowledge_base, kb)
        self.assertIn(chunk, doc.chunks)
        self.assertEqual(chunk.document, doc)

    def test_graph_entity_and_relation_relationships(self):
        user = User(username="graph-user", password_hash="hash")
        self.session.add(user)
        self.session.flush()
        kb = KnowledgeBase(name="GraphKB", owner_id=user.id)
        self.session.add(kb)
        self.session.flush()
        source = GraphEntity(kb_id=kb.id, name="Welding", entity_type="process")
        target = GraphEntity(kb_id=kb.id, name="Defect", entity_type="outcome")
        self.session.add_all([source, target])
        self.session.flush()
        relation = GraphRelation(
            kb_id=kb.id,
            source_id=source.id,
            target_id=target.id,
            relation_type="causes",
        )
        self.session.add(relation)
        self.session.commit()

        self.assertIn(source, kb.entities)
        self.assertIn(relation, source.source_relations)
        self.assertEqual(relation.source, source)
        self.assertEqual(relation.target, target)
        self.assertIn(relation, target.target_relations)

    def test_chat_session_and_message_relationships(self):
        user = User(username="chat-user", password_hash="hash")
        self.session.add(user)
        self.session.flush()
        kb = KnowledgeBase(name="ChatKB", owner_id=user.id)
        self.session.add(kb)
        self.session.flush()
        session = ChatSession(kb_id=kb.id, user_id=user.id, title="S1")
        self.session.add(session)
        self.session.flush()
        msg = ChatMessage(session_id=session.id, role="user", content="hi")
        self.session.add(msg)
        self.session.commit()
        self.assertIn(msg, session.messages)
        self.assertEqual(msg.session, session)

    def test_dataset_annotation_task_result_relationships(self):
        user = User(username="annot-model-user", password_hash="hash")
        self.session.add(user)
        self.session.flush()
        dataset = Dataset(name="DS", owner_id=user.id)
        self.session.add(dataset)
        self.session.flush()
        task = AnnotationTask(name="Task", dataset_id=dataset.id, owner_id=user.id)
        self.session.add(task)
        self.session.flush()
        result = AnnotationResult(task_id=task.id, sample_index=0, sample_path="/x.png")
        self.session.add(result)
        self.session.commit()

        self.assertEqual(dataset.owner, user)
        self.assertIn(dataset, user.datasets)
        self.assertIn(task, dataset.annotation_tasks)
        self.assertEqual(task.dataset, dataset)
        self.assertIn(result, task.results)

    def test_orchestration_app_and_version_relationships(self):
        user = User(username="orch-user", password_hash="hash")
        self.session.add(user)
        self.session.flush()
        app = OrchestrationApp(name="App", owner_id=user.id)
        self.session.add(app)
        self.session.flush()
        version = OrchestrationVersion(
            app_id=app.id,
            version="v1",
            created_by=user.id,
        )
        self.session.add(version)
        self.session.commit()

        self.assertEqual(app.owner, user)
        self.assertIn(app, user.orchestration_apps)
        self.assertIn(version, app.versions)
        self.assertEqual(version.app, app)
        self.assertEqual(version.creator, user)


if __name__ == "__main__":
    unittest.main()
