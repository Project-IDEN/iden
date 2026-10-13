import type { ReactNode } from "react";
import { Lede, Screen, Title } from "./layout";

/** A kiosk that cannot enrol anyone right now, and says why. */
export function Unavailable({
  name,
  title,
  children,
}: {
  name?: string | null;
  title: string;
  children: ReactNode;
}) {
  return (
    <Screen name={name}>
      <Title>{title}</Title>
      <Lede>{children}</Lede>
    </Screen>
  );
}
