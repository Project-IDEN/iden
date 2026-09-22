import { get, type components } from "@iden/shared";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosInstance } from "axios";

type Schemas = components["schemas"];

export type Application = Schemas["ApplicationResponse"];
export type ApplicationCreated = Schemas["ApplicationCreated"];
export type ApplicationList = Schemas["ApplicationList"];

export const APPLICATIONS = "/developer/clients";

export function useApplications(api: AxiosInstance) {
  return useQuery({
    queryKey: [APPLICATIONS],
    queryFn: () => get<ApplicationList>(api, APPLICATIONS),
  });
}

export function useApplication(api: AxiosInstance, id: string) {
  return useQuery({
    queryKey: [`${APPLICATIONS}/${id}`],
    queryFn: () => get<Application>(api, `${APPLICATIONS}/${id}`),
  });
}

/**
 * Every write refetches the list and the record it touched. The list carries
 * `remaining`, which a create or a delete changes, so invalidating only the
 * record would leave the allowance stale.
 */
export function useApplicationWrite<TBody, TResult>(
  id: string | null,
  request: (body: TBody) => Promise<TResult>,
) {
  const queryClient = useQueryClient();
  const keys = id ? [APPLICATIONS, `${APPLICATIONS}/${id}`] : [APPLICATIONS];

  return useMutation({
    mutationFn: request,
    onSuccess: () =>
      Promise.all(keys.map((key) => queryClient.invalidateQueries({ queryKey: [key] }))),
  });
}
