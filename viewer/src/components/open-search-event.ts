/**
 * Cross-component contract for opening the global search overlay with a
 * pre-filled query.
 *
 * Lives in a tiny standalone module so AppShell can import it without
 * pulling in ConceptGraph's graph renderer bundle. Producers (e.g. ConceptGraph
 * detail panel quick links) dispatch this event on `window`; AppShell is
 * the sole consumer and maps it to its `isSearchOpen` state.
 *
 * `detail.query` MUST be treated as untrusted text — it comes from
 * concept-graph data which is already sanitised on the API edge but
 * still arbitrary.
 */
export const OPEN_SEARCH_EVENT = 'ahadiff:open-search';

export interface OpenSearchEventDetail {
  /** Concept name to seed the global search overlay's input. */
  query: string;
}
