import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";

import { AppError } from "../../api/errors";
import { listMerchants } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { listRoles } from "../../api/roles.api";
import { createUser, listUsers } from "../../api/users.api";
import { Button } from "../../components/common/Button";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, PhoneInput, Select } from "../../components/forms/Field";
import { applyServerErrors, fieldError, zodResolver } from "../../components/forms/form-utils";
import { mobileSchema, optionalEmailSchema, requiredText } from "../../schemas/common";
import { emptyToUndefined } from "../../utils/format";
import { normalizeMobileNumber } from "../../utils/mobile";

/** Scope comes from the selected role's configured login channels, never its name. */
const ALL_ROLES = { is_active: true, page: 1, page_size: 100 } as const;

const schema = z
  .object({
    full_name: requiredText("the full name", 2, 160),
    mobile_number: mobileSchema,
    email: optionalEmailSchema,
    role: z.string().min(1, "Choose a role."),
    merchantId: z.string(),
    staffType: z.string().max(60).optional()
  });
type Values = z.infer<typeof schema>;

const DUPLICATE_MOBILE = "A user with this mobile number already exists.";

export function AddUserDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [formMessage, setFormMessage] = useState<string | null>(null);
  const { register, handleSubmit, formState, setError, reset, watch } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { full_name: "", mobile_number: "", email: "", role: "", merchantId: "", staffType: "" }
  });
  const role = watch("role");
  const rolesQuery = useQuery({
    queryKey: [...queryKeys.roles.all, "add-user-options"],
    queryFn: async ({ signal }) => {
      const first = await listRoles(ALL_ROLES, signal);
      const items = [...first.items];
      for (let page = 2; page <= first.total_pages; page++) {
        const next = await listRoles({...ALL_ROLES,page},signal);
        items.push(...next.items);
        if (!next.items.length) break;
      }
      return {...first,items};
    },
    staleTime: 0,
    enabled: open
  });
  const selectedRole = rolesQuery.data?.items.find(item=>item.code===role);
  const requiresMerchant = Boolean(selectedRole?.requires_merchant || selectedRole?.login_channels?.includes("MERCHANT"));
  const scopeReady = Boolean(selectedRole && Array.isArray(selectedRole.login_channels) && selectedRole.login_channels.some(channel=>channel==="ADMIN" || channel==="MERCHANT"));
  const roleOptions = (rolesQuery.data?.items ?? []).filter(item=>item.login_channels?.some(channel=>channel==="ADMIN" || channel==="MERCHANT")).map(item=>({value:item.code,label:item.name}));
  const merchantParams = { limit: 100, offset: 0 };
  const merchants = useQuery({
    queryKey: [...queryKeys.merchants.all, "add-user-options"],
    queryFn: async ({ signal }) => {
      const first = await listMerchants(merchantParams, signal);
      const items = [...first.items];
      for (let offset=merchantParams.limit; offset<first.total; offset+=merchantParams.limit) {
        const next=await listMerchants({...merchantParams,offset},signal);
        items.push(...next.items);
        if (!next.items.length) break;
      }
      return {...first,items};
    },
    enabled: open,
    staleTime: 0
  });

  const mutation = useMutation({
    mutationFn: async (values: Values) => {
      const mobile = normalizeMobileNumber(values.mobile_number) ?? values.mobile_number;
      // Give an early duplicate warning; the backend remains authoritative.
      const existing = await listUsers({ search: mobile, limit: 20, offset: 0 });
      if (existing.items.some((user) => user.mobile_number === mobile)) {
        throw new AppError({
          kind: "conflict",
          status: 409,
          userMessage: DUPLICATE_MOBILE,
          fieldErrors: { mobile_number: DUPLICATE_MOBILE }
        });
      }
      return createUser({
        full_name: values.full_name.trim(),
        mobile_number: mobile,
        country_code: "+91",
        email: emptyToUndefined(values.email)?.toLowerCase(),
        status: "ACTIVE",
        role: values.role,
        merchantId: requiresMerchant ? values.merchantId : undefined,
        staffType: requiresMerchant ? emptyToUndefined(values.staffType)?.trim() : undefined
      });
    },
    onSuccess: (user) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.lists() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminDashboard.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      queryClient.setQueryData(queryKeys.users.detail(user.id), user);
      toast.success(`${user.full_name ?? "The user"} has been added and can now sign in.`);
      close();
      navigate(`/admin/users/${user.id}`);
    },
    onError: (error) => setFormMessage(applyServerErrors(error, setError, ["full_name", "mobile_number", "email", "role", "merchantId", "staffType"]))
  });

  function close() {
    reset();
    setFormMessage(null);
    onClose();
  }

  return (
    <Modal
      open={open}
      onClose={close}
      busy={mutation.isPending}
      title="Add user"
      description="The role decides which panel they can use and what they can do."
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="add-user-form" variant="primary" loading={mutation.isPending} loadingText="Adding…" disabled={!scopeReady || (requiresMerchant && (merchants.isPending || Boolean(merchants.error)))}>
            Add user
          </Button>
        </>
      }
    >
      <form
        id="add-user-form"
        className="stack"
        noValidate
        onSubmit={handleSubmit((values) => {
          setFormMessage(null);
          if (!scopeReady) { setError("role",{message:"Choose a configured role before adding this user."}); return; }
          if (requiresMerchant && !values.merchantId) { setError("merchantId",{message:"Choose the merchant this user works for."}); return; }
          mutation.mutate(values);
        })}
      >
        {formMessage ? <Alert tone="error">{formMessage}</Alert> : null}
        <Field label="Full name" required error={fieldError(formState.errors, "full_name")}>
          <Input autoComplete="name" {...register("full_name")} />
        </Field>
        <Field
          label="Mobile number"
          required
          error={fieldError(formState.errors, "mobile_number")}
          hint="Used to sign in with a verification code."
        >
          <PhoneInput {...register("mobile_number")} />
        </Field>
        <Field label="Email address" optional error={fieldError(formState.errors, "email")}>
          <Input type="email" autoComplete="email" {...register("email")} />
        </Field>
        <Field label="Role" required hint="Active roles configured for the Admin or Merchant panel." error={fieldError(formState.errors, "role")}>
          <Select placeholder={rolesQuery.isPending ? "Loading roles…" : "Choose a role"} options={roleOptions} {...register("role")} />
        </Field>
        {rolesQuery.isError ? <Alert tone="error">Roles could not be loaded.<Button variant="secondary" onClick={()=>void rolesQuery.refetch()}>Retry roles</Button></Alert> : null}
        {selectedRole && !requiresMerchant ? <p className="meta">This role does not use the Merchant panel, so no merchant is needed.</p> : null}
        {!role || requiresMerchant ? (
          <>
            <Field
              label="Merchant"
              required
              error={fieldError(formState.errors, "merchantId")}
              hint={merchants.error ? "Merchants could not be loaded." : "The agency this user works for."}
            >
              <Select
                placeholder={merchants.isLoading ? "Loading merchants…" : "Choose a merchant"}
                options={(merchants.data?.items ?? []).map((m) => ({ value: m.id, label: `${m.business_name} (${m.merchant_code})` }))}
                disabled={merchants.isPending || Boolean(merchants.error)}
                {...register("merchantId")}
              />
            </Field>
            {merchants.isError ? <Button variant="secondary" onClick={()=>void merchants.refetch()}>Retry merchants</Button> : null}
            <Field label="Job title" optional error={fieldError(formState.errors, "staffType")} hint="Leave blank to use the role.">
              <Input {...register("staffType")} />
            </Field>
          </>
        ) : null}
      </form>
    </Modal>
  );
}
