import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";

import { AppError } from "../../api/errors";
import { queryKeys } from "../../api/query-keys";
import { createUser, listUsers } from "../../api/users.api";
import { Button } from "../../components/common/Button";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, PhoneInput } from "../../components/forms/Field";
import { applyServerErrors, fieldError, zodResolver } from "../../components/forms/form-utils";
import { mobileSchema, optionalEmailSchema, requiredText } from "../../schemas/common";
import { emptyToUndefined } from "../../utils/format";
import { normalizeMobileNumber } from "../../utils/mobile";

const schema = z.object({
  full_name: requiredText("the full name", 2, 160),
  mobile_number: mobileSchema,
  email: optionalEmailSchema
});
type Values = z.infer<typeof schema>;

const DUPLICATE_MOBILE = "A user with this mobile number already exists.";

export function AddUserDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [formMessage, setFormMessage] = useState<string | null>(null);
  const { register, handleSubmit, formState, setError, reset } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { full_name: "", mobile_number: "", email: "" }
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
        status: "ACTIVE"
      });
    },
    onSuccess: (user) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.lists() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminDashboard.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      queryClient.setQueryData(queryKeys.users.detail(user.id), user);
      toast.success(`${user.full_name ?? "The user"} has been added. Assign a role so they can sign in.`);
      close();
      navigate(`/admin/users/${user.id}?tab=roles`);
    },
    onError: (error) => setFormMessage(applyServerErrors(error, setError, ["full_name", "mobile_number", "email"]))
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
      description="After adding the user, assign a role to decide which panel they can use and what they can do."
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
      </form>
    </Modal>
  );
}
