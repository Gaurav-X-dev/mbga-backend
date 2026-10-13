import { Card } from "../../components/layout/Page";
import { PageHeader } from "../../components/layout/Page";

export function MerchantOrdersPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Orders" description="Manage incoming and outgoing orders." />
      <Card className="p-6">
        <p className="text-gray-600">Orders module is under construction.</p>
      </Card>
    </div>
  );
}

export default MerchantOrdersPage;

