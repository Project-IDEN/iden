import { get, usePage, type Page, type components } from "@iden/shared";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosInstance } from "axios";

type Schemas = components["schemas"];

export type ApiRecord = Schemas["ApiResponse"];
export type ScopeRecord = Schemas["ScopeResponse"];
export type RoleRecord = Schemas["RoleResponse"];
export type GroupRecord = Schemas["GroupResponse"];
export type MemberRecord = Schemas["MemberSummary"];
export type UserRecord = Schemas["UserResponse"];
export type UserCreated = Schemas["UserCreated"];
export type EffectiveScopes = Schemas["EffectiveScopes"];
export type ClientRecord = Schemas["ClientResponse"];
export type ClientCreated = Schemas["ClientCreated"];
export type ProfileFieldRecord = Schemas["ProfileFieldResponse"];
export type AuditEvent = Schemas["AuditEventResponse"];
export type KioskRecord = Schemas["KioskResponse"];
export type KioskCreated = Schemas["KioskCreated"];
export type KioskSettings = Schemas["KioskSettings"];
export type PairingCode = Schemas["PairingCode"];
export type KioskEnrolment = Schemas["KioskEnrolmentEvent"];

/** Lists share one hook; the resource is the URL and nothing else differs. */
export function useList<T>(api: AxiosInstance, url: string, params: Record<string, unknown> = {}) {
  return usePage<T>(api, url, params);
}

export function useRecord<T>(api: AxiosInstance, url: string, enabled = true) {
  return useQuery({ queryKey: [url], queryFn: () => get<T>(api, url), enabled });
}

/**
 * Every admin write invalidates the resource it touched. Optimistic updates are
 * deliberately absent: these screens change who can do what, and showing a
 * change that the server refused would be worse than a moment's wait.
 */
export function useWrite<TBody, TResult>(
  invalidate: string[],
  request: (body: TBody) => Promise<TResult>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: () =>
      Promise.all(
        invalidate.map((key) => queryClient.invalidateQueries({ queryKey: [key], exact: false })),
      ),
  });
}

/** Reads every page of a list — for the pickers, which need the whole set. */
export async function fetchAll<T>(api: AxiosInstance, url: string): Promise<T[]> {
  const items: T[] = [];
  let offset = 0;
  for (;;) {
    const page = await get<Page<T>>(api, url, { params: { limit: 200, offset } });
    items.push(...page.items);
    offset += page.meta.limit;
    if (offset >= page.meta.total) return items;
  }
}

/** A kiosk, polled quickly while a pairing code is showing so the page sees the
 * device pair, and slowly otherwise so its status stays current. */
export function useKiosk(api: AxiosInstance, kioskId: string, pairing: boolean) {
  const url = `/admin/kiosks/${kioskId}`;
  return useQuery({
    queryKey: [url],
    queryFn: () => get<Schemas["KioskResponse"]>(api, url),
    refetchInterval: pairing ? 3000 : 30_000,
    enabled: kioskId !== "",
  });
}

/** Whether the device paired after `issuedAt`, allowing for clock skew. */
export function pairedSince(kiosk: Schemas["KioskResponse"], issuedAt: number): boolean {
  return kiosk.pairedAt !== null && Date.parse(kiosk.pairedAt) >= issuedAt - 5000;
}
