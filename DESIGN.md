---
version: 1
name: iden-design-system
description: The visual system of IDEN's three screens — the hosted sign-in page, the dashboard, and the kiosk. A warm off-white canvas, one terracotta accent used sparingly, a serif display for headings and a humanist sans for everything a person reads or types. Implemented once in web/shared/tokens/theme.css; token names below match it one to one.

colors:
  primary: "#cc785c"
  primary-active: "#a9583e"
  primary-disabled: "#e6dfd8"
  on-primary: "#ffffff"
  canvas: "#faf9f5"
  surface-soft: "#f5f0e8"
  surface-card: "#efe9de"
  surface-cream-strong: "#e8e0d2"
  surface-dark: "#181715"
  surface-dark-elevated: "#252320"
  surface-dark-soft: "#1f1e1b"
  ink: "#141413"
  body-strong: "#252523"
  body: "#3d3d3a"
  muted-foreground: "#6c6a64"
  muted-soft: "#8e8b82"
  on-dark: "#faf9f5"
  on-dark-soft: "#a09d96"
  hairline: "#e6dfd8"
  hairline-soft: "#ebe6df"
  hairline-dark: "#302e2a"
  row-hover: "#f5f0e8"
  accent-teal: "#5db8a6"
  accent-amber: "#e8a55a"
  success: "#5db872"
  warning: "#d4a017"
  error: "#c64545"

typography:
  display-xl:
    {
      fontFamily: "EB Garamond, Garamond, serif",
      fontSize: 64px,
      fontWeight: 400,
      lineHeight: 1.05,
      letterSpacing: -1.5px,
    }
  display-lg:
    {
      fontFamily: "EB Garamond, Garamond, serif",
      fontSize: 48px,
      fontWeight: 400,
      lineHeight: 1.1,
      letterSpacing: -1px,
    }
  display-md:
    {
      fontFamily: "EB Garamond, Garamond, serif",
      fontSize: 36px,
      fontWeight: 400,
      lineHeight: 1.15,
      letterSpacing: -0.5px,
    }
  display-sm:
    {
      fontFamily: "EB Garamond, Garamond, serif",
      fontSize: 28px,
      fontWeight: 400,
      lineHeight: 1.2,
      letterSpacing: -0.3px,
    }
  title-lg:
    {
      fontFamily: "Inter, sans-serif",
      fontSize: 22px,
      fontWeight: 500,
      lineHeight: 1.3,
    }
  title-md:
    {
      fontFamily: "Inter, sans-serif",
      fontSize: 18px,
      fontWeight: 500,
      lineHeight: 1.4,
    }
  title-sm:
    {
      fontFamily: "Inter, sans-serif",
      fontSize: 16px,
      fontWeight: 500,
      lineHeight: 1.4,
    }
  body-md:
    {
      fontFamily: "Inter, sans-serif",
      fontSize: 16px,
      fontWeight: 400,
      lineHeight: 1.55,
    }
  body-sm:
    {
      fontFamily: "Inter, sans-serif",
      fontSize: 14px,
      fontWeight: 400,
      lineHeight: 1.55,
    }
  caption:
    {
      fontFamily: "Inter, sans-serif",
      fontSize: 13px,
      fontWeight: 500,
      lineHeight: 1.4,
    }
  caption-upper:
    {
      fontFamily: "Inter, sans-serif",
      fontSize: 12px,
      fontWeight: 500,
      lineHeight: 1.4,
      letterSpacing: 1.5px,
    }
  code:
    {
      fontFamily: "JetBrains Mono, monospace",
      fontSize: 14px,
      fontWeight: 400,
      lineHeight: 1.6,
    }
  button:
    {
      fontFamily: "Inter, sans-serif",
      fontSize: 14px,
      fontWeight: 500,
      lineHeight: 1,
    }

rounded:
  xs: 4px
  sm: 6px
  md: 8px
  lg: 12px
  xl: 16px
  full: 9999px

spacing:
  unit: 4px
  control: 40px
  row: 44px
  section: 96px

