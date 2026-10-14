import type { components } from "@iden/shared";
import { z } from "zod";

export type Preset = components["schemas"]["FieldPresetResponse"];

export const DATA_TYPES = [
  { value: "string", label: "Text" },
  { value: "integer", label: "Number" },
  { value: "boolean", label: "Yes or no" },
  { value: "date", label: "Date" },
  { value: "enum", label: "One of a list" },
  { value: "email", label: "Email address" },
  { value: "phone", label: "Phone number" },
  { value: "url", label: "URL" },
] as const;

export const schema = z
  .object({
    key: z
      .string()
      .min(1, "A key is required.")
      .regex(/^[a-z][a-z0-9_]*$/, "Lowercase, starting with a letter — e.g. `student_id`."),
    label: z.string().min(1, "Give the field a label."),
    description: z.string(),
    dataType: z.enum(["string", "integer", "boolean", "date", "enum", "email", "phone", "url"]),
    options: z.array(z.object({ value: z.string().min(1, "An option cannot be blank.") })),
    required: z.boolean(),
    unique: z.boolean(),
    userReadable: z.boolean(),
    userWritable: z.boolean(),
    groupId: z.string(),
    claimName: z.string(),
    claimScope: z.string(),
  })
  .refine((v) => v.dataType !== "enum" || v.options.length > 0, {
    path: ["options"],
    message: "A field of this type needs at least one option.",
  })
  .refine((v) => Boolean(v.claimName) === Boolean(v.claimScope), {
    path: ["claimScope"],
    message: "A claim name and a claim scope go together — a claim with no scope reaches everyone.",
  });

export type Values = z.infer<typeof schema>;

/** Not a preset key — presets are lowercase identifiers, so this cannot collide. */
export const BLANK_KEY = "\u0000blank";

export const BLANK: Values = {
  key: "",
  label: "",
  description: "",
  dataType: "string",
  options: [],
  required: false,
  unique: false,
  userReadable: true,
  userWritable: false,
  groupId: "",
  claimName: "",
  claimScope: "",
};

export function fromPreset(preset: Preset): Values {
  return {
    ...BLANK,
    key: preset.key,
    label: preset.label,
    description: preset.description,
    dataType: preset.dataType,
    options: preset.options.map((value) => ({ value })),
    required: preset.required,
    unique: preset.unique,
    userReadable: preset.userReadable,
    userWritable: preset.userWritable,
  };
}
