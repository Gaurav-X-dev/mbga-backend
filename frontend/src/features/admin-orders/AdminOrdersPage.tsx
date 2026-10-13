import { Card } from "../../components/layout/Page";
import { PageHeader } from "../../components/layout/Page";

export function AdminOrdersPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="All Orders" description="View orders across all merchants." />
      <Card className="p-6">
        <p className="text-gray-600">Central Orders module is under construction.</p>
      </Card>
    </div>
  );
}

export default AdminOrdersPage;