components:
  button-primary:
    {
      backgroundColor: "{colors.primary}",
      textColor: "{colors.on-primary}",
      typography: "{typography.button}",
      rounded: "{rounded.md}",
      height: "{spacing.control}",
    }
  button-primary-active: { backgroundColor: "{colors.primary-active}" }
  button-primary-disabled:
    {
      backgroundColor: "{colors.primary-disabled}",
      textColor: "{colors.muted-foreground}",
    }
  button-secondary:
    {
      backgroundColor: "{colors.canvas}",
      textColor: "{colors.ink}",
      border: "1px {colors.hairline}",
      rounded: "{rounded.md}",
      height: "{spacing.control}",
    }
  button-destructive:
    {
      backgroundColor: "{colors.error}",
      textColor: "{colors.on-primary}",
      rounded: "{rounded.md}",
      height: "{spacing.control}",
    }
  text-input:
    {
      backgroundColor: "{colors.canvas}",
      textColor: "{colors.ink}",
      border: "1px {colors.hairline}",
      rounded: "{rounded.md}",
      height: "{spacing.control}",
    }
  card:
    {
      backgroundColor: "{colors.canvas}",
      border: "1px {colors.hairline}",
      rounded: "{rounded.lg}",
    }
  table-row:
    {
      height: "{spacing.row}",
      hover: "{colors.row-hover}",
      divider: "1px {colors.hairline-soft}",
    }
  badge:
    {
      backgroundColor: "{colors.surface-card}",
      textColor: "{colors.ink}",
      typography: "{typography.caption}",
      rounded: "{rounded.full}",
    }
  secret-reveal:
    {
      backgroundColor: "{colors.surface-dark}",
      textColor: "{colors.on-dark}",
      typography: "{typography.code}",
      rounded: "{rounded.lg}",
    }
  focus-ring: { outline: "2px {colors.primary}", offset: 2px }
---

# IDEN design system

IDEN has three screens, used by three different people in three different moods:

1. **The sign-in page** (`web/auth-ui`). Seen by everyone, for seconds at a time, often when
   they are in a hurry to get somewhere else. It must be calm, quick to read, and impossible to
   mistake for a phishing page.
2. **The dashboard** (`web/dashboard`). A member's own account and security, and the
   administrators' working surface: tables of people, roles, clients and audit events, read
   carefully and acted on deliberately.
3. **The kiosk** (`kiosk/client`). A touch screen in a public place, read from arm's length by
   someone enrolling their face for the first time.

One visual language covers all three, defined once in
[`web/shared/tokens/theme.css`](web/shared/tokens/theme.css). The kiosk carries a copy of that file
because it builds on its own device; change both together. **Nothing in any app declares a colour, a
type size or a radius of its own**: a value resolves to a token here or it does not exist.

## Principles

- **Quiet by default, loud on purpose.** Almost everything is ink on a warm off-white canvas. The
  terracotta `primary` marks the one action a screen is for: _Continue_, _Approve_, _Enrol_. A
  screen with two primary buttons has not decided what it is for.
- **Trust is legible.** An identity provider is asked for passwords, so its screens must look
  deliberate and consistent everywhere, not decorated. The same layout, type and wording on every
  sign-in step is itself a security property: a person learns what the real page looks like.
- **Identifiers are monospace.** Scope values, client IDs, audiences, UUIDs and token IDs are set
  in JetBrains Mono (`.font-identity`), with ligatures off. People copy them, compare them character
  by character and paste them into configuration, so they must never look like prose.
- **Colour-block first, shadow rare.** Depth comes from a hairline border or a step in surface tone,
  not from drop shadows.
- **Accessible is not optional.** Every interactive element shows the focus ring. Every input has a
  visible label. Motion respects `prefers-reduced-motion`.

## Colour

### Accent

| Token              | Value     | Use                                                                     |
| ------------------ | --------- | ----------------------------------------------------------------------- |
| `primary`          | `#cc785c` | The screen's primary action; the focus ring; text selection (22% tint). |
| `primary-active`   | `#a9583e` | Primary while pressed.                                                  |
| `primary-disabled` | `#e6dfd8` | Primary that cannot be pressed yet.                                     |
| `on-primary`       | `#ffffff` | Text on a primary or destructive button.                                |

