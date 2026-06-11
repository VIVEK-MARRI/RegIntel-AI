import { useState } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Field, Input, TextArea } from "@/components/ui/Field";
import { useCreateWorkflow, useRunWorkflow, useWorkflows } from "@/hooks/api";
import { useDemoQuery } from "@/hooks/useDemoFallback";
import { demoWorkflows } from "@/lib/demo";
import { useToast } from "@/providers/ToastProvider";
import { formatRelative } from "@/lib/format";

export function AgentWorkflowsPage() {
  const workflows = useDemoQuery("Agent Workflows", demoWorkflows, useWorkflows);
  const create = useCreateWorkflow();
  const runWf = useRunWorkflow();
  const toast = useToast();
  const [name, setName] = useState("KYC Renewal Check");
  const [description, setDescription] = useState("Validate KYC renewal across portfolio");
  const [definition, setDefinition] = useState(
    JSON.stringify(
      {
        steps: [
          {
            step_id: "s1",
            agent_name: "research-agent",
            capability: "regulatory_search",
            depends_on: [],
          },
          {
            step_id: "s2",
            agent_name: "compliance-agent",
            capability: "obligation_check",
            depends_on: ["s1"],
          },
        ],
      },
      null,
      2
    )
  );

  async function handleCreate() {
    try {
      const parsed = JSON.parse(definition);
      await create.mutateAsync({ name, description, steps: parsed.steps });
      toast.push({ title: "Workflow created", tone: "success" });
    } catch (err) {
      toast.push({
        title: "Invalid definition",
        description: err instanceof Error ? err.message : "JSON parse error",
        tone: "danger",
      });
    }
  }

  async function handleRun(id: string) {
    try {
      const r = await runWf.mutateAsync({ workflow_id: id });
      toast.push({
        title: "Workflow started",
        description: `Execution ${r.execution_id}`,
        tone: "success",
      });
    } catch (err) {
      toast.push({
        title: "Run failed",
        description: err instanceof Error ? err.message : "Unexpected error",
        tone: "danger",
      });
    }
  }

  return (
    <div className="mx-auto grid max-w-7xl grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
      <Card padding="none">
        <CardHeader
          title="Workflows"
          description="Reusable multi-agent execution plans"
        />
        <div className="card-body">
          {workflows.isLoading ? (
            <Skeleton lines={5} />
          ) : workflows.isError ? (
            <ErrorState error={workflows.error} onRetry={() => workflows.refetch()} />
          ) : !workflows.data || workflows.data.length === 0 ? (
            <EmptyState
              title="No workflows yet"
              description="Create a workflow on the right to get started."
            />
          ) : (
            <ul className="space-y-2">
              {workflows.data.map((w) => (
                <li
                  key={w.workflow_id}
                  className="rounded-xl border border-slate-200 p-3 dark:border-slate-800"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {w.name}
                    </span>
                    <Badge tone="brand" size="sm">
                      {w.steps.length} steps
                    </Badge>
                    <span className="ml-auto text-[10px] text-slate-500 dark:text-slate-400">
                      {w.created_at ? formatRelative(w.created_at) : ""}
                    </span>
                  </div>
                  {w.description ? (
                    <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                      {w.description}
                    </p>
                  ) : null}
                  <div className="mt-2">
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => handleRun(w.workflow_id)}
                      loading={runWf.isPending}
                    >
                      Run
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      <Card padding="none">
        <CardHeader
          title="Create workflow"
          description="Define steps in JSON"
        />
        <div className="card-body space-y-3">
          <Field label="Name" id="wf-name">
            <Input
              id="wf-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Description" id="wf-desc">
            <Input
              id="wf-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <Field label="Definition (JSON)" id="wf-def">
            <TextArea
              id="wf-def"
              rows={10}
              value={definition}
              onChange={(e) => setDefinition(e.target.value)}
              className="font-mono text-[11px]"
            />
          </Field>
          <Button
            variant="primary"
            onClick={handleCreate}
            loading={create.isPending}
            disabled={!name.trim()}
          >
            Create
          </Button>
        </div>
      </Card>
    </div>
  );
}
