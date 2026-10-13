import { Card } from "../../components/layout/Page";
import { PageHeader } from "../../components/layout/Page";

export function MerchantPaymentsPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Payments" description="Manage transactions and collections." />
      <Card className="p-6">
        <p className="text-gray-600">Payments module is under construction.</p>
      </Card>
    </div>
  );
}

export default MerchantPaymentsPage;

