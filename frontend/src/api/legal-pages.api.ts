import { apiClient } from "./client";

export type PolicySection = { heading: string; body: string };
export type PolicyContent = {
  title: string; publisherName: string; customerAppName: string; merchantAppName: string;
  riderAppName: string; contactEmail: string; contactUrl: string; effectiveDate: string;
  backgroundLocation: "UNCONFIRMED" | "FOREGROUND_ONLY" | "FOREGROUND_AND_BACKGROUND";
  sdkDisclosure: string; sections: PolicySection[];
};
export type PolicyEditor = {
  slug: string; revision: number; publishedRevision: number | null;
  draft: PolicyContent; published: PolicyContent | null; updatedAt: string | null;
  updatedBy: string | null; publishedAt: string | null; publicPath: string; publicationIssues: string[];
};
export type PolicyRevision = {
  id: string; revision: number; action: string; actorName: string; createdAt: string; content: PolicyContent;
};
const path = "/admin/legal-pages/privacy-policy";
export async function getPrivacyEditor(signal?: AbortSignal) {
  return (await apiClient.get<PolicyEditor>(path, { signal })).data;
}
export async function savePrivacyDraft(expectedRevision: number, content: PolicyContent) {
  return (await apiClient.put<PolicyEditor>(`${path}/draft`, { expectedRevision, content })).data;
}
export async function publishPrivacyPolicy(expectedRevision: number) {
  return (await apiClient.post<PolicyEditor>(`${path}/publish`, { expectedRevision })).data;
}
export async function previewPrivacyPolicy(content: PolicyContent) {
  return (await apiClient.post<string>(`${path}/preview`, content, { responseType: "text" })).data;
}
export async function getPrivacyRevisions(signal?: AbortSignal) {
  return (await apiClient.get<PolicyRevision[]>(`${path}/revisions`, { signal })).data;
}
