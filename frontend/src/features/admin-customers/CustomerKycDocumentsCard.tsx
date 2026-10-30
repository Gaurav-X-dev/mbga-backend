import type { CustomerDocument } from "../../api/customers.api";
import { Alert } from "../../components/feedback/Feedback";
import { Icon } from "../../components/common/Icon";
import { StatusBadge } from "../../components/common/StatusBadge";
import { Card } from "../../components/layout/Page";
import { humanize } from "../../utils/format";
import { documentNumberKey as documentKey, useDocumentNumbers } from "../customers/useDocumentNumbers";
import { DocumentNumber } from "../customers/DocumentNumber";
import { DocumentViewButton } from "../customers/DocumentViewer";

export function CustomerKycDocumentsCard({merchantId,applicationId,documents}: {
  merchantId: string; applicationId?: string | null; documents: CustomerDocument[];
}) {
  const { canReveal, shownNumbers, fullNumbers, loading, errors, toggleNumber } = useDocumentNumbers(applicationId);
  const fileCount=documents.reduce((total,document)=>total+(document.files?.length || (document.fileId ? 1 : 0)),0);
  return <Card className="customer-kyc-card" title="KYC documents"
    subtitle={documents.length ? `${documents.length} ${documents.length === 1 ? "document" : "documents"} · ${fileCount} ${fileCount === 1 ? "file" : "files"}` : undefined}
    >
    {documents.length ? <ul className="customer-kyc-documents list-plain">
      {documents.map(document=>{
        const key=documentKey(document);
        const files=document.files?.length ? document.files : document.fileId ? [{fileId:document.fileId,fileName:document.fileName,side:"FRONT"}] : [];
        return <li key={key} className="customer-kyc-document">
          <div className="customer-kyc-document__heading">
            <div className="customer-kyc-document__identity">
              <span className="doc-item__icon" aria-hidden="true"><Icon name="fileText" size={18}/></span>
              <strong>{humanize(document.type)}</strong>
            </div>
            <StatusBadge status={document.status}/>
          </div>
          <div className="customer-kyc-document__number">
            <DocumentNumber wrap value={canReveal ? fullNumbers[key] || document.numberMasked : document.numberMasked}
              shown={shownNumbers.has(key)} disabled={loading.has(key)} onToggle={()=>void toggleNumber(document)}/>
            {loading.has(key) ? <span className="text-small text-muted" role="status">Loading number…</span> : null}
            {errors[key] ? <Alert tone="error">{errors[key]}</Alert> : null}
          </div>
          <div className="customer-kyc-document__files" aria-label={`${humanize(document.type)} files`}>
            {files.length ? files.map(file=><DocumentViewButton key={file.fileId} merchantId={merchantId}
              document={{fileId:file.fileId,fileName:file.fileName,label:`${humanize(document.type)} ${humanize(file.side)}`}}
              buttonText={files.length > 1 ? humanize(file.side) : "View"}/>) : <span className="text-muted text-small">No file</span>}
          </div>
        </li>;
      })}
    </ul> : <p className="text-muted">No documents on file.</p>}
  </Card>;
}
