import { Card } from "../../components/layout/Page";
import { PageHeader } from "../../components/layout/Page";

export function AdminInventoryPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="All Inventory" description="View inventory across all merchants." />
      <Card className="p-6">
        <p className="text-gray-600">Central Inventory module is under construction.</p>
      </Card>
    </div>
  );
}

export default AdminInventoryPage;

