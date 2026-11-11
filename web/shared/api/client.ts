import axios, { type AxiosInstance, type AxiosRequestConfig } from "axios";
import { toIdenError } from "./errors";

export interface ClientOptions {
  /** The provider's origin, e.g. `http://localhost:8000`. */
  issuer: string;
  /**
   * Send cookies. auth-ui must — the login and consent responses set
   * `iden_session`, and the browser will not store it otherwise. The dashboard
   * must not: it authenticates with a bearer token and never touches the
   * session cookie.
   */
  withCredentials: boolean;
  /** Supplies the current access token, when there is one. */
  getToken?: () => string | undefined;
  /** Called when a request is refused with `401`: the token is no longer good. */
  onUnauthorized?: () => void;
}

export function createClient({
  issuer,
  withCredentials,
  getToken,
  onUnauthorized,
}: ClientOptions): AxiosInstance {
  const client = axios.create({
    baseURL: issuer,
    withCredentials,
    headers: { Accept: "application/json" },
  });

  client.interceptors.request.use((config) => {
    const token = getToken?.();
    if (token) config.headers.set("Authorization", `Bearer ${token}`);
    return config;
  });

  // One place where every failure becomes an IdenError, so no screen ever reads
  // `error.response?.data?.detail` and guesses.
  client.interceptors.response.use(
    (response) => response,
    (error: unknown) => {
      const idenError = toIdenError(error);
      if (idenError.status === 401) onUnauthorized?.();
      return Promise.reject(idenError);
    },
  );

  return client;
}

/** `GET` returning the parsed body, which is what every caller actually wants. */
export async function get<T>(
  client: AxiosInstance,
  url: string,
  config?: AxiosRequestConfig,
): Promise<T> {
  const response = await client.get<T>(url, config);
  return response.data;
}
