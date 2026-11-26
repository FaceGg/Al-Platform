GENERICIZATION_BRIDGE_ONLY = True

from app.models.user import User
from app.models.project import Project
from app.models.workflow import Workflow, WorkflowNode, WorkflowEdge
from app.models.run import WorkflowRun, NodeRun
from app.models.workflow_version import WorkflowVersion
from app.models.artifact import Artifact
from app.models.operation import DurableOperation
from app.models.knowledge import (
    KnowledgeBase,
    Document,
    Chunk,
    GraphEntity,
    GraphRelation,
    KgExtractionJob,
    KgUnitResult,
    KgMergeSuggestion,
)
from app.models.training import TrainingJob
from app.models.experiment import Experiment, ExperimentAutoMLBinding
from app.models.schedule import PipelineSchedule, PipelineScheduleRun
from app.models.access import ProjectMember, AuditEvent
from app.models.platform_audit import PlatformAuditEvent
from app.models.notifications import (
    InAppNotification,
    NotificationDelivery,
    NotificationEndpoint,
    NotificationOutbox,
    NotificationSubscription,
)
from app.models.agent import Agent, AgentTask, AgentMessage
from app.models.algorithm import Algorithm
from app.models.model_library import ModelLibrary
from app.models.model_registry import (
    RegisteredModel,
    ModelVersion,
    InferenceDeployment,
    DeploymentRevision,
    DeploymentTarget,
    DeploymentRollout,
    InferenceApiKey,
    InferenceRequestLog,
    InferenceMetricBucket,
    ModelCard,
)
from app.models.model_export import ModelExport
from app.models.llm_profile import LLMProfile
from app.models.announcement import Announcement
from app.models.agent_run import AgentRun
from app.models.recipe import PipelineRecipe, PipelineRecipeVersion
from app.models.experience_entry import ExperienceEntry
from app.models.skill_revision import SkillRevision
from app.models.prompt_template import PromptTemplate
from app.models.kb_binding import KBBinding
from app.models.api_model import PlatformAPI
from app.models.compute import ComputeNode, EdgeDevice
from app.models.platform_models import (
    Dataset,
    AnnotationTask,
    GenericAnnotationTask,
    AnnotationTaskPreview,
    AnnotationTaskRevisionSnapshot,
    AnnotationTaskScopeSample,
    AnnotationTaskPreviewSample,
    AnnotationTaskExecutionResult,
    AnnotationTaskExecutionStatistic,
    AnnotationResult,
    OrchestrationApp,
    OrchestrationVersion,
)
from app.models.data_version import DatasetVersion, DatasetSchemaColumn, DatasetSample, DatasetImport, DatasetImportProcess
from app.models.demo_loop import DemoLoopConfig, DemoLoopEvent
from app.models.developer_resources import (
    ContainerImage,
    GpuResourceClass,
    ImageBuild,
    NotebookSession,
)
from app.models.kubernetes_execution import KubernetesJobRun
from app.models.resource_governance import (
    ClusterRoutingPolicy,
    ResourceQuotaPolicy,
    ResourceReservation,
    ResourceUsageSnapshot,
    StorageBinding,
)
from app.models.cloud_resources import (
    KubernetesCluster,
    KubernetesCredentialRef,
    KubernetesNamespace,
    KubernetesResourceGroup,
)
from app.models.annotator import AnnotatorAccount, AnnotatorSession, AnnotatorSubjectMapping, ProjectAnnotatorGrant
from app.models.labeling import (LabelSchema, LabelColumn, LabelValueConstraint, AnnotationTaskLabel, AnnotationSampleCurrent, AnnotationRevision, AnnotationComment, AnnotationConfirmation, AnnotationStrategyArtifact, AnnotationStrategyDecision, AnnotationAssignment, AnnotationAssignmentSample, AnnotationReturnBatch, AnnotationReturnBatchSample)
from app.models.spot_weld_quality import (
    SpotWeldQualityRun,
    SpotWeldQualitySample,
    SpotWeldQualityRuleSet,
    SpotWeldLabelRevision,
    SpotWeldLabelSnapshot,
)
from app.models.platform_option import PlatformOption
from app.models.quality_domain import QualityScene, QualityStation, QualitySpecLimit
from app.models.inference_result import InferenceResult, InferenceResultBucket
from app.models.external_data_source import ExternalDataSource
from app.models.quality_alerts import (
    QualityAlert,
    QualityAlertEvent,
    QualitySop,
    QualitySpcBaseline,
    ModelEvidenceCheck,
)
from app.models.drift import (
    DriftBaseline,
    DriftReport,
    DriftReportFeature,
    InferenceFeatureHistogram,
)
from app.models.ingest import IngestEvent
from app.models.approvals import ApprovalRequest
from app.models.agent_audit import AgentActionAudit, AuditChainState
from app.models.dataset_splitting import (
    BlindTestUsage,
    DatasetSplit,
    DatasetSplitMember,
    ModelingRound,
)
from app.models.release_governance import (
    ReleaseCheck,
    ReleasePreauthorization,
    RolloutReceipt,
    ShadowComparison,
)
from app.models.label_quality import (
    ActiveLearningSelection,
    AnnotationBlindLabel,
    ConsistencyRound,
    LabelArbitration,
    PseudoLabelBatch,
)
from app.models.audit_qa import AuditReport, ModelTrustScore

