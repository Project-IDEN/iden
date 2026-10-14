import { Button, Field, IdenError, Input } from "@iden/shared";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "../../app/api";
import { Setting, StepUpNotice } from "./security-setting";

export function PasswordSetting() {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const [currentPassword, setCurrent] = useState("");
  const [newPassword, setNext] = useState("");

  const change = useMutation({
    mutationFn: async () => {
      const response = await api.post<{ sessionsEnded: number }>("/entity/credentials/password", {
        currentPassword,
        newPassword,
      });
      return response.data;
    },
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setOpen(false);
    },
  });

  const problem = change.error instanceof IdenError ? change.error : null;
  const ended = change.data?.sessionsEnded ?? 0;

  return (
    <Setting
      title="Password"
      status={
        change.isSuccess && !open
          ? `Changed. ${ended} other session${ended === 1 ? "" : "s"} signed out.`
          : "Changing it signs out every other session you have open."
      }
      action={
        <Button size="sm" variant={open ? "ghost" : "outline"} onClick={() => setOpen(!open)}>
          {open ? "Cancel" : "Change password"}
        </Button>
      }
    >
      {open ? (
        <form
          noValidate
          className="flex flex-col gap-5"
          onSubmit={(event) => {
            event.preventDefault();
            change.mutate();
          }}
        >
          <Field label="Current password">
            {(props) => (
              <Input
                {...props}
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(event) => setCurrent(event.target.value)}
              />
            )}
          </Field>
          <Field
            label="New password"
            hint="At least 12 characters."
            error={
              problem?.code === "same_password"
                ? "Choose a password you haven't used here."
                : undefined
            }
          >
            {(props) => (
              <Input
                {...props}
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(event) => setNext(event.target.value)}
              />
            )}
          </Field>

          <StepUpNotice problem={problem} />

          {problem && !problem.stepUpMaxAge && problem.code !== "same_password" ? (
            <p role="alert" className="text-body-sm text-error">
              {problem.code === "wrong_password"
                ? "That current password is not right."
                : problem.message}
            </p>
          ) : null}

          <Button
            type="submit"
            variant="default"
            className="self-start"
            disabled={change.isPending}
          >
            {change.isPending ? "Changing…" : "Change password"}
          </Button>
        </form>
      ) : null}
    </Setting>
  );
}
