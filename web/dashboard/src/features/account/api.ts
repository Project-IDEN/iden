import { get, type components } from "@iden/shared";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosInstance } from "axios";

export type Profile = components["schemas"]["ProfileResponse"];
export type ProfileSchema = components["schemas"]["ProfileSchemaResponse"];
export type FieldSchema = components["schemas"]["FieldSchema"];
export type TotpStatus = components["schemas"]["TotpStatus"];
export type TotpEnrollment = components["schemas"]["TotpEnrollment"];
export type Sessions = components["schemas"]["SessionListResponse"];
export type Connections = components["schemas"]["ConnectionListResponse"];
export type Permissions = components["schemas"]["PermissionsResponse"];

export function useProfile(api: AxiosInstance, enabled = true) {
  return useQuery({
    queryKey: ["profile"],
    queryFn: () => get<Profile>(api, "/entity/profile"),
    enabled,
  });
}

export function useProfileSchema(api: AxiosInstance) {
  return useQuery({
    queryKey: ["profile-schema"],
    queryFn: () => get<ProfileSchema>(api, "/entity/profile/schema"),
  });
}

export function useUpdateProfile(api: AxiosInstance) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: { displayName?: string | null; fields: Record<string, unknown> }) => {
      const response = await api.patch<Profile>("/entity/profile", body);
      return response.data;
    },
    onSuccess: (profile) => queryClient.setQueryData(["profile"], profile),
  });
}

export function useUploadPhoto(api: AxiosInstance) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      const response = await api.put<Profile>("/entity/profile/photo", body);
      return response.data;
    },
    onSuccess: (profile) => queryClient.setQueryData(["profile"], profile),
  });
}

export function useRemovePhoto(api: AxiosInstance) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const response = await api.delete<Profile>("/entity/profile/photo");
      return response.data;
    },
    onSuccess: (profile) => queryClient.setQueryData(["profile"], profile),
  });
}

export function useTotpStatus(api: AxiosInstance) {
  return useQuery({ queryKey: ["totp"], queryFn: () => get<TotpStatus>(api, "/entity/totp") });
}

export function useSessions(api: AxiosInstance) {
  return useQuery({
    queryKey: ["sessions"],
    queryFn: () => get<Sessions>(api, "/entity/sessions"),
  });
}

export function useConnections(api: AxiosInstance) {
  return useQuery({
    queryKey: ["connections"],
    queryFn: () => get<Connections>(api, "/entity/connections"),
  });
}

export function usePermissions(api: AxiosInstance) {
  return useQuery({
    queryKey: ["permissions"],
    queryFn: () => get<Permissions>(api, "/entity/permissions"),
  });
}
