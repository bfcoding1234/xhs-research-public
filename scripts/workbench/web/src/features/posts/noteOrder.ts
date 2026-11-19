export function noteIdPrefix(noteId: string): string {
  return String(noteId || '').slice(0, 8);
}

export function compareNoteIdPrefix(left: string, right: string): number {
  return noteIdPrefix(left).localeCompare(noteIdPrefix(right));
}

export function sortByNoteIdPrefixDesc<T extends { note_id: string }>(values: readonly T[]): T[] {
  return [...values].sort((left, right) => compareNoteIdPrefix(right.note_id, left.note_id));
}
