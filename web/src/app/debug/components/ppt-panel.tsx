"use client";

import { EditableFilePanel } from "./editable-file-panel";

const defaultPrompt = "Create a \"Q2 2026 E-commerce Operations Report\" PPT for the management quarterly meeting, kept within 8 pages, in a business-tech style. Highlight sales growth, user growth, ad performance, and 618 campaign results, presented with line, bar, ring, and funnel charts.";

export function PptPanel() {
  return <EditableFilePanel title="PPT generation" kind="ppt" endpoint="/v1/ppt/generations" defaultPrompt={defaultPrompt} />;
}