__all__ = [
    "User",
    "Project",
    "Workflow",
    "WorkflowNode",
    "WorkflowEdge",
    "WorkflowRun",
    "NodeRun",
    "WorkflowVersion",
    "Artifact",
    "DurableOperation",
    "KnowledgeBase",
    "Document",
    "Chunk",
    "GraphEntity",
    "GraphRelation",
    "KgExtractionJob",
    "KgUnitResult",
    "KgMergeSuggestion",
    "TrainingJob",
    "Experiment",
    "ExperimentAutoMLBinding",
    "PipelineSchedule",
    "PipelineScheduleRun",
    "ProjectMember",
    "AuditEvent",
    "PlatformAuditEvent",
    "NotificationEndpoint",
    "NotificationSubscription",
    "NotificationOutbox",
    "NotificationDelivery",
    "InAppNotification",
    "Agent",
    "AgentTask",
    "AgentMessage",
    "Algorithm",
    "ModelLibrary",
    "RegisteredModel",
    "ModelVersion",
    "InferenceDeployment",
    "DeploymentRevision",
    "DeploymentTarget",
    "DeploymentRollout",
    "InferenceApiKey",
    "InferenceRequestLog",
    "InferenceMetricBucket",
    "ModelCard",
    "ModelExport",
    "LLMProfile",
    "AgentRun",
    "PipelineRecipe",
    "PipelineRecipeVersion",
    "ExperienceEntry",
    "SkillRevision",
    "PromptTemplate",
    "KBBinding",
    "PlatformAPI",
    "ComputeNode",
    "EdgeDevice",
    "Dataset",
    "AnnotationTask",
    "GenericAnnotationTask",
    "AnnotationTaskPreview",
    "AnnotationTaskRevisionSnapshot",
    "AnnotationTaskScopeSample",
    "AnnotationTaskPreviewSample",
    "AnnotationTaskExecutionResult",
    "AnnotationTaskExecutionStatistic",
    "AnnotationResult",
    "OrchestrationApp",
    "OrchestrationVersion",
    "DatasetVersion",
    "DatasetSchemaColumn",
    "DatasetSample",
    "DatasetImport",
    "DatasetImportProcess",
    "KubernetesCluster",
    "KubernetesCredentialRef",
    "KubernetesNamespace",
    "KubernetesResourceGroup",
    "KubernetesJobRun",
    "ContainerImage",
    "ImageBuild",
    "NotebookSession",
    "GpuResourceClass",
    "ClusterRoutingPolicy",
    "StorageBinding",
    "ResourceQuotaPolicy",
    "ResourceReservation",
    "ResourceUsageSnapshot",
    "AnnotatorAccount",
    "AnnotatorSession",
    "AnnotatorSubjectMapping",
    "ProjectAnnotatorGrant",
    "LabelSchema",
    "LabelColumn",
    "LabelValueConstraint",
    "AnnotationTaskLabel",
    "AnnotationSampleCurrent",
    "AnnotationRevision",
    "AnnotationComment",
    "AnnotationConfirmation",
    "AnnotationStrategyArtifact",
    "AnnotationStrategyDecision",
    "AnnotationAssignment",
    "AnnotationAssignmentSample",
    "AnnotationReturnBatch",
    "AnnotationReturnBatchSample",
    "SpotWeldQualityRun",
    "SpotWeldQualitySample",
    "SpotWeldQualityRuleSet",
    "SpotWeldLabelRevision",
    "SpotWeldLabelSnapshot",
    "PlatformOption",
    "QualityScene",
    "QualityStation",
    "QualitySpecLimit",
    "InferenceResult",
    "InferenceResultBucket",
    "ExternalDataSource",
    "QualityAlert",
    "QualityAlertEvent",
    "QualitySop",
    "QualitySpcBaseline",
    "ModelEvidenceCheck",
    "DriftBaseline",
    "DriftReport",
    "DriftReportFeature",
    "InferenceFeatureHistogram",
    "IngestEvent",
    "ApprovalRequest",
    "AgentActionAudit",
    "AuditChainState",
    "DatasetSplit",
    "DatasetSplitMember",
    "ModelingRound",
    "BlindTestUsage",
    "ShadowComparison",
    "ReleaseCheck",
    "ReleasePreauthorization",
    "RolloutReceipt",
    "ActiveLearningSelection",
    "ConsistencyRound",
    "AnnotationBlindLabel",
    "LabelArbitration",
    "PseudoLabelBatch",
    "AuditReport",
    "ModelTrustScore",
]
