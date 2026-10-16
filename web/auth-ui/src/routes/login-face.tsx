import { useMutation, useQuery } from "@tanstack/react-query";
import { FaceCapture, IdenError, Spinner } from "@iden/shared";
import { useState } from "react";
import { startFaceCheck, submitFace, type AuthStep } from "../api";
import { working } from "../auth-step";
import { AuthLayout } from "../AuthLayout";
import { FaceOutcome } from "./face-outcome";
import { SwitchMethod } from "./switch-method";

/** The face step. Each attempt fetches a fresh challenge: one is good for one capture. */
export function FaceStep({
  challengeId,
  clientName,
  onDone,
  onSwitch,
}: {
  challengeId: string;
  clientName: string;
  onDone: (result: AuthStep) => void;
  onSwitch?: () => void;
}) {
  const [attempt, setAttempt] = useState(0);

  const faceChallenge = useQuery({
    queryKey: ["face-challenge", challengeId, attempt],
    queryFn: () => startFaceCheck(challengeId),
    retry: false,
    staleTime: Infinity,
    gcTime: 0,
  });

  const submit = useMutation({
    mutationFn: (frames: Blob[]) =>
      submitFace({
        challengeId,
        faceChallengeId: faceChallenge.data?.faceChallengeId ?? "",
        frames,
      }),
    onSuccess: onDone,
  });

  const problem =
    submit.error instanceof IdenError
      ? submit.error
      : faceChallenge.error instanceof IdenError
        ? faceChallenge.error
        : null;
  function retry() {
    submit.reset();
    setAttempt((value) => value + 1);
  }

  return (
    <AuthLayout
      eyebrow={clientName}
      step="face"
      title="Confirm it's you"
      lede="Look at the camera and follow the prompts."
      footer={<SwitchMethod onSwitch={onSwitch} />}
    >
      {problem ? (
        <FaceOutcome problem={problem} onRetry={retry} onSwitch={onSwitch} />
      ) : working(submit) ? (
        <Spinner label={submit.isPending ? "Checking it's you" : `Returning to ${clientName}`} />
      ) : faceChallenge.data ? (
        <FaceCapture
          key={faceChallenge.data.faceChallengeId}
          challenge={faceChallenge.data}
          onCaptured={(frames) => submit.mutate(frames)}
        />
      ) : (
        <Spinner label="Preparing the camera" />
      )}
    </AuthLayout>
  );
}
