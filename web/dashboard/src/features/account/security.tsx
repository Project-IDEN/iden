import { RowCard } from "@iden/shared";
import { useApi } from "../../app/api";
import { PageHeader } from "../../app/shell";
import { useProfile } from "./api";
import { FaceSetting } from "./security-face";
import { PasswordSetting } from "./security-password";
import { Setting } from "./security-setting";
import { TotpSetting } from "./security-totp";

export function SecurityRoute() {
  return (
    <>
      <PageHeader
        title="Security"
        lede="Your password, the address you sign in with, and your second factors."
      />
      <RowCard className="max-w-3xl">
        <PasswordSetting />
        <EmailSetting />
        <TotpSetting />
        <FaceSetting />
      </RowCard>
    </>
  );
}

function EmailSetting() {
  const api = useApi();
  const profile = useProfile(api);

  return (
    <Setting
      title="Sign-in address"
      status={
        profile.data ? (
          <>
            You sign in as <span className="text-body-strong">{profile.data.email}</span>. It was
            given to you by your organization and cannot be changed.
          </>
        ) : (
          "The address you sign in with."
        )
      }
    />
  );
}
