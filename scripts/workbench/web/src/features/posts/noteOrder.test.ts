import { describe, expect, it } from 'vitest';
import { compareNoteIdPrefix, noteIdPrefix, sortByNoteIdPrefixDesc } from './noteOrder';

describe('note ID ordering', () => {
  it('exposes the first eight characters', () => {
    expect(noteIdPrefix('100000030000000000000003')).toBe('10000003');
  });

  it('sorts fixed-width hexadecimal prefixes in publication order', () => {
    const values = ['100000010000000000000001', '100000030000000000000003'];
    expect(values.sort(compareNoteIdPrefix)).toEqual([
      '100000010000000000000001',
      '100000030000000000000003',
    ]);
  });

  it('orders posts by the first eight characters descending without mutating the input', () => {
    const values = [
      { note_id: '100000010000000000000001' },
      { note_id: '100000030000000000000003' },
      { note_id: '100000020000000000000002' },
    ];

    expect(sortByNoteIdPrefixDesc(values).map((post) => post.note_id)).toEqual([
      '100000030000000000000003',
      '100000020000000000000002',
      '100000010000000000000001',
    ]);
    expect(values.map((post) => post.note_id)).toEqual([
      '100000010000000000000001',
      '100000030000000000000003',
      '100000020000000000000002',
    ]);
  });
});
