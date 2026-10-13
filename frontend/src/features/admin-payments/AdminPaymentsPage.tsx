import { Card } from "../../components/layout/Page";
import { PageHeader } from "../../components/layout/Page";

export function AdminPaymentsPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="All Payments" description="View payments across all merchants." />
      <Card className="p-6">
        <p className="text-gray-600">Central Payments module is under construction.</p>
      </Card>
    </div>
  );
}

export default AdminPaymentsPage;

