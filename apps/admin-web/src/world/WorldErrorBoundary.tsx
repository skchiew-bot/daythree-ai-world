import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  failed: boolean;
}

export function WorldUnavailable() {
  return (
    <div role="alert" style={{ padding: "2rem 1rem", textAlign: "center", color: "var(--text-muted)" }}>
      The 3D view could not start on this device. The tables below still show every agent.
    </div>
  );
}

/** Keeps the rest of the page working when the 3D scene cannot start (no WebGL, or a
 * setup error). Errors thrown from the scene's effect land here. */
export class WorldErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error): void {
    console.error("3D world failed to start", error);
  }

  render(): ReactNode {
    return this.state.failed ? <WorldUnavailable /> : this.props.children;
  }
}
