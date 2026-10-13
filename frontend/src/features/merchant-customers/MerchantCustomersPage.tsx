import { Card } from "../../components/layout/Page";
import { PageHeader } from "../../components/layout/Page";

export function MerchantCustomersPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Customers" description="Manage your customer base." />
      <Card className="p-6">
        <p className="text-gray-600">Customers module is under construction.</p>
      </Card>
    </div>
  );
}

export default MerchantCustomersPage;

