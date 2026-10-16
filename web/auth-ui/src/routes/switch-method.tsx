/** Back to the choice of second method, when there is more than one. */
export function SwitchMethod({ onSwitch }: { onSwitch?: () => void }) {
  if (!onSwitch) return null;
  return (
    <button
      type="button"
      className="text-primary underline-offset-2 hover:underline"
      onClick={onSwitch}
    >
      Use another method
    </button>
  );
}
