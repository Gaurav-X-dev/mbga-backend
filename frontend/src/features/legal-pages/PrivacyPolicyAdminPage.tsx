import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getPrivacyEditor, getPrivacyRevisions, previewPrivacyPolicy, publishPrivacyPolicy, savePrivacyDraft, type PolicyContent, type PolicyEditor } from "../../api/legal-pages.api";
import { normalizeError } from "../../api/errors";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { Alert, InlineError, LoadingSkeleton } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, Select, Textarea } from "../../components/forms/Field";
import { Card, PageHeader } from "../../components/layout/Page";

const KEY = ["admin", "privacy-policy"] as const;

export function PrivacyPolicyAdminPage() {
  const auth = useAuth();
  const toast = useToast();
  const client = useQueryClient();
  const canManage = auth.can(PERMISSIONS.platformSettingsManage);
  const query = useQuery({ queryKey: KEY, queryFn: ({ signal }) => getPrivacyEditor(signal), staleTime: 60_000 });
  const [editor, setEditor] = useState<PolicyEditor | null>(null);
  const [form, setForm] = useState<PolicyContent | null>(null);
  const [previewHtml, setPreviewHtml] = useState("");
  useEffect(() => {
    if (query.data && !editor) { setEditor(query.data); setForm(query.data.draft); }
  }, [query.data, editor]);
  const history = useQuery({ queryKey: [...KEY, "revisions", editor?.revision], queryFn: ({ signal }) => getPrivacyRevisions(signal), enabled: Boolean(editor?.revision) });
  const dirty = Boolean(form && editor && JSON.stringify(form) !== JSON.stringify(editor.draft));
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  function accept(saved: PolicyEditor) {
    setEditor(saved); setForm(saved.draft); setPreviewHtml(""); client.setQueryData(KEY, saved);
    void client.invalidateQueries({ queryKey: [...KEY, "revisions"] });
  }
  const save = useMutation({ mutationFn: () => savePrivacyDraft(editor!.revision, form!), onSuccess: (saved) => { accept(saved); toast.success("Privacy policy draft saved. The public page is unchanged."); } });
  const publish = useMutation({ mutationFn: () => publishPrivacyPolicy(editor!.revision), onSuccess: (saved) => { accept(saved); toast.success("Privacy policy published for all three apps."); } });
  const preview = useMutation({ mutationFn: () => previewPrivacyPolicy(form!), onSuccess: setPreviewHtml });
  const busy = save.isPending || publish.isPending || preview.isPending;
  const error = save.error || publish.error || preview.error;
  const canPublish = canManage && !dirty && Boolean(editor?.revision) && !editor?.publicationIssues.length;
  const set = (key: keyof Omit<PolicyContent, "sections">, value: string) => {
    setForm((current) => current ? { ...current, [key]: value } : current); setPreviewHtml("");
  };
  const section = (index: number, key: "heading" | "body", value: string) => {
    setForm((current) => current ? { ...current, sections: current.sections.map((s, i) => i === index ? { ...s, [key]: value } : s) } : current);
    setPreviewHtml("");
  };
  async function reload() {
    const result = await query.refetch();
    if (result.data) accept(result.data);
    save.reset(); publish.reset(); preview.reset();
  }
  if (query.isLoading || (!form && !query.error)) return <LoadingSkeleton />;
  if (!form || !editor) return <InlineError error={query.error} onRetry={() => void query.refetch()} />;
  const publicUrl = new URL(editor.publicPath, window.location.origin).href;
  return (
    <div className="page stack">
      <PageHeader title="Privacy policy" documentTitle="Privacy policy" description="One shared policy for the Customer, Merchant and Rider apps. Save a draft, preview it, then publish." />
      <Card title="Public policy" subtitle={editor.publishedAt ? `Published version ${editor.publishedRevision} · ${new Date(editor.publishedAt).toLocaleString("en-IN")}` : "No version has been published yet."}>
        <div className="stack">
          <a href={editor.publicPath} target="_blank" rel="noreferrer">{publicUrl}</a>
          <p className="meta">Use this same URL in all three Play Console listings and inside each app. The public page requires no login.</p>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <Button variant="secondary" onClick={() => { void navigator.clipboard.writeText(publicUrl).then(() => toast.success("Policy URL copied.")).catch(() => toast.error("Copy the URL shown above.")); }}>Copy URL</Button>
            <Button variant="secondary" onClick={() => preview.mutate()} loading={preview.isPending} disabled={busy}>Preview draft</Button>
            {canManage ? <>
              <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!dirty || busy}>Save draft</Button>
              <Button onClick={() => publish.mutate()} loading={publish.isPending} disabled={!canPublish || busy}>Publish policy</Button>
            </> : null}
          </div>
          <p className="meta">Draft revision {editor.revision}{editor.updatedBy ? ` · Last updated by ${editor.updatedBy}` : ""}{dirty ? " · Unsaved changes" : ""}</p>
          {editor.publicationIssues.length > 0 ? <Alert tone="warning" title="Details needed before publication"><ul>{editor.publicationIssues.map((issue) => <li key={issue}>{issue}</li>)}</ul></Alert> : null}
          {dirty ? <p className="meta">Save your changes before publishing. Publication checks update after saving.</p> : null}
          {error ? <Alert tone="error" title="Policy could not be updated"><p>{normalizeError(error).userMessage}</p><Button variant="secondary" onClick={() => void reload()}>Discard local changes and reload latest</Button></Alert> : null}
          {query.error ? <InlineError error={query.error} onRetry={() => void query.refetch()} /> : null}
        </div>
      </Card>
      <fieldset disabled={!canManage || busy} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
        <div className="stack">
          <Card title="Publisher and apps" subtitle="Use the publisher and app names shown in your Play Store listings.">
            <div className="form-grid">
              <Field label="Policy title" required><Input value={form.title} maxLength={180} onChange={(e) => set("title", e.target.value)} /></Field>
              <Field label="Publisher / business name" required><Input value={form.publisherName} maxLength={200} onChange={(e) => set("publisherName", e.target.value)} /></Field>
              <Field label="Customer app name" required><Input value={form.customerAppName} maxLength={150} onChange={(e) => set("customerAppName", e.target.value)} /></Field>
              <Field label="Merchant app name" required><Input value={form.merchantAppName} maxLength={150} onChange={(e) => set("merchantAppName", e.target.value)} /></Field>
              <Field label="Rider app name" required><Input value={form.riderAppName} maxLength={150} onChange={(e) => set("riderAppName", e.target.value)} /></Field>
              <Field label="Effective date" required><Input type="date" value={form.effectiveDate} onChange={(e) => set("effectiveDate", e.target.value)} /></Field>
              <Field label="Privacy contact email" hint="Provide a monitored email or contact page for privacy and deletion requests."><Input type="email" value={form.contactEmail} maxLength={254} onChange={(e) => set("contactEmail", e.target.value)} /></Field>
              <Field label="Privacy contact page"><Input type="url" value={form.contactUrl} maxLength={500} onChange={(e) => set("contactUrl", e.target.value)} /></Field>
            </div>
          </Card>
          <Card title="Location and service providers" subtitle="Match these statements to the actual mobile builds before publication.">
            <div className="stack">
              <Field label="Rider location collection" required><Select value={form.backgroundLocation} onChange={(e) => set("backgroundLocation", e.target.value)} options={[
                { value: "UNCONFIRMED", label: "Not yet confirmed" },
                { value: "FOREGROUND_ONLY", label: "Only while the app is in use" },
                { value: "FOREGROUND_AND_BACKGROUND", label: "Foreground and background during delivery work" }
              ]} /></Field>
              <Field label="Service providers and SDK disclosure" required hint="Include messaging/OTP, hosting, Firebase notifications, and any analytics, crash reporting or advertising SDKs actually used."><Textarea rows={5} value={form.sdkDisclosure} maxLength={6000} onChange={(e) => set("sdkDisclosure", e.target.value)} /></Field>
            </div>
          </Card>
          <Card title="Policy content" subtitle="Edit headings and plain text. HTML and scripts are displayed as text, never executed.">
            <div className="stack">
              {form.sections.map((s, index) => <div key={index} className="stack" style={{ paddingBottom: 20, borderBottom: "1px solid var(--border, #e1e7f0)" }}>
                <Field label={`Section ${index + 1} heading`} required><Input value={s.heading} maxLength={180} onChange={(e) => section(index, "heading", e.target.value)} /></Field>
                <Field label={`Section ${index + 1} content`} required><Textarea rows={6} value={s.body} maxLength={10000} onChange={(e) => section(index, "body", e.target.value)} /></Field>
                <Button variant="ghost" size="sm" disabled={form.sections.length <= 1} onClick={() => { setForm({ ...form, sections: form.sections.filter((_, i) => i !== index) }); setPreviewHtml(""); }}>Remove section {index + 1}</Button>
              </div>)}
              <Button variant="secondary" disabled={form.sections.length >= 40} onClick={() => { setForm({ ...form, sections: [...form.sections, { heading: "New section", body: "Write the policy details for this section." }] }); setPreviewHtml(""); }}>Add section</Button>
            </div>
          </Card>
        </div>
      </fieldset>
      {previewHtml ? <Card title="Draft preview"><iframe title="Privacy policy draft preview" sandbox="" srcDoc={previewHtml} style={{ width: "100%", minHeight: 800, border: "1px solid #e1e7f0", borderRadius: 12 }} /></Card> : null}
      <Card title="Version history" subtitle="Saved drafts and publications are recorded separately.">
        {history.error ? <InlineError error={history.error} onRetry={() => void history.refetch()} /> : <ul>{history.data?.map((revision) => <li key={revision.id}>Revision {revision.revision} · {revision.action === "PUBLISHED" ? "Published" : "Draft saved"} · {revision.actorName} · {new Date(revision.createdAt).toLocaleString("en-IN")}</li>)}</ul>}
        {!editor.revision ? <p className="meta">Save the first draft to start the version history.</p> : null}
      </Card>
    </div>
  );
}
