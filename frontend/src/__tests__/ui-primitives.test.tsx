import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Button, Badge, Card, CardHeader, CardTitle, CardContent, Alert, Modal, Input, Select } from "../components/ui";

describe("Design System UI Primitives", () => {
  describe("Button Component", () => {
    it("renders with default primary variant and handles click", () => {
      const handleClick = vi.fn();
      render(<Button onClick={handleClick}>Deploy Mission</Button>);
      const btn = screen.getByRole("button", { name: /Deploy Mission/i });
      expect(btn).toBeDefined();
      fireEvent.click(btn);
      expect(handleClick).toHaveBeenCalledTimes(1);
    });

    it("displays loading spinner and disables when isLoading=true", () => {
      const handleClick = vi.fn();
      render(<Button isLoading onClick={handleClick}>Processing</Button>);
      const btn = screen.getByRole("button");
      expect(btn.hasAttribute("disabled")).toBe(true);
      fireEvent.click(btn);
      expect(handleClick).not.toHaveBeenCalled();
    });

    it("renders danger variant with proper styles", () => {
      render(<Button variant="danger">Kill Switch</Button>);
      const btn = screen.getByRole("button", { name: /Kill Switch/i });
      expect(btn.className).toContain("bg-danger");
    });
  });

  describe("Badge Component", () => {
    it("renders with variant and dot", () => {
      render(<Badge variant="success" dot>Online</Badge>);
      expect(screen.getByText("Online")).toBeDefined();
    });

    it("renders purple AI badge", () => {
      render(<Badge variant="purple">CISO Agent</Badge>);
      expect(screen.getByText("CISO Agent")).toBeDefined();
    });
  });

  describe("Card Component", () => {
    it("renders Card, Header, Title, and Content", () => {
      render(
        <Card>
          <CardHeader>
            <CardTitle>Threat Matrix</CardTitle>
          </CardHeader>
          <CardContent>
            <p>Active vulnerabilities identified</p>
          </CardContent>
        </Card>
      );
      expect(screen.getByText("Threat Matrix")).toBeDefined();
      expect(screen.getByText("Active vulnerabilities identified")).toBeDefined();
    });
  });

  describe("Alert Component", () => {
    it("renders warning alert with title and handles dismiss", () => {
      const handleDismiss = vi.fn();
      render(
        <Alert variant="warning" title="Scope Violation Alert" onDismiss={handleDismiss}>
          Out of scope packet dropped.
        </Alert>
      );
      expect(screen.getByText("Scope Violation Alert")).toBeDefined();
      expect(screen.getByText("Out of scope packet dropped.")).toBeDefined();

      const closeBtn = screen.getByLabelText(/Dismiss alert/i);
      fireEvent.click(closeBtn);
      expect(handleDismiss).toHaveBeenCalledTimes(1);
    });
  });

  describe("Modal Component", () => {
    it("does not render when isOpen=false", () => {
      render(
        <Modal isOpen={false} onClose={vi.fn()} title="Approval Gate">
          Content
        </Modal>
      );
      expect(screen.queryByText("Approval Gate")).toBeNull();
    });

    it("renders and handles close when isOpen=true", () => {
      const handleClose = vi.fn();
      render(
        <Modal isOpen={true} onClose={handleClose} title="Approval Gate GATE-01">
          Approve active exploit payload execution?
        </Modal>
      );
      expect(screen.getByText("Approval Gate GATE-01")).toBeDefined();
      expect(screen.getByText("Approve active exploit payload execution?")).toBeDefined();

      const closeBtn = screen.getByLabelText(/Close modal/i);
      fireEvent.click(closeBtn);
      expect(handleClose).toHaveBeenCalledTimes(1);
    });
  });

  describe("Input & Select Components", () => {
    it("renders Input with label and value", () => {
      render(<Input label="Target CIDR" placeholder="10.0.0.0/24" defaultValue="127.0.0.1/32" />);
      expect(screen.getByText("Target CIDR")).toBeDefined();
      const input = screen.getByPlaceholderText("10.0.0.0/24") as HTMLInputElement;
      expect(input.value).toBe("127.0.0.1/32");
    });

    it("renders Select with label and options", () => {
      render(
        <Select label="Provider" defaultValue="anthropic">
          <option value="openai">OpenAI</option>
          <option value="anthropic">Anthropic</option>
        </Select>
      );
      expect(screen.getByText("Provider")).toBeDefined();
      const select = screen.getByRole("combobox") as HTMLSelectElement;
      expect(select.value).toBe("anthropic");
    });
  });
});
