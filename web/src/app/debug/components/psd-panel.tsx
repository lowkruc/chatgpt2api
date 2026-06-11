"use client";

import { EditableFilePanel } from "./editable-file-panel";

const defaultPrompt = "Split the poster elements by their original positions and merge them into an editable PSD, keeping the background and each element layer position, and also output a zip of each layer asset.";

export function PsdPanel() {
  return <EditableFilePanel title="PSD generation" kind="psd" endpoint="/v1/psd/generations" defaultPrompt={defaultPrompt} imageRequired />;
}
