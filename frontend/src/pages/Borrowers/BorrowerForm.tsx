import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation } from "@tanstack/react-query";
import { borrowersApi } from "@/api/borrowers";
import { Modal } from "@/components/ui/Modal";
import { Input, Select } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

const schema = z.object({
  external_id: z.string().min(1, "Required"),
  phone: z.string().min(10, "Enter a valid phone"),
  first_name: z.string().optional(),
  last_name: z.string().optional(),
  original_creditor: z.string().optional(),
  principal_amount: z.number().positive("Must be positive"),
  current_balance: z.number().positive("Must be positive"),
  days_past_due: z.number().min(0).optional(),
  debt_type: z.string().optional(),
  time_zone: z.string(),
  consent_recorded: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export default function BorrowerForm({ open, onClose, onSaved }: Props) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { time_zone: "America/New_York", consent_recorded: true, days_past_due: 0 },
  });

  const { mutate, isPending, error } = useMutation({
    mutationFn: (data: FormValues) =>
      borrowersApi.create({
        ...data,
        principal_amount: data.principal_amount,
        current_balance: data.current_balance,
        days_past_due: data.days_past_due ?? 0,
      }),
    onSuccess: () => {
      reset();
      onSaved();
    },
  });

  return (
    <Modal open={open} onClose={onClose} title="New Borrower" className="max-w-2xl">
      <form onSubmit={handleSubmit((d) => mutate(d))} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <Input label="External ID *" {...register("external_id")} error={errors.external_id?.message} placeholder="CRM-001" />
          <Input label="Phone (E.164) *" {...register("phone")} error={errors.phone?.message} placeholder="+12025551234" />
          <Input label="First Name" {...register("first_name")} placeholder="John" />
          <Input label="Last Name" {...register("last_name")} placeholder="Smith" />
          <Input label="Original Creditor" {...register("original_creditor")} placeholder="Bank of America" />
          <Input label="Debt Type" {...register("debt_type")} placeholder="credit_card" />
          <Input
            label="Principal Amount *"
            type="number"
            step="0.01"
            {...register("principal_amount", { valueAsNumber: true })}
            error={errors.principal_amount?.message}
          />
          <Input
            label="Current Balance *"
            type="number"
            step="0.01"
            {...register("current_balance", { valueAsNumber: true })}
            error={errors.current_balance?.message}
          />
          <Input
            label="Days Past Due"
            type="number"
            {...register("days_past_due", { valueAsNumber: true })}
          />
          <Select label="Timezone" {...register("time_zone")}>
            <option value="America/New_York">Eastern</option>
            <option value="America/Chicago">Central</option>
            <option value="America/Denver">Mountain</option>
            <option value="America/Los_Angeles">Pacific</option>
          </Select>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
          <input type="checkbox" {...register("consent_recorded")} className="rounded" />
          TCPA consent recorded
        </label>
        {error && <p className="text-sm text-red-600">{(error as Error).message}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={isPending}>Create Borrower</Button>
        </div>
      </form>
    </Modal>
  );
}
