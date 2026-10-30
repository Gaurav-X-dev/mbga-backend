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

/** A platform user belongs to no agency, so a platform role takes no merchant. */
const PLATFORM_ROLE = "super_admin";

/** Every active role, and the ones that sign in on the admin channel. */
const ALL_ROLES = { is_active: true, page: 1, page_size: 100 } as const;
const PLATFORM_ROLES = { is_active: true, login_channel: "ADMIN", page: 1, page_size: 100 } as const;

/**
 * Which role codes are platform roles.
 *
 * The list used to be five hardcoded entries, so a role created in Roles & Access never
 * appeared here and could not be given to a new user. It is read from the API now, and this
 * set exists because the schema below is built once at module scope and cannot reach a query
 * result. It is seeded with `super_admin` so the form still judges correctly in the moment
 * before the roles have loaded.
 */
const knownPlatformRoles = new Set<string>([PLATFORM_ROLE]);

const schema = z
  .object({
    full_name: requiredText("the full name", 2, 160),
    mobile_number: mobileSchema,
    email: optionalEmailSchema,
    role: z.string().min(1, "Choose a role."),
    merchantId: z.string(),
    staffType: z.string().max(60).optional()
  })
  .refine((v) => knownPlatformRoles.has(v.role) || v.merchantId, { path: ["merchantId"], message: "Choose the merchant this user works for." });
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
    queryKey: queryKeys.roles.list(ALL_ROLES),
    queryFn: ({ signal }) => listRoles(ALL_ROLES, signal),
    enabled: open
  });
  const platformRolesQuery = useQuery({
    queryKey: queryKeys.roles.list(PLATFORM_ROLES),
    queryFn: ({ signal }) => listRoles(PLATFORM_ROLES, signal),
    enabled: open
  });
  const roleOptions = (rolesQuery.data?.items ?? []).map((item) => ({ value: item.code, label: item.name }));
  for (const item of platformRolesQuery.data?.items ?? []) knownPlatformRoles.add(item.code);
  const isPlatform = knownPlatformRoles.has(role);
  const merchantParams = { limit: 100, offset: 0 };
  const merchants = useQuery({
    queryKey: queryKeys.merchants.list(merchantParams),
    queryFn: ({ signal }) => listMerchants(merchantParams, signal),
    enabled: open,
    staleTime: 5 * 60_000
  });

  const mutation = useMutation({
    mutationFn: async (values: Values) => {
      const mobile = normalizeMobileNumber(values.mobile_number) ?? values.mobile_number;
      // The backend does not reject duplicate mobile numbers for users, so check first.
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
        merchantId: values.role === PLATFORM_ROLE ? undefined : values.merchantId,
        staffType: values.role === PLATFORM_ROLE ? undefined : emptyToUndefined(values.staffType)?.trim()
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
          <Button type="submit" form="add-user-form" variant="primary" loading={mutation.isPending} loadingText="Adding…">
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
        <Field label="Role" required error={fieldError(formState.errors, "role")}>
          <Select placeholder={rolesQuery.isPending ? "Loading roles…" : "Choose a role"} options={roleOptions} {...register("role")} />
        </Field>
        {isPlatform ? null : (
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
                {...register("merchantId")}
              />
            </Field>
            <Field label="Job title" optional error={fieldError(formState.errors, "staffType")} hint="Leave blank to use the role.">
              <Input {...register("staffType")} />
            </Field>
          </>
        )}
      </form>
    </Modal>
  );
}
