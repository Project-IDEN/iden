/** One URI per line, which is how every URI list in the console is entered. */
export const lines = (value: string) =>
  value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

/**
 * Has a scheme, which is all the server means by "absolute".
 *
 * Not `://`: a native app registers a private-use scheme with a single slash,
 * `com.example.app:/callback` (RFC 8252), and the provider documents that as a
 * valid redirect URI. Requiring `://` refuses it here and nowhere else.
 */
export const isAbsoluteUri = (value: string) => /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(value);
