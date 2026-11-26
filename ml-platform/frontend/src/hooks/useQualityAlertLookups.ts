import { useCallback, useEffect, useState } from "react";
import apiClient from "../api/client";
import { listQualityScenes, listQualityStations } from "../api/qualityDomain";
import type { QualityScene, QualityStation } from "../api/qualityDomain";
import { notificationsApi } from "../api/securityNotifications";

/** 质量预警页面共用的查找数据（F2a，技术方案 §9.8）：项目、场景、工位、责任人。 */

export interface PersonOption {
  value: string;
  label: string;
}

function shortId(id: string | null | undefined): string {
  if (!id) return "-";
  return id.length > 10 ? `${id.slice(0, 8)}…` : id;
}

export function useQualityAlertLookups() {
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [scenes, setScenes] = useState<QualityScene[]>([]);
  const [stations, setStations] = useState<QualityStation[]>([]);
  const [people, setPeople] = useState<PersonOption[]>([]);

  useEffect(() => {
    apiClient.get("/projects").then((res) => {
      const items = (res.data?.items || []).map((p: { id: string; name: string }) => ({ id: p.id, name: p.name }));
      setProjects(items);
      setProjectId((current) => current ?? items[0]?.id ?? null);
    }).catch(() => setProjects([]));
  }, []);

  useEffect(() => {
    if (!projectId) { setScenes([]); setStations([]); setPeople([]); return; }
    listQualityScenes(projectId).then(setScenes).catch(() => setScenes([]));
    listQualityStations(projectId).then(setStations).catch(() => setStations([]));
    // 责任人候选 = 项目成员 ∪ 通知收件人（后者含项目负责人）；成员表里没有负责人
    Promise.all([
      notificationsApi.listProjectMembers(projectId),
      notificationsApi.listProjectNotificationRecipients(projectId),
    ]).then(([members, recipients]) => {
      const merged = new Map<string, string>();
      for (const person of [...members.items, ...recipients]) {
        if (person.user_id) merged.set(person.user_id, person.username);
      }
      setPeople(Array.from(merged, ([value, label]) => ({ value, label })));
    }).catch(() => setPeople([]));
  }, [projectId]);

  const sceneName = useCallback(
    (id: string | null) => {
      const scene = id ? scenes.find((item) => item.id === id) : undefined;
      return scene ? `${scene.name}（${scene.code}）` : "-";
    },
    [scenes],
  );
  const stationName = useCallback(
    (id: string | null) => {
      const station = id ? stations.find((item) => item.id === id) : undefined;
      return station ? `${station.name}（${station.code}）` : "-";
    },
    [stations],
  );
  const userName = useCallback(
    (id: string | null) => (id ? people.find((item) => item.value === id)?.label ?? shortId(id) : "-"),
    [people],
  );

  return {
    projects, projectId, setProjectId, scenes, stations, people,
    sceneName, stationName, userName,
  };
}
