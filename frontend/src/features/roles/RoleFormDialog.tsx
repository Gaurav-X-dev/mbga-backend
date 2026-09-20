import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";

import { queryKeys } from "../../api/query-keys";
import { createRole, updateRole, type Role } from "../../api/roles.api";
import { Button } from "../../components/common/Button";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, Textarea } from "../../components/forms/Field";
import { applyServerErrors, fieldError, zodResolver } from "../../components/forms/form-utils";
import { requiredText } from "../../schemas/common";
import { emptyToNull, emptyToUndefined } from "../../utils/format";

/** Mirrors backend RoleCreate: code must match ^[a-z0-9][a-z0-9_]*$ */
const createSchema = z.object({
  name: requiredText("a role name", 2, 120),
  code: z
    .string()
    .trim()
    .min(1, "Enter a role code.")
    .regex(/^[a-z0-9][a-z0-9_]*$/, "Use lowercase letters, numbers and underscores only, e.g. area_supervisor."),
  description: z.string().trim().max(500, "Description must be 500 characters or fewer.")
});
type Values = z.infer<typeof createSchema>;

function suggestRoleCode(name: string) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 60);
}

export function RoleFormDialog({ role, onClose }: { role?: Role; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [formMessage, setFormMessage] = useState<string | null>(null);
  const [codeTouched, setCodeTouched] = useState(false);
  const editing = Boolean(role);
  const { register, handleSubmit, formState, setError, setValue } = useForm<Values>({
    // Existing role codes already satisfy the pattern, so one schema serves both modes.
    resolver: zodResolver(createSchema),
    defaultValues: { name: role?.name ?? "", code: role?.code ?? "", description: role?.description ?? "" }
  });

  const mutation = useMutation({
    mutationFn: (values: Values) =>
      role
        ? updateRole(role.id, { name: values.name.trim(), description: emptyToNull(values.description) })
        : createRole({ name: values.name.trim(), code: values.code.trim(), description: emptyToUndefined(values.description) }),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.roles.detail(saved.id), saved);
      void queryClient.invalidateQueries({ queryKey: queryKeys.roles.lists() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminDashboard.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      toast.success(role ? "Role saved." : `${saved.name} role added. Choose what it can do.`);
      onClose();
      if (!role) navigate(`/admin/roles/${saved.id}?tab=permissions`);
    },
    onError: (error) => setFormMessage(applyServerErrors(error, setError, ["name", "code", "description"]))
  });

  const nameField = register("name");

  return (
    <Modal
      open
      onClose={onClose}
      busy={mutation.isPending}
      title={role ? "Edit role" : "Add role"}
      description={role ? undefined : "After adding the role, choose its permissions and which panels it can sign in to."}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="role-form" variant="primary" loading={mutation.isPending} loadingText="Saving…">
            {role ? "Save changes" : "Add role"}
          </Button>
        </>
      }
    >
      <form
        id="role-form"
        className="stack"
        noValidate
        onSubmit={handleSubmit((values) => {
          setFormMessage(null);
          mutation.mutate(values);
        })}
      >
        {formMessage ? <Alert tone="error">{formMessage}</Alert> : null}
        <Field label="Role name" required error={fieldError(formState.errors, "name")} hint="Example: Area supervisor">
          <Input
            {...nameField}
            onChange={(event) => {
              void nameField.onChange(event);
              if (!editing && !codeTouched) setValue("code", suggestRoleCode(event.target.value));
            }}
          />
        </Field>
        {editing ? null : (
          <Field
            label="Role code"
            required
            error={fieldError(formState.errors, "code")}
            hint="A permanent internal reference. It is suggested from the name and cannot be changed later."
          >
            <Input
              className="mono"
              {...register("code", { onChange: () => setCodeTouched(true) })}
            />
          </Field>
        )}
        <Field label="Description" optional error={fieldError(formState.errors, "description")} hint="What people with this role do.">
          <Textarea rows={3} {...register("description")} />
        </Field>
      </form>
    </Modal>
  );
}
