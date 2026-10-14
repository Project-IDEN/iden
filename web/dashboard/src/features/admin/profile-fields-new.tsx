import { Spinner, get } from "@iden/shared";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router";
import { useApi } from "../../app/api";
import { Wizard, type Step } from "../../app/wizard";
import { useWrite, type ProfileFieldRecord } from "./api";
import {
  BLANK,
  BLANK_KEY,
  fromPreset,
  schema,
  type Preset,
  type Values,
} from "./profile-field-form";
import { PresetPicker } from "./profile-field-presets";
import { DefinitionStep, ReleaseStep, ReviewStep, WhoStep } from "./profile-field-steps";

export function ProfileFieldCreateRoute() {
  const api = useApi();
  const navigate = useNavigate();

  const presets = useQuery({
    queryKey: ["profile-field-presets"],
    queryFn: () =>
      get<{ presets: Preset[] }>(api, "/admin/profile-fields/presets").then((r) => r.presets),
  });

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    mode: "onTouched",
    defaultValues: BLANK,
  });

  const create = useWrite<Values, ProfileFieldRecord>(["/admin/profile-fields"], async (values) => {
    const response = await api.post<ProfileFieldRecord>("/admin/profile-fields", {
      key: values.key,
      label: values.label,
      description: values.description || null,
      dataType: values.dataType,
      options: values.options.map((option) => option.value),
      required: values.required,
      unique: values.unique,
      userReadable: values.userReadable,
      userWritable: values.userWritable,
      groupId: values.groupId || null,
      claimName: values.claimName || null,
      claimScope: values.claimScope || null,
    });
    return response.data;
  });

  // Only so the step can show what was chosen when it is revisited — the
  // form already holds the answer.
  const [chosen, setChosen] = useState<string | null>(null);

  const steps: Step<Values>[] = [
    {
      id: "start",
      label: "Start",
      title: "Start from something, or from nothing",
      lede: "Presets are templates — nothing is created until the last step, and you can change every part of one first.",
      render: (_f, step) =>
        presets.isPending ? (
          <Spinner label="Loading presets" />
        ) : (
          <PresetPicker
            presets={presets.data ?? []}
            chosen={chosen}
            onPick={(preset) => {
              setChosen(preset.key);
              form.reset(fromPreset(preset));
              step.next();
            }}
            onBlank={() => {
              setChosen(BLANK_KEY);
              form.reset(BLANK);
              step.next();
            }}
          />
        ),
    },
    {
      id: "definition",
      label: "Definition",
      title: "What is being collected?",
      fields: ["key", "label", "description", "dataType", "options"],
      render: (f) => <DefinitionStep form={f} />,
    },
    {
      id: "who",
      label: "Who",
      title: "Who has it, and who may change it",
      lede: "The two questions that decide what self-service means for this field.",
      render: (f) => <WhoStep form={f} />,
    },
    {
      id: "claim",
      label: "Release",
      title: "Should applications receive it?",
      lede: "Fields are invisible to every application until both parts are set, and then only to one holding that scope. Data minimization by default.",
      fields: ["claimName", "claimScope"],
      render: (f) => <ReleaseStep form={f} />,
    },
    {
      id: "review",
      label: "Review",
      title: "Check this before it applies to anyone",
      lede: "The key, the type and uniqueness cannot be changed once values exist.",
      render: (f) => <ReviewStep form={f} />,
    },
  ];

  return (
    <Wizard
      form={form}
      steps={steps}
      title="Define a profile field"
      lede="Something this organization records about the people in it."
      section={{ label: "Profile fields", to: "/admin/profile-fields" }}
      backTo="/admin/profile-fields"
      backLabel="Back to profile fields"
      submitLabel="Create field"
      pending={create.isPending}
      error={create.error}
      onSubmit={(values) =>
        create.mutate(values, { onSuccess: () => void navigate("/admin/profile-fields") })
      }
    />
  );
}