### Surfaces

| Token                                         | Value                 | Use                                                                                                                       |
| --------------------------------------------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `canvas`                                      | `#faf9f5`             | Every page's background, and cards on it. Warm, not pure white, so long admin sessions are easier on the eyes.            |
| `surface-soft`                                | `#f5f0e8`             | Secondary buttons' hover, muted panels, row hover (`row-hover`).                                                          |
| `surface-card`                                | `#efe9de`             | Badges and the occasional emphasised panel.                                                                               |
| `surface-cream-strong`                        | `#e8e0d2`             | The selected item in a tab strip or a sidebar.                                                                            |
| `surface-dark`                                | `#181715`             | A one-time secret being revealed (a new password, a client secret): the dark block says _this is different, copy it now_. |
| `surface-dark-elevated` / `surface-dark-soft` | `#252320` / `#1f1e1b` | Controls and code inside a dark block.                                                                                    |

There are only these surfaces. A new screen that seems to need another tone should use a hairline
instead.

### Text and lines

| Token                      | Value                 | Use                                                                   |
| -------------------------- | --------------------- | --------------------------------------------------------------------- |
| `ink`                      | `#141413`             | Headings, primary text, table cell values.                            |
| `body-strong`              | `#252523`             | Emphasised running text.                                              |
| `body`                     | `#3d3d3a`             | Running text.                                                         |
| `muted-foreground`         | `#6c6a64`             | Labels, helper text, secondary table columns.                         |
| `muted-soft`               | `#8e8b82`             | Timestamps, fine print. Never for anything a person must read to act. |
| `on-dark` / `on-dark-soft` | `#faf9f5` / `#a09d96` | Text on dark surfaces.                                                |
| `hairline`                 | `#e6dfd8`             | Borders of inputs and cards.                                          |
| `hairline-soft`            | `#ebe6df`             | Dividers between table rows.                                          |
| `hairline-dark`            | `#302e2a`             | Dividers on dark surfaces.                                            |

### Status

| Token                          | Value                 | Use                                                                             |
| ------------------------------ | --------------------- | ------------------------------------------------------------------------------- |
| `success`                      | `#5db872`             | Active, enrolled, healthy.                                                      |
| `warning`                      | `#d4a017`             | Needs attention, not broken: an uncalibrated threshold, a kiosk out of service. |
| `error`                        | `#c64545`             | Errors, validation, destructive buttons.                                        |
| `accent-teal` / `accent-amber` | `#5db8a6` / `#e8a55a` | Status dots and small category markers. Not for text.                           |

Status is never carried by colour alone: every dot or badge also has a word.

## Typography

Three self-hosted families, through `@fontsource`. A CDN is not an option: the provider's CSP is
`default-src 'none'`, and IDEN deploys without internet egress.

- **EB Garamond**, weight 400 only, for page and section headings (`h1`–`h3`). Negative tracking at
  display sizes; never bold.
- **Inter** (variable) for everything else: body, labels, buttons, tables.
- **JetBrains Mono** (variable) for identifiers and code.

| Token           | Size | Weight | Line height | Tracking | Use                                                                  |
| --------------- | ---- | ------ | ----------- | -------- | -------------------------------------------------------------------- |
| `display-xl`    | 64px | 400    | 1.05        | -1.5px   | Kiosk titles, read from arm's length.                                |
| `display-lg`    | 48px | 400    | 1.1         | -1px     | Kiosk titles on a short screen.                                      |
| `display-md`    | 36px | 400    | 1.15        | -0.5px   | Dashboard page titles.                                               |
| `display-sm`    | 28px | 400    | 1.2         | -0.3px   | Sign-in page titles; dashboard sub-pages.                            |
| `title-lg`      | 22px | 500    | 1.3         | 0        | Section headings inside a page.                                      |
| `title-md`      | 18px | 500    | 1.4         | 0        | Card titles, dialog titles.                                          |
| `title-sm`      | 16px | 500    | 1.4         | 0        | List-item titles.                                                    |
| `body-md`       | 16px | 400    | 1.55        | 0        | Running text, inputs.                                                |
| `body-sm`       | 14px | 400    | 1.55        | 0        | Table cells, helper text.                                            |
| `caption`       | 13px | 500    | 1.4         | 0        | Field labels, badges.                                                |
| `caption-upper` | 12px | 500    | 1.4         | 1.5px    | Eyebrows above a title (the application's name on the sign-in page). |
| `code`          | 14px | 400    | 1.6         | 0        | Identifiers, secrets.                                                |
| `button`        | 14px | 500    | 1           | 0        | Button labels.                                                       |

## Layout

- **Spacing** is a 4px grid. Tailwind's own unit is 4px, so the scale maps one to one (`p-3` is
  12px, `p-8` is 32px). `section` (96px) separates the major bands of the kiosk's screens.
