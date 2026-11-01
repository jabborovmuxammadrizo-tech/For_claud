import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

class Boundary extends React.Component<{ children: React.ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 40, fontFamily: "Segoe UI, sans-serif" }}>
          <h2 style={{ color: "#0F1F4B" }}>Something went wrong in this screen.</h2>
          <p style={{ color: "#475569" }}>Your documents are saved. Reload the window to continue.</p>
          <pre style={{ color: "#B91C1C", whiteSpace: "pre-wrap", fontSize: 12 }}>{this.state.error.message}</pre>
          <button onClick={() => location.reload()} style={{ marginTop: 16, padding: "8px 16px", background: "#1D4ED8", color: "#fff", border: 0, borderRadius: 8 }}>Reload</button>
        </div>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><Boundary><App /></Boundary></React.StrictMode>);
