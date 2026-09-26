import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { FoundryApp } from "./app";

describe("Mosaic Canvas Agent Assembly", () => {
  it("creates a floating Agent node from a template", async () => {
    const user = userEvent.setup();
    render(<FoundryApp />);

    await user.click(screen.getByTestId("template-support"));

    expect(screen.getByTestId("agent-node-support-agent")).toBeInTheDocument();
    expect(within(screen.getByTestId("agent-node-support-agent")).getByText("Support guide")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Overview" })).toBeInTheDocument();
  });

  it("drops a Tool onto an Agent and opens a configuration modal", async () => {
    const user = userEvent.setup();
    render(<FoundryApp />);
    await user.click(screen.getByTestId("template-support"));

    const paletteTool = screen.getByTestId("palette-web_search");
    const dropzone = screen.getByTestId("agent-dropzone-support-agent");
    const dataTransfer = { value: "", setData: (_type: string, value: string) => { dataTransfer.value = value; }, getData: () => dataTransfer.value };
    fireEvent.dragStart(paletteTool, { dataTransfer });
    fireEvent.dragOver(dropzone, { dataTransfer });
    fireEvent.drop(dropzone, { dataTransfer });

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Configure Web Search")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Equip resource" }));

    const agent = screen.getByTestId("agent-node-support-agent");
    expect(within(agent).getByText("Web Search")).toBeInTheDocument();
  });

  it("adds a Workflow as an optional Agent capability", async () => {
    const user = userEvent.setup();
    render(<FoundryApp />);
    await user.click(screen.getByTestId("template-support"));
    const workflow = screen.getByTestId("palette-research-and-cite");
    const dropzone = screen.getByTestId("agent-dropzone-support-agent");
    const dataTransfer = { value: "", setData: (_type: string, value: string) => { dataTransfer.value = value; }, getData: () => dataTransfer.value };
    fireEvent.dragStart(workflow, { dataTransfer });
    fireEvent.drop(dropzone, { dataTransfer });
    await user.click(screen.getByRole("button", { name: "Equip resource" }));

    await user.click(screen.getByRole("tab", { name: "Workflows" }));
    const inspector = screen.getByLabelText("Agent inspector");
    expect(within(inspector).getAllByText("Research & Cite").length).toBeGreaterThanOrEqual(1);
    expect(within(inspector).getByText("Optional behavior module")).toBeInTheDocument();
  });

  it("keeps Agentic as the default mode while allowing system prompt editing", async () => {
    const user = userEvent.setup();
    render(<FoundryApp />);
    await user.click(screen.getByTestId("template-support"));

    expect(screen.getByLabelText("Behavior mode")).toHaveValue("agentic");
    const prompt = screen.getByLabelText("System prompt");
    await user.clear(prompt);
    await user.type(prompt, "Use the equipped capabilities and explain uncertainty.");
    expect(prompt).toHaveValue("Use the equipped capabilities and explain uncertainty.");
  });
});
