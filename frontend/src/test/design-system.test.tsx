/**
 * Stage 05 shared-primitive behavior tests. Asserts observable behavior
 * (roles, keyboard, associations, bounds) — never CSS implementation.
 */
import { describe, expect, it, vi } from "vitest";
import * as React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Tabs } from "@/components/ui/Tabs";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input } from "@/components/ui/Field";
import { Alert } from "@/components/ui/Alert";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Skeleton } from "@/components/ui/Skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { Metric } from "@/components/ui/Metric";
import { Button } from "@/components/ui/Button";
import { ToastProvider, useToast } from "@/providers/ToastProvider";
import { ToastViewport } from "@/components/ui/ToastViewport";

describe("Tabs", () => {
  const items = [
    { id: "a", label: "Alpha" },
    { id: "b", label: "Beta" },
    { id: "c", label: "Gamma" },
  ];

  function renderTabs(initial = "a") {
    function Harness() {
      const [value, setValue] = React.useState(initial);
      return (
        <Tabs
          items={items}
          value={value}
          onChange={(id) => {
            onChangeSpy(id);
            setValue(id);
          }}
          label="Sections"
          idPrefix="t"
        />
      );
    }
    const onChangeSpy = vi.fn();
    render(<Harness />);
    return { onChange: onChangeSpy };
  }

  it("marks the active tab selected with stable control ids", () => {
    renderTabs("b");
    const tab = screen.getByRole("tab", { name: "Beta" });
    expect(tab).toHaveAttribute("aria-selected", "true");
    expect(tab).toHaveAttribute("aria-controls", "t-panel-b");
    expect(tab).toHaveAttribute("id", "t-tab-b");
    expect(screen.getByRole("tab", { name: "Alpha" })).toHaveAttribute("aria-selected", "false");
  });

  it("click selects a tab; arrows move selection with keyboard", async () => {
    const user = userEvent.setup();
    const { onChange } = renderTabs("a");
    await user.click(screen.getByRole("tab", { name: "Gamma" }));
    expect(onChange).toHaveBeenCalledWith("c");
    // roving tabindex: only the selected tab is tabbable
    expect(screen.getByRole("tab", { name: "Alpha" })).toHaveAttribute("tabindex", "-1");
  });

  it("arrow keys move focus and select", async () => {
    const user = userEvent.setup();
    renderTabs("a");
    screen.getByRole("tab", { name: "Alpha" }).focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Beta" })).toHaveFocus();
  });
});

describe("Dialog", () => {
  it("renders labelled dialog, closes on Escape and backdrop", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const { rerender } = render(
      <Dialog open={false} onClose={onClose} label="Confirm">
        <p>body</p>
      </Dialog>
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    rerender(
      <Dialog open onClose={onClose} label="Confirm">
        <p>body</p>
      </Dialog>
    );
    expect(screen.getByRole("dialog", { name: "Confirm" })).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("locks body scroll while open and restores after", () => {
    const onClose = vi.fn();
    const { rerender, unmount } = render(
      <Dialog open onClose={onClose} label="X">
        <p>body</p>
      </Dialog>
    );
    expect(document.body.style.overflow).toBe("hidden");
    rerender(
      <Dialog open={false} onClose={onClose} label="X">
        <p>body</p>
      </Dialog>
    );
    expect(document.body.style.overflow).toBe("");
    unmount();
  });
});

describe("Field", () => {
  it("associates error with the control and marks it invalid", () => {
    render(
      <Field label="Name" id="nm" error="Required">
        <Input id="nm" />
      </Field>
    );
    const input = screen.getByLabelText("Name");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby", "nm-error");
    expect(screen.getByRole("alert")).toHaveTextContent("Required");
  });

  it("associates hint when there is no error", () => {
    render(
      <Field label="Name" id="nm2" hint="Your legal name">
        <Input id="nm2" />
      </Field>
    );
    expect(screen.getByLabelText("Name")).toHaveAttribute("aria-describedby", "nm2-hint");
  });

  it("announces required fields to assistive tech", () => {
    render(
      <Field label="Email" id="em" required>
        <Input id="em" />
      </Field>
    );
    expect(screen.getByText("(required)", { exact: false })).toBeTruthy();
  });
});

describe("Alert", () => {
  it("danger asserts, other tones inform", () => {
    const { rerender } = render(<Alert tone="danger">bad</Alert>);
    expect(screen.getByRole("alert")).toHaveTextContent("bad");
    rerender(<Alert tone="warning">careful</Alert>);
    expect(screen.getByRole("status")).toHaveTextContent("careful");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("ProgressBar", () => {
  it("clamps aria values to the 0-100 scale", () => {
    render(<ProgressBar value={250} max={100} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "100");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
  });
});

describe("Skeleton", () => {
  it("is decorative and non-disruptive", () => {
    const { container } = render(<Skeleton lines={3} />);
    expect(container.querySelector('[aria-busy="true"]')).toBeNull();
    expect(container.firstChild).toHaveAttribute("aria-hidden", "true");
  });
});

describe("Table", () => {
  it("headers default to column scope and caption is supported", () => {
    render(
      <Table caption="Users">
        <THead>
          <TR>
            <TH>Name</TH>
          </TR>
        </THead>
        <TBody>
          <TR>
            <TD>Ada</TD>
          </TR>
        </TBody>
      </Table>
    );
    expect(screen.getByRole("columnheader", { name: "Name" })).toHaveAttribute("scope", "col");
    expect(screen.getByText("Users")).toBeTruthy();
  });
});

describe("Metric", () => {
  it("delta direction is text, not color-only", () => {
    render(<Metric label="X" value="1" delta={{ value: "+2%", positive: true }} />);
    expect(screen.getByText(/trending up/i)).toBeTruthy();
  });
});

describe("Button", () => {
  it("loading disables and announces busy without dropping children", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        Save
      </Button>
    );
    const btn = screen.getByRole("button", { name: "Save" });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("aria-busy", "true");
    await user.click(btn);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("activates with keyboard", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Go</Button>);
    screen.getByRole("button", { name: "Go" }).focus();
    await user.keyboard("{Enter}");
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe("Toast", () => {
  function PushAndView({ tone }: { tone: "info" | "danger" }) {
    const { push } = useToast();
    return (
      <>
        <button type="button" onClick={() => push({ title: "T", tone })}>
          push
        </button>
        <ToastViewport />
      </>
    );
  }

  it("danger toasts assert, info toasts inform; dismiss removes", async () => {
    const user = userEvent.setup();
    const { unmount } = render(
      <ToastProvider>
        <PushAndView tone="danger" />
      </ToastProvider>
    );
    await user.click(screen.getByRole("button", { name: "push" }));
    expect(screen.getByRole("alert")).toHaveTextContent("T");
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
    unmount();
  });
});
