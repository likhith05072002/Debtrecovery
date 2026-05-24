import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation } from "@tanstack/react-query";
import { campaignsApi } from "@/api/campaigns";
import { Modal } from "@/components/ui/Modal";
import { Input, Select } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

const schema = z.object({
  name: z.string().min(1, "Required").max(200),
  strategy_type: z.enum(["auto", "reminder", "negotiation", "settlement", "escalation"]),
  max_attempts: z.number().min(1).max(20),
  call_window_start: z.string().optional(),
  call_window_end: z.string().optional(),
  retry_interval_hrs: z.number().min(1),
  settlement_floor_pct: z.number().min(0).max(1),
});

type FormValues = z.infer<typeof schema>;

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export default function CampaignForm({ open, onClose, onSaved }: Props) {
  const { register, handleSubmit, reset, formState: { errors } } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { strategy_type: "auto", max_attempts: 5, retry_interval_hrs: 24, settlement_floor_pct: 0.5 },
  });

  const { mutate, isPending, error } = useMutation({
    mutationFn: (data: FormValues) => campaignsApi.create(data),
    onSuccess: () => { reset(); onSaved(); },
  });

  return (
    <Modal open={open} onClose={onClose} title="New Campaign">
      <form onSubmit={handleSubmit((d) => mutate(d))} className="space-y-4">
        <Input label="Campaign Name *" {...register("name")} error={errors.name?.message} placeholder="Q2 Outreach" />
        <Select label="Strategy *" {...register("strategy_type")}>
          <option value="auto">Auto (ML-selected)</option>
          <option value="reminder">Reminder</option>
          <option value="negotiation">Negotiation</option>
          <option value="settlement">Settlement</option>
          <option value="escalation">Escalation</option>
        </Select>
        <div className="grid grid-cols-2 gap-4">
          <Input label="Max Attempts" type="number" {...register("max_attempts", { valueAsNumber: true })} error={errors.max_attempts?.message} />
          <Input label="Retry Interval (hrs)" type="number" {...register("retry_interval_hrs", { valueAsNumber: true })} />
          <Input label="Call Window Start" type="time" {...register("call_window_start")} />
          <Input label="Call Window End" type="time" {...register("call_window_end")} />
        </div>
        <Input
          label="Settlement Floor (0.0–1.0)"
          type="number"
          step="0.01"
          min="0"
          max="1"
          {...register("settlement_floor_pct", { valueAsNumber: true })}
          placeholder="0.50"
        />
        {error && <p className="text-sm text-red-600">{(error as Error).message}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={isPending}>Create Campaign</Button>
        </div>
      </form>
    </Modal>
  );
}
