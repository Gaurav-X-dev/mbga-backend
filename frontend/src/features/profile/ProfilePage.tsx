import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../../auth/auth-context";
import { Button } from "../../components/common/Button";
import { Badge, StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { ConfirmationDialog } from "../../components/feedback/Dialogs";
import { useToast } from "../../components/feedback/toast-context";
import { Card, DetailsPanel, PageHeader } from "../../components/layout/Page";
import { PANEL_LABEL } from "../../config/navigation";
import { formatMobileNumber } from "../../utils/mobile";
import { roleLabel } from "../../utils/labels";
import { pluralize } from "../../utils/format";

export function ProfilePage() {
  const auth = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [confirmEverywhere, setConfirmEverywhere] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const user = auth.user;
  const channel = auth.channel ?? "admin";
  const home = channel === "admin" ? "/admin/dashboard" : "/merchant/dashboard";

  return (
    <div className="page">
      <PageHeader
        title="My account"
        description="Your sign-in details and access."
        breadcrumbs={[{ label: "Dashboard", to: home }, { label: "My account" }]}
      />
      <div className="grid-sidebar">
        <div className="stack-lg">
          <Card title="Profile">
            <div className="row" style={{ marginBottom: "var(--space-5)" }}>
              <UserAvatar name={user?.display_name} size="lg" />
              <div>
                <p className="section-title">{user?.display_name ?? "—"}</p>
                <p className="meta">{PANEL_LABEL[channel]}</p>
              </div>
            </div>
            <DetailsPanel
              items={[
                { label: "Name", value: user?.display_name },
                { label: "Mobile number", value: formatMobileNumber(user?.mobile_number) },
                { label: "Account status", value: <StatusBadge status={user?.status} /> },
                { label: "Signed in to", value: PANEL_LABEL[channel] }
              ]}
            />
            <p className="meta" style={{ marginTop: "var(--space-4)" }}>
              To change your name or mobile number, contact your administrator.
            </p>
          </Card>
          <Card title="Your roles">
            {user && user.active_roles.length > 0 ? (
              <div className="stack">
                <div className="chip-list">
                  {user.active_roles.map((role) => (
                    <Badge key={role} tone="info">
                      {roleLabel(role)}
                    </Badge>
                  ))}
                </div>
                <p className="meta">
                  Your roles give you {pluralize(user.effective_permissions.length, "permission")} in this panel.
                </p>
              </div>
            ) : (
              <p className="text-muted">No active roles.</p>
            )}
          </Card>
        </div>
        <Card title="Sign-in and security">
          <div className="stack">
            <p className="text-small text-muted">
              You sign in with a one-time verification code sent to your mobile number. Never share this code with anyone,
              including MBGA staff.
            </p>
            <Button
              variant="secondary"
              icon="logout"
              block
              loading={signingOut}
              loadingText="Signing out…"
              onClick={async () => {
                setSigningOut(true);
                await auth.signOut();
                navigate("/login", { replace: true });
              }}
            >
              Sign out
            </Button>
            <Button variant="danger" icon="devices" block onClick={() => setConfirmEverywhere(true)}>
              Sign out from all devices
            </Button>
            <p className="meta">Use this if you signed in on a shared or lost device.</p>
          </div>
        </Card>
      </div>
      <ConfirmationDialog
        open={confirmEverywhere}
        title="Sign out from all devices?"
        description="You will be signed out here and on every other device where you are signed in to MBGA."
        confirmLabel="Sign out everywhere"
        onClose={() => setConfirmEverywhere(false)}
        onConfirm={async () => {
          await auth.signOutEverywhere();
          toast.success("You have been signed out from all devices.");
          navigate("/login", { replace: true });
        }}
      />
    </div>
  );
}
