import { ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import type { ConsentText } from "../api";
import { BigButton, Screen } from "./layout";

/**
 * Before the camera turns on: what enrolling does, and the person's yes or no.
 *
 * The words come from IDEN, which knows what this deployment keeps, and the
 * version agreed to here goes back with the capture so IDEN records it. Saying
 * no returns to the idle screen with nothing captured.
 */
export function Consent({
  name,
  footer,
  consent,
  onAgree,
  onDecline,
}: {
  name: string | null;
  footer: ReactNode;
  consent: ConsentText;
  onAgree: () => void;
  onDecline: () => void;
}) {
  return (
    <Screen name={name} footer={footer} className="items-stretch text-left">
      <div className="flex items-center gap-4 short:gap-3">
        <ShieldCheck
          aria-hidden="true"
          className="h-10 w-10 shrink-0 text-primary short:h-8 short:w-8"
        />
        <h1 className="text-balance font-display text-display-md text-ink short:text-display-sm">
          {consent.title}
        </h1>
      </div>
      <ul className="flex flex-col gap-3 border-y border-hairline py-5 short:gap-1.5 short:py-3">
        {consent.statements.map((statement) => (
          <li key={statement} className="text-title-md text-body short:text-body-sm">
            {statement}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-4">
        <BigButton onClick={onAgree}>I agree, continue</BigButton>
        <BigButton variant="quiet" onClick={onDecline}>
          No, thanks
        </BigButton>
      </div>
    </Screen>
  );
}
