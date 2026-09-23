import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
  Button,
  Card,
  CardContent,
  cn,
  ErrorState,
  Mark,
} from "@iden/shared";
import { ArrowLeft, Check } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { FieldValues, Path, UseFormReturn } from "react-hook-form";
import { Link, useNavigate } from "react-router";

/** What a step can do to the flow it sits in. */
export interface StepControls {
  /**
   * Move on, validating this step's fields first.
   *
   * For a step whose whole content *is* a choice — picking a preset, say —
   * making that choice is the answer, and asking for a second click on
   * Continue only to confirm it is a click that carries no information.
   */
  next: () => void;
}

/**
 * One step of a creation flow.
 *
 * `fields` is what makes per-step validation possible: react-hook-form validates
 * exactly those paths when Continue is pressed, so a later step's empty required
 * field cannot block an earlier one.
 */
export interface Step<T extends FieldValues> {
  id: string;
  /** Two or three words. It sits in the stepper, where there is no room. */
  label: string;
  title: string;
  lede?: string;
  fields?: Path<T>[];
  render: (form: UseFormReturn<T>, step: StepControls) => ReactNode;
}

/**
 * The rail of numbered steps.
 *
 * Steps behind the current one become a check rather than staying numbered — the
 * number is only useful while it tells you how far there is to go. `furthest`
 * decides only what is clickable: going back to change an answer is a normal
 * thing to want, and a step ahead of you is still ahead of you however far you
 * walked before turning back.
 */
function Stepper({
  steps,
  current,
  furthest,
  onJump,
}: {
  steps: { id: string; label: string }[];
  current: number;
  furthest: number;
  onJump: (index: number) => void;
}) {
  return (
    <ol className="mb-8 flex list-none flex-wrap items-center gap-y-3 p-0">
      {steps.map((step, index) => {
        const done = index < current;
        const active = index === current;
        const reachable = index <= furthest;

        return (
          <li key={step.id} className="flex items-center">
            <button
              type="button"
              disabled={!reachable}
              onClick={() => reachable && onJump(index)}
              aria-current={active ? "step" : undefined}
              className={cn(
                "flex items-center gap-2 rounded-full py-1 pl-1 pr-3 text-caption transition-colors duration-100",
                active && "bg-primary text-primary-foreground",
                !active && reachable && "text-body hover:bg-secondary",
                !reachable && "cursor-default text-muted-soft",
              )}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-caption tabular-nums",
                  active && "bg-primary-foreground/20 text-primary-foreground",
                  done && !active && "bg-primary text-primary-foreground",
                  !done && !active && "border border-border text-muted-foreground",
                )}
              >
                {done && !active ? <Check className="h-3 w-3" /> : index + 1}
              </span>
              {step.label}
            </button>
            {index < steps.length - 1 ? (
              <span
                aria-hidden="true"
                className={cn("mx-1 h-px w-6 sm:w-10", done ? "bg-primary/40" : "bg-border")}
              />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

/**
 * A multi-step creation flow.
 *
 * A page rather than a dialog, and several steps rather than one long form.
 * These objects decide what an application may do and who may do it — a client's
 * redirect URIs, a role's scopes — and a modal with fourteen fields invites
 * scrolling past the ones that matter. One decision per screen, then a review
 * that shows the whole answer before anything is created.
 */
export function Wizard<T extends FieldValues>({
  form,
  steps,
  title,
  lede,
  section,
  backTo,
  backLabel,
  submitLabel,
  onSubmit,
  pending,
  error,
}: {
  form: UseFormReturn<T>;
  steps: Step<T>[];
  title: string;
  lede?: string;
  /** Where this sits in the rail, for the breadcrumb. */
  section: { label: string; to: string };
  backTo: string;
  backLabel: string;
  submitLabel: string;
  onSubmit: (values: T) => void;
  pending?: boolean;
  error?: unknown;
}) {
  const navigate = useNavigate();
  const [current, setCurrent] = useState(0);
  // How far the flow has been validated, so the stepper knows what is reachable
  // and a step revisited from the review does not reset progress.
  const [furthest, setFurthest] = useState(0);

  const step = steps[current];
  const isLast = current === steps.length - 1;
  if (!step) return null;

  async function next() {
    const fields = step?.fields;
    if (fields?.length && !(await form.trigger(fields))) return;

    if (isLast) {
      void form.handleSubmit(onSubmit)();
      return;
    }
    const advanced = current + 1;
    setCurrent(advanced);
    setFurthest((far) => Math.max(far, advanced));
  }

  return (
    <>
      <Breadcrumb className="mb-6">
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={section.to}>{section.label}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>New</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <header className="mb-8">
        <Link
          to={backTo}
          className="inline-flex items-center gap-1.5 text-caption text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft aria-hidden="true" className="h-3.5 w-3.5" />
          {backLabel}
        </Link>
        <h1 className="mt-3 text-display-md">{title}</h1>
        <p className="mt-2 flex items-center gap-2 text-caption-upper uppercase text-muted-foreground">
          <Mark className="h-3 w-3 text-primary" />
          Step {current + 1} of {steps.length} · {step.label}
        </p>
        {lede ? <p className="mt-3 max-w-prose text-body-md text-body">{lede}</p> : null}
      </header>

      <Stepper steps={steps} current={current} furthest={furthest} onJump={setCurrent} />

      <Card>
        <CardContent>
          <h2 className="text-title-lg text-foreground">{step.title}</h2>
          {step.lede ? (
            <p className="mt-1 max-w-prose text-body-sm text-muted-foreground">{step.lede}</p>
          ) : null}
          <div className="mt-6">{step.render(form, { next: () => void next() })}</div>
        </CardContent>
      </Card>

      {error ? (
        <div className="mt-6">
          <ErrorState error={error} />
        </div>
      ) : null}

      <div className="mt-8 flex items-center justify-between gap-4">
        <Button
          type="button"
          variant="outline"
          onClick={() => (current === 0 ? void navigate(backTo) : setCurrent(current - 1))}
        >
          {current === 0 ? "Cancel" : "Back"}
        </Button>
        <Button type="button" variant="default" disabled={pending} onClick={() => void next()}>
          {isLast ? (pending ? "Working…" : submitLabel) : "Continue"}
        </Button>
      </div>
    </>
  );
}

/**
 * A read-back of one answer on the review step.
 *
 * The review exists so that the thing being created is legible in one screen
 * before it exists — these objects are hard to reason about after the fact, and
 * "nothing was set" is an answer worth showing rather than an empty row.
 */
export function ReviewItem({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap justify-between gap-x-6 gap-y-1 border-b border-hairline-soft py-3 last:border-b-0">
      <dt className="text-body-sm text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right text-body-sm text-body-strong">{children}</dd>
    </div>
  );
}

export function ReviewList({ children }: { children: ReactNode }) {
  return <dl className="m-0">{children}</dl>;
}

/** What a review row shows when the answer was left empty. */
export function NotSet() {
  return <span className="text-muted-soft">Not set</span>;
}
