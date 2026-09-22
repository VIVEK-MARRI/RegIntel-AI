/**
 * Shared envelope + scalar contracts.
 * Backend sources: app/schemas (Paginated* models), app/api/v1/* list routes.
 *
 * Rule: every list endpoint declares its OWN envelope type below in its
 * domain file (bare array vs paginated object is per-endpoint, verified).
 * This file only holds the reusable paginated shape for endpoints that
 * provably return {items, total, page, page_size} (all Paginated* schemas
 * carry total/page/page_size; several also carry has_more).
 */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  has_more?: boolean;
}

/** Backend epoch timestamps are SECONDS (float); ISO strings stay strings. */
export type EpochSeconds = number;
export type IsoDateTime = string;
