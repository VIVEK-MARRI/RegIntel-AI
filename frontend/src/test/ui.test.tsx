import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Alert } from "@/components/ui/Alert";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { Field, Input, Select, TextArea } from "@/components/ui/Field";
import { Metric } from "@/components/ui/Metric";

describe("UI primitives", () => {
  it("Button renders with variants and loading state", () => {
    render(
      <Button variant="primary" loading iconLeft={<span>L</span>}>
        Save
      </Button>
    );
    const btn = screen.getByRole("button", { name: /save/i });
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveAttribute("aria-busy", "true");
    expect(btn).toBeDisabled();
  });

  it("Card + CardHeader + CardBody render structured", () => {
    render(
      <Card>
        <CardHeader title="Title" description="Desc" actions={<span>A</span>} />
        <CardBody>body</CardBody>
      </Card>
    );
    expect(screen.getByText("Title")).toBeInTheDocument();
    expect(screen.getByText("Desc")).toBeInTheDocument();
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();
  });

  it("Badge renders tone and dot", () => {
    const { container } = render(
      <Badge tone="success" dot>
        ok
      </Badge>
    );
    expect(container.firstChild).toHaveClass("badge-success");
  });

  it("Skeleton renders with line count", () => {
    const { container } = render(<Skeleton lines={3} />);
    expect(container.querySelectorAll(".skeleton").length).toBe(3);
  });

  it("ErrorState surfaces error message and retry", async () => {
    const retry = vi.fn();
    render(
      <ErrorState
        title="Boom"
        error={new Error("nope")}
        onRetry={retry}
      />
    );
    expect(screen.getByText("Boom")).toBeInTheDocument();
    expect(screen.getByText(/nope/)).toBeInTheDocument();
    const btn = screen.getByRole("button", { name: /retry/i });
    btn.click();
    expect(retry).toHaveBeenCalledOnce();
  });

  it("EmptyState renders action", async () => {
    const action = <button type="button">Go</button>;
    render(
      <EmptyState
        title="Nothing"
        description="No items"
        action={action}
      />
    );
    expect(screen.getByText("Nothing")).toBeInTheDocument();
    expect(screen.getByText("No items")).toBeInTheDocument();
    expect(screen.getByText("Go")).toBeInTheDocument();
  });

  it("Alert renders and supports dismiss", async () => {
    const dismiss = vi.fn();
    render(
      <Alert tone="warning" title="Careful" onDismiss={dismiss}>
        detail
      </Alert>
    );
    expect(screen.getByText("Careful")).toBeInTheDocument();
    screen.getByRole("button", { name: /dismiss/i }).click();
    expect(dismiss).toHaveBeenCalledOnce();
  });

  it("ProgressBar exposes ARIA progressbar role", () => {
    render(<ProgressBar value={40} max={100} showLabel />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "40");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
  });

  it("Table primitives render correctly", () => {
    render(
      <Table>
        <THead>
          <TR>
            <TH>A</TH>
          </TR>
        </THead>
        <TBody>
          <TR>
            <TD>1</TD>
          </TR>
        </TBody>
      </Table>
    );
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("Field, Input, Select, TextArea render", () => {
    render(
      <Field label="L" hint="h" id="x">
        <Input id="x" placeholder="p" />
        <Select id="s">
          <option>a</option>
        </Select>
        <TextArea id="t" />
      </Field>
    );
    expect(screen.getByLabelText("L")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("p")).toBeInTheDocument();
  });

  it("Metric renders label and value with hint", () => {
    render(
      <Metric
        label="Active"
        value={42}
        hint="hint"
        delta={{ value: "+5%", positive: true }}
      />
    );
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("hint")).toBeInTheDocument();
    expect(screen.getByText("+5%")).toBeInTheDocument();
  });
});
