import { Card } from "../../components/layout/Page";
import { PageHeader } from "../../components/layout/Page";

export function MerchantInventoryPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Inventory" description="Track stock and supplies." />
      <Card className="p-6">
        <p className="text-gray-600">Inventory module is under construction.</p>
      </Card>
    </div>
  );
}

export default MerchantInventoryPage;

