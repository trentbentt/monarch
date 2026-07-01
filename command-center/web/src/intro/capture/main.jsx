import { createRoot } from "react-dom/client";
import CaptureRunner from "./CaptureRunner.jsx";

// No StrictMode here — its double-mount would create two WebGL contexts and
// confuse the deterministic single-canvas capture.
createRoot(document.getElementById("root")).render(<CaptureRunner />);