- **Controls** are 40px tall (`control`); **table rows** 44px (`row`), which is also the minimum
  touch target.
- **Sign-in page:** one centred column at most 26rem (416px) wide. The organisation's logo above, the
  application's name as an eyebrow, one title, one form, one primary button.
- **Dashboard:** a sidebar of sections (each shown only if the person holds its read scope), and a
  content column at most 1000px wide. Lists are tables; a row opens the record.
- **Kiosk:** full-screen, one step per screen, a single large primary button within thumb reach.
  Titles use the largest display sizes, because the screen is read standing up.

## Shape and depth

| Token  | Value  | Use                                              |
| ------ | ------ | ------------------------------------------------ |
| `xs`   | 4px    | The focus ring's corners; tiny chips.            |
| `sm`   | 6px    | Menu items.                                      |
| `md`   | 8px    | Buttons, inputs, tabs.                           |
| `lg`   | 12px   | Cards, dialogs, secret reveals.                  |
| `xl`   | 16px   | The camera frame on the kiosk and the face step. |
| `full` | 9999px | Badges, avatars, status dots.                    |

Depth: flat by default; a 1px `hairline` border for cards and inputs; a faint shadow
(`0 1px 3px rgb(20 20 19 / 8%)`) only on floating layers: menus, popovers, dialogs.

## Components

The components live in [`web/shared/ui`](web/shared/ui). Most are shadcn/ui components, unmodified:
`theme.css` defines shadcn's semantic names (`background`, `foreground`, `muted`, `border`, `ring`,
…) in terms of the palette above, so a component pulled from the registry needs no restyling.

- **Button**: `primary` for the screen's one action, `secondary` (hairline outline) for the rest,
  `destructive` for anything that deletes or revokes. A destructive action always goes through
  `ConfirmDialog`, which names what will be lost.
- **Field**: label above, input, then helper or error text below, wired with `htmlFor` and
  `aria-describedby`. Errors appear in `error`, beside the field they concern, in words that say
  what to do next.
- **Feedback**: one `Notice` for every error a server returns, so a problem looks the same
  everywhere; `Spinner` with a label for loading; `ErrorState` with a retry for a failed load;
  and an empty state that says what would appear here and how to add the first one.
- **SecretRevealOnce**: a dark block showing a new password or client secret exactly once, with a
  copy button and the warning that it will not be shown again.
- **Provenance**: for each of a person's permissions, where it came from (direct, a role, a group).
  The answer an administrator needs before removing anything.
- **Data table**: 44px rows, a hairline between them, `row-hover` on hover, identifiers in
  monospace, and status as a dot plus a word.
- **Face capture**: the camera in an `xl`-rounded frame, a guide for where the face goes, and one
  instruction at a time in `title-lg`.

## Motion

Only one transition carries meaning: `.step-in` (200ms, a 6px rise and fade) between sign-in steps.
Password, authenticator code and consent read as one conversation continuing, not three pages. With
`prefers-reduced-motion`, every animation collapses to nothing.

## Writing

The words are part of the design.

- Say what happened and what to do next: "That code has expired. Enter the new one from your
  authenticator app." Not "Invalid input".
- Never reveal whether an account exists. A wrong email and a wrong password get the same message.
- Name things the way the person knows them: _your account_, _Security_, _sign in_. Not _entity_,
  _credential store_, _authenticate_.
- _Enrol_ and _enrolment_ in prose; the API's identifiers say `/enroll`.
