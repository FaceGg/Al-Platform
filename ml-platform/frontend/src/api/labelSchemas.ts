import apiClient from "./client";
import type { LabelColumnDraft } from "../components/LabelSchemaEditor";

export async function createLabelSchema(projectId: string, name: string, columns: LabelColumnDraft[]) {
  const response = await apiClient.post("/annotations/label-schemas", {
    project_id: projectId,
    name,
    columns: columns.map((column) => ({ ...column, enum_values: [] })),
  });
  return response.data as { id: string; project_id: string; name: string; version: number };
}
