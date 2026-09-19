import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { ApiError } from "@/api/client";
import { useArchiveProject, useCreateProject, useProjects } from "@/api/hooks";

// ADR-014 decision 2 / data-warden D12: same shape the API validates.
const schema = z.object({
  code: z
    .string()
    .min(1, "Required")
    .max(20, "20 characters max")
    .regex(/^[A-Z0-9][A-Z0-9_-]*$/, "Uppercase letters, digits, _ and - only; must start with a letter or digit"),
  name: z.string().min(1, "Required").max(80, "80 characters max"),
});
type FormValues = z.infer<typeof schema>;

export function Projects() {
  const { data: projects, isLoading } = useProjects();
  const createProject = useCreateProject();
  const archiveProject = useArchiveProject();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  async function onSubmit(values: FormValues) {
    setSubmitError(null);
    try {
      await createProject.mutateAsync(values);
      reset();
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Failed to create project.");
    }
  }

  return (
    <div>
      <h2>Projects</h2>
      <p style={{ color: "var(--text-muted)", marginTop: "-0.5rem" }}>
        Each project becomes a building in the 3D World (ADR-014). A mission with no project
        is worked at the community hall.
      </p>

      <form className="card" onSubmit={handleSubmit(onSubmit)}>
        <h3 style={{ marginTop: 0 }}>New project</h3>
        <p className="form-error" style={{ color: "var(--warning-color, #b45309)" }}>
          This code may appear in shared screenshots of the 3D world. Use an internal codename,
          never a client&apos;s legal name.
        </p>
        <div className="form-field">
          <label htmlFor="code">Code</label>
          <input id="code" placeholder="e.g. ATLAS" {...register("code")} />
          {errors.code && <span className="form-error">{errors.code.message}</span>}
        </div>
        <div className="form-field">
          <label htmlFor="name">Internal name</label>
          <input id="name" {...register("name")} />
          {errors.name && <span className="form-error">{errors.name.message}</span>}
        </div>
        {submitError && <p className="form-error">{submitError}</p>}
        <button className="btn" type="submit" disabled={createProject.isPending}>
          {createProject.isPending ? "Creating…" : "Create project"}
        </button>
      </form>

      <h3>All projects</h3>
      {isLoading && <p>Loading…</p>}
      <table>
        <thead>
          <tr>
            <th>Code</th>
            <th>Name</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {projects?.map((project) => (
            <tr key={project.id}>
              <td>{project.code}</td>
              <td>{project.name}</td>
              <td>
                <span className={`badge status-${project.status}`}>{project.status}</span>
              </td>
              <td>
                {project.status === "active" && (
                  <button
                    className="btn danger"
                    onClick={() => archiveProject.mutate(project.id)}
                    disabled={archiveProject.isPending}
                  >
                    Archive
                  </button>
                )}
              </td>
            </tr>
          ))}
          {projects?.length === 0 && (
            <tr>
              <td colSpan={4} style={{ color: "var(--text-muted)" }}>
                No projects yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
