import { forwardRef } from "react";
import "./ShinyButton.css";

// Ported from neuro-portfolio components/ui/shiny-button.tsx (styled-jsx → CSS file).
export const ShinyButton = forwardRef(function ShinyButton(
  { children, onClick, className = "" },
  ref,
) {
  return (
    <button ref={ref} className={`shiny-cta ${className}`} onClick={onClick}>
      <span>{children}</span>
    </button>
  );
});

export default ShinyButton;
