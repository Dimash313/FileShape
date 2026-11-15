/** Restore keyboard focus to the same photo after an up/down reorder.
 * A button becomes disabled at either boundary, so prefer its opposite control.
 */
export type BatchReorderDirection = -1 | 1;
export type BatchReorderFocus = { index: number; direction: BatchReorderDirection };

export function nextBatchReorderFocus(
  index: number,
  direction: BatchReorderDirection,
  count: number,
): BatchReorderFocus | null {
  if (!Number.isSafeInteger(index) || !Number.isSafeInteger(count) ||
      count < 2 || index < 0 || index >= count ||
      (direction !== -1 && direction !== 1)) return null;
  const destination = index + direction;
  if (destination < 0 || destination >= count) return null;

  return {
    index: destination,
    direction: destination === 0 ? 1 : destination === count - 1 ? -1 : direction,
  };
}
