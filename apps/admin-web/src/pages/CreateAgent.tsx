import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";

import { useCreateAgent, useModelPolicies } from "@/api/hooks";
import { ApiError } from "@/api/client";

const AVAILABLE_TOOLS = ["artifact.write", "artifact.read", "knowledge.read", "calculator.execute"];

const schema = z.object({
  agent_code: z.string().min(1, "Required"),
  display_name: z.string().min(1, "Required"),
  description: z.string().optional(),
  department: z.string().optional(),
  role_name: z.string().optional(),
  system_prompt: z.string().min(1, "Required"),
  runtime_adapter: z.string().min(1),
  model_policy_id: z.string().min(1, "Select a model policy"),
  autonomy_level: z.enum(["A1", "A2", "A3"]),
  tools: z.array(z.string()).min(1, "Select at least one tool"),
});

type FormValues = z.infer<typeof schema>;

export function CreateAgent() {
  const navigate = useNavigate();
  const { data: modelPolicies } = useModelPolicies();
  const createAgent = useCreateAgent();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const {
    register,
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { runtime_adapter: "custom_durable", autonomy_level: "A1", tools: [] },
  });

  async function onSubmit(values: FormValues) {
    setSubmitError(null);
    try {
      await createAgent.mutateAsync({
        agent_code: values.agent_code,
        display_name: values.display_name,
        description: values.description,
        department: values.department,
        role_name: values.role_name,
        version: {
          system_prompt: values.system_prompt,
          runtime_adapter: values.runtime_adapter,
          model_policy_id: values.model_policy_id,
          autonomy_level: values.autonomy_level,
          tool_policy: { allow: values.tools, deny: ["*"] },
        },
      });
      navigate("/agents");
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Failed to create agent.");
    }
  }

  return (
    <div>
      <h2>Create Agent</h2>
      <form className="card" onSubmit={handleSubmit(onSubmit)} style={{ maxWidth: 560 }}>
        <div className="form-field">
          <label htmlFor="agent_code">Agent code</label>
          <input id="agent_code" {...register("agent_code")} placeholder="AGT-000002" />
          {errors.agent_code && <span className="form-error">{errors.agent_code.message}</span>}
        </div>

        <div className="form-field">
          <label htmlFor="display_name">Name</label>
          <input id="display_name" {...register("display_name")} />
          {errors.display_name && <span className="form-error">{errors.display_name.message}</span>}
        </div>

        <div className="form-field">
          <label htmlFor="description">Description</label>
          <textarea id="description" rows={2} {...register("description")} />
        </div>

        <div className="form-field">
          <label htmlFor="department">Department</label>
          <input id="department" {...register("department")} />
        </div>

        <div className="form-field">
          <label htmlFor="role_name">Role</label>
          <input id="role_name" {...register("role_name")} />
        </div>

        <div className="form-field">
          <label htmlFor="system_prompt">System prompt</label>
          <textarea id="system_prompt" rows={5} {...register("system_prompt")} />
          {errors.system_prompt && <span className="form-error">{errors.system_prompt.message}</span>}
        </div>

        <div className="form-field">
          <label htmlFor="runtime_adapter">Runtime adapter</label>
          <select id="runtime_adapter" {...register("runtime_adapter")}>
            <option value="custom_durable">custom_durable</option>
            <option value="langgraph">langgraph (not implemented in Phase 0)</option>
          </select>
        </div>

        <div className="form-field">
          <label htmlFor="model_policy_id">Model policy</label>
          <select id="model_policy_id" {...register("model_policy_id")}>
            <option value="">Select…</option>
            {modelPolicies?.map((policy) => (
              <option key={policy.id} value={policy.id}>
                {policy.name} ({policy.primary_provider}/{policy.primary_model})
              </option>
            ))}
          </select>
          {errors.model_policy_id && <span className="form-error">{errors.model_policy_id.message}</span>}
        </div>

        <div className="form-field">
          <label htmlFor="autonomy_level">Autonomy level</label>
          <select id="autonomy_level" {...register("autonomy_level")}>
            <option value="A1">A1</option>
            <option value="A2">A2</option>
            <option value="A3">A3</option>
          </select>
        </div>

        <div className="form-field">
          <label>Tool permissions</label>
          <Controller
            control={control}
            name="tools"
            render={({ field }) => (
              <div>
                {AVAILABLE_TOOLS.map((tool) => (
                  <label key={tool} style={{ display: "block", fontWeight: 400 }}>
                    <input
                      type="checkbox"
                      checked={field.value.includes(tool)}
                      onChange={(e) => {
                        field.onChange(
                          e.target.checked
                            ? [...field.value, tool]
                            : field.value.filter((t) => t !== tool),
                        );
                      }}
                    />{" "}
                    {tool}
                  </label>
                ))}
              </div>
            )}
          />
          {errors.tools && <span className="form-error">{errors.tools.message}</span>}
        </div>

        {submitError && <p className="form-error">{submitError}</p>}
        <button className="btn" type="submit" disabled={createAgent.isPending}>
          {createAgent.isPending ? "Creating…" : "Create agent"}
        </button>
      </form>
    </div>
  );
}
