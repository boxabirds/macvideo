export type FilterOption = {
  name: string;
  category: string;
  description: string;
};

export const FILTER_OPTIONS: FilterOption[] = [
  { name: "oil impasto", category: "rich colour", description: "Thick palette-knife paint with ridges catching light." },
  { name: "mosaic", category: "tactile", description: "Tile-by-tile composition with visible grout lines." },
  { name: "stained glass", category: "rich colour", description: "Lead-lined coloured-glass panels lit from behind." },
  { name: "claymation", category: "tactile", description: "Stop-motion clay figures with thumbprint imperfections." },
  { name: "watercolour", category: "medium transform", description: "Wet-on-wet washes, paper grain, and soft lost-and-found edges." },
  { name: "papercut", category: "medium transform", description: "Layered cut-paper diorama with visible fibre and cast shadows." },
  { name: "charcoal", category: "medium transform", description: "Vine-charcoal strokes, smudging, dust, and heavy blacks." },
  { name: "scratchboard", category: "high contrast", description: "White lines scratched from a solid black surface." },
  { name: "risograph", category: "high contrast", description: "Two-tone print grain with imperfect registration." },
  { name: "cyanotype", category: "monochrome", description: "Prussian-blue photograms with white subjects on blue ground." },
  { name: "sumi-e", category: "monochrome", description: "Minimal Zen brushwork with ink gesture and negative space." },
  { name: "daguerreotype", category: "monochrome", description: "Silvery antique photo surface with ghostly imperfections." },
  { name: "embroidery", category: "tactile", description: "Thread texture on linen with visible stitch direction." },
  { name: "double exposure", category: "conceptual", description: "Two images anatomically merged, such as a silhouette filled with landscape." },
  { name: "baroque chiaroscuro", category: "world reskin", description: "Caravaggio-dark scenes with one shaft of light pulling figures from blackness." },
  { name: "surrealist", category: "world reskin", description: "Dream-logic composition with impossible spatial relationships." },
];

export const FILTER_NAMES = FILTER_OPTIONS.map(option => option.name);

export type AbstractionOption = {
  value: number;
  label: string;
  description: string;
};

export const ABSTRACTION_OPTIONS: AbstractionOption[] = [
  { value: 0, label: "0 - literal", description: "Concrete, recognisable scenes with grounded proportions and depth." },
  { value: 25, label: "25 - expressive", description: "Still legible, but simplified through brushwork, line, and gesture." },
  { value: 50, label: "50 - stylised", description: "Figures and settings become reduced shapes and masses." },
  { value: 75, label: "75 - mostly abstract", description: "Details give way to rhythm, light, shadow, and visual weight." },
  { value: 100, label: "100 - pure abstraction", description: "Colour, line, rhythm, and texture replace recognisable objects." },
];

export function describeFilter(name: string | null | undefined): FilterOption | undefined {
  return FILTER_OPTIONS.find(option => option.name === name);
}

export function describeAbstraction(value: number | null | undefined): AbstractionOption | undefined {
  return ABSTRACTION_OPTIONS.find(option => option.value === value);
}
